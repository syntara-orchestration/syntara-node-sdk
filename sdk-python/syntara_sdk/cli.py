"""Command line tooling for scaffolding and packaging nodes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
import yaml

from .compiler import compile_manifest
from .registry.oci_client import OCI_ARTIFACT_TYPE, OCI_MANIFEST_ANNOTATION, OCIRegistryClient

SHARED_SCRIPT_IMAGE = "quay.io/syntara/script-python-executor:latest"
SHARED_HTTP_IMAGE = "quay.io/syntara/http-request-executor:latest"
_NODE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _manifest(name: str, tier: int, image: str) -> dict[str, Any]:
    execution: dict[str, Any] = {"type": "container", "image": image}
    if tier == 1:
        execution = {"type": "in_process", "image": None, "entrypoint": None}
    return {
        "apiVersion": "syntara.io/v1alpha1",
        "kind": "NodeType",
        "metadata": {
            "name": name,
            "displayName": name.replace("_", " ").title(),
            "version": "0.1.0",
            "icon": "terminal",
            "description": f"Custom tier {tier} node.",
            "tags": [f"execution:{execution['type']}", "category:task"],
            "author": "",
            "license": "Apache-2.0",
        },
        "spec": {
            "category": "task",
            "execution": execution,
            "inputs": {"type": "object", "properties": {}, "required": []},
            "outputs": {
                "allOf": [
                    {
                        "$ref": "../../schemas/common-definitions.json#/definitions/StandardOutputWrapper"
                    }
                ]
            },
            "executionTimeout": 300,
        },
    }


def init_node(path: Path, name: str, tier: int, image: str | None) -> None:
    """Create a Tier 2 script package or Tier 3 image package."""

    if not _NODE_NAME.fullmatch(name):
        raise ValueError("name must be lowercase snake_case")
    if tier not in {2, 3}:
        raise ValueError("--tier must be 2 or 3")
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"target directory is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)

    resolved_image = image or f"quay.io/example/{name}:0.1.0"
    manifest = _manifest(name, tier, resolved_image)
    (path / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))

    if tier == 2:
        (path / "main.py").write_text(
            """from typing import Any\n\n\ndef main(inputs: dict[str, Any]) -> dict[str, Any]:\n    return {\"result\": inputs}\n\n\nif __name__ == \"__main__\":\n    print(main({}))\n"""
        )
    else:
        (path / "Containerfile").write_text(
            """FROM python:3.12-slim\nCOPY main.py /app/main.py\nENTRYPOINT [\"python\", \"/app/main.py\"]\n"""
        )
        (path / "main.py").write_text(
            """import json\nimport sys\n\n\nif __name__ == \"__main__\":\n    payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}\n    print(json.dumps({\"result\": payload}))\n"""
        )


def _oci_manifest(manifest: dict[str, Any], image_ref: str | None = None) -> dict[str, Any]:
    """Return an OCI image manifest carrying the node YAML as an annotation."""

    image = image_ref or manifest["spec"]["execution"]["image"]
    if not isinstance(image, str) or image in {SHARED_SCRIPT_IMAGE, SHARED_HTTP_IMAGE}:
        raise ValueError("build packages Tier 3 nodes and requires a dedicated image")
    raw_yaml = yaml.safe_dump(manifest, sort_keys=False)
    empty_config = b"{}"
    digest = "sha256:" + hashlib.sha256(empty_config).hexdigest()
    return {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": OCI_ARTIFACT_TYPE,
        "config": {
            "mediaType": "application/vnd.oci.empty.v1+json",
            "digest": digest,
            "size": len(empty_config),
        },
        "layers": [],
        "annotations": {
            OCI_MANIFEST_ANNOTATION: raw_yaml,
            "org.opencontainers.image.title": manifest["metadata"]["name"],
            "org.opencontainers.image.version": manifest["metadata"]["version"],
            "org.opencontainers.image.ref.name": image,
        },
    }


def build_node(manifest_path: Path, output: Path, image_ref: str | None = None) -> Path:
    """Validate a Tier 3 manifest and write an OCI layout or manifest JSON."""

    manifest = compile_manifest(manifest_path)
    if manifest["spec"]["execution"]["type"] != "container":
        raise ValueError("build requires a container-backed Tier 3 manifest")
    oci_manifest = _oci_manifest(manifest, image_ref)
    encoded = json.dumps(oci_manifest, indent=2, sort_keys=True).encode()

    if output.suffix == ".json":
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(encoded)
        return output

    digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
    config = b"{}"
    config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
    blob_root = output / "blobs" / "sha256"
    blob_root.mkdir(parents=True, exist_ok=True)
    (blob_root / config_digest.removeprefix("sha256:")).write_bytes(config)
    (blob_root / digest.removeprefix("sha256:")).write_bytes(encoded)
    (output / "oci-layout").write_text(json.dumps({"imageLayoutVersion": "1.0.0"}, indent=2) + "\n")
    (output / "index.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "artifactType": OCI_ARTIFACT_TYPE,
                        "digest": digest,
                        "size": len(encoded),
                        "annotations": {
                            "org.opencontainers.image.ref.name": image_ref
                            or manifest["spec"]["execution"]["image"]
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return output


class SyntaraRegistrationError(RuntimeError):
    """Raised when the platform catalog cannot accept a published node."""


def register_with_syntara(
    image_ref: str,
    api_url: str,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Register a published OCI node in Syntara's node catalog."""

    owns_client = client is None
    http_client = client or httpx.Client(timeout=10.0)
    url = f"{api_url.rstrip('/')}/api/v1/node-types"
    try:
        try:
            response = http_client.post(url, json={"image_ref": image_ref})
        except httpx.HTTPError as exc:
            raise SyntaraRegistrationError(f"could not reach Syntara at {url}: {exc}") from exc
        if response.is_error:
            raise SyntaraRegistrationError(
                f"Syntara registration failed with HTTP {response.status_code}: {response.text[:500]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SyntaraRegistrationError("Syntara registration returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise SyntaraRegistrationError("Syntara registration returned a non-object response")
        return payload
    finally:
        if owns_client:
            http_client.close()


def push_node(
    manifest_path: Path,
    image_ref: str,
    *,
    registry_client: OCIRegistryClient | None = None,
    register_api_url: str | None = None,
    registration_client: httpx.Client | None = None,
) -> str:
    """Push a Tier 3 manifest and optionally register it with Syntara."""

    manifest = compile_manifest(manifest_path)
    if manifest["spec"]["execution"]["type"] != "container":
        raise ValueError("push requires a container-backed Tier 3 manifest")
    manifest = {
        **manifest,
        "spec": {
            **manifest["spec"],
            "execution": {**manifest["spec"]["execution"], "image": image_ref},
        },
    }
    oci_manifest = _oci_manifest(manifest, image_ref)
    owns_client = registry_client is None
    client = registry_client or OCIRegistryClient()
    try:
        digest = client.push_manifest(image_ref, oci_manifest)
    finally:
        if owns_client:
            client.close()
    if register_api_url:
        register_with_syntara(image_ref, register_api_url, client=registration_client)
    return digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="syntara-cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="scaffold a node package")
    init_parser.add_argument("name")
    init_parser.add_argument("--tier", type=int, choices=[2, 3], required=True)
    init_parser.add_argument("--path", type=Path, default=None)
    init_parser.add_argument("--image")

    build_parser = subparsers.add_parser("build", help="package a Tier 3 node as an OCI artifact")
    build_parser.add_argument("manifest", type=Path)
    build_parser.add_argument("--output", type=Path, default=Path("oci-layout"))
    build_parser.add_argument("--image", help="dedicated image reference override")

    push_parser = subparsers.add_parser("push", help="push a Tier 3 manifest to an OCI registry")
    push_parser.add_argument("manifest", type=Path, nargs="?", default=Path("manifest.yaml"))
    push_parser.add_argument(
        "--registry",
        required=True,
        help="destination image reference, e.g. localhost:5000/syntara/nodes/my-node:1.0.0",
    )
    push_parser.add_argument(
        "--api-url",
        default=os.getenv("SYNTARA_API_URL", "http://localhost:5173"),
        help="Syntara API base URL used to register the pushed node",
    )
    push_parser.add_argument(
        "--skip-register",
        action="store_true",
        help="publish to the OCI registry without registering in Syntara",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init_node(args.path or Path(args.name), args.name, args.tier, args.image)
            return 0
        if args.command == "build":
            result = build_node(args.manifest, args.output, args.image)
            print(result)
        else:
            digest = push_node(
                args.manifest,
                args.registry,
                register_api_url=None if args.skip_register else args.api_url,
            )
            if digest:
                print(digest)
            if not args.skip_register:
                print(f"registered {args.registry} with {args.api_url}")
        return 0
    except (
        FileExistsError,
        FileNotFoundError,
        ValueError,
        SyntaraRegistrationError,
        yaml.YAMLError,
    ) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
