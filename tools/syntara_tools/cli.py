"""Command line tooling for scaffolding and packaging steps."""

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

from syntara_tools.compiler import (
    PluginDiscoveryError,
    discover_plugin,
    load_manifest,
    validate_manifest,
    validate_plugin_manifest,
)
from syntara_tools.oci_client import (
    OCI_ARTIFACT_TYPE,
    OCI_CONFIG_MEDIA_TYPE,
    OCI_PLUGIN_MANIFEST_MEDIA_TYPE,
    OCIRegistryClient,
    parse_image_reference,
)

_STEP_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _manifest(name: str, tier: int) -> dict[str, Any]:
    step_class = _step_class_name(name)
    return {
        "apiVersion": "syntara.io/v1alpha1",
        "kind": "StepType",
        "metadata": {
            "name": name,
            "displayName": name.replace("_", " ").title(),
            "icon": "terminal",
            "description": f"Custom tier {tier} step.",
            "tags": [],
            "license": "Apache-2.0",
        },
        "spec": {
            "category": "task",
            "execution": {"entrypoint": f"steps.{name}.main:{step_class}"},
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


def _plugin_manifest(name: str, namespace: str, image: str) -> dict[str, Any]:
    """Return the root manifest owning the one plugin runtime image."""
    return {
        "apiVersion": "syntara.io/v1alpha1",
        "kind": "Plugin",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "displayName": name.replace("_", " ").title(),
            "version": "0.1.0",
            "description": f"Custom plugin containing the {name} step.",
            "authors": [{"name": "Plugin Author"}],
        },
        "spec": {
            "targets": [f"steps/{name}/manifest.yaml"],
            "runtime": {"image": image},
        },
    }


def _step_class_name(name: str) -> str:
    """Derive the BaseStep subclass name used by the plugin registration."""

    return "".join(part.title() for part in name.split("_")) + "Step"


def _step_module(class_name: str) -> str:
    """Scaffold a BaseStep subclass for plugin-level registration."""

    return f'''"""Step implementation registered by this plugin's runtime."""

from pydantic import BaseModel

from syntara_sdk import ExecutionContext, TaskStep


class {class_name}Input(BaseModel):
    """Typed inputs. Keep in sync with spec.inputs in manifest.yaml."""


class {class_name}Output(BaseModel):
    """Inner Result payload; the base class wraps it in StandardOutputWrapper."""


class {class_name}(TaskStep[{class_name}Input, {class_name}Output]):
    def __init__(self) -> None:
        super().__init__({class_name}Input, {class_name}Output)

    def run(
        self, inputs: {class_name}Input, context: ExecutionContext
    ) -> {class_name}Output:
        raise NotImplementedError("implement the step logic")
'''


def _runtime_module(namespace: str, plugin_name: str, step_name: str, class_name: str) -> str:
    """Generate the one image-level registration point for a scaffolded plugin."""
    identity = f"{namespace}/{plugin_name}/{step_name}"
    return f'''"""Plugin-level runtime registration for every bundled step."""

from syntara_sdk import PluginRuntime
from steps.{step_name}.main import {class_name}


def create_runtime() -> PluginRuntime:
    runtime = PluginRuntime("{namespace}/{plugin_name}")
    runtime.register("{identity}", {class_name})
    return runtime
'''


def _resolve_within(candidate: Path, base: Path) -> Path:
    """Resolve ``candidate`` and refuse to escape ``base``.

    Scaffolding paths may arrive from a CLI argument, which in an agentic
    workflow can be model-generated rather than typed by a person. A value
    like ``../../etc`` would otherwise write files outside the project, so the
    resolved target must stay inside the base directory.
    """

    base = base.resolve()
    target = (base / candidate).resolve()
    if target != base and base not in target.parents:
        raise ValueError(f"path escapes the base directory {base}: {candidate}")
    return target


def init_step(
    path: Path,
    name: str,
    tier: int,
    image: str | None,
    base_dir: Path | None = None,
    namespace: str = "syntara",
) -> None:
    """Create a plugin root with one registered initial step.

    The generated root owns one runtime image and one dispatcher. Additional
    steps belong under ``steps/`` and register in ``plugin_runtime.py``.
    """

    if not _STEP_NAME.fullmatch(name):
        raise ValueError("name must be lowercase snake_case")
    if tier not in {2, 3}:
        raise ValueError("--tier must be 2 or 3")
    path = _resolve_within(path, base_dir if base_dir is not None else Path.cwd())
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"target directory is not empty: {path}")

    if not _STEP_NAME.fullmatch(namespace):
        raise ValueError("namespace must be lowercase snake_case")
    resolved_image = image or f"quay.io/example/{name}@sha256:" + "0" * 64
    manifest = _manifest(name, tier)
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("generated manifest is invalid:\n" + "\n".join(errors))
    plugin_manifest = _plugin_manifest(name, namespace, resolved_image)
    plugin_errors = validate_plugin_manifest(plugin_manifest)
    if plugin_errors:
        raise ValueError("generated plugin runtime is invalid:\n" + "\n".join(plugin_errors))
    path.mkdir(parents=True, exist_ok=True)
    step_dir = path / "steps" / name
    step_dir.mkdir(parents=True)
    (path / "plugin.yaml").write_text(
        yaml.safe_dump(plugin_manifest, sort_keys=False)
    )
    (path / "steps" / "__init__.py").write_text("")
    (step_dir / "__init__.py").write_text("")
    (step_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    (step_dir / "main.py").write_text(_step_module(_step_class_name(name)))
    (path / "plugin_runtime.py").write_text(
        _runtime_module(namespace, name, name, _step_class_name(name))
    )
    if tier == 3:
        (path / "Containerfile").write_text(
            "FROM docker.io/library/python:3.12-slim\n"
            "RUN pip install --no-cache-dir syntara-sdk\n"
            "COPY . /app\n"
            "WORKDIR /app\n"
            "USER 1000:1000\n"
            'CMD ["python", "-m", "syntara_sdk.runner", "--runtime-module", "plugin_runtime"]\n'
        )


def _oci_manifest(plugin_path: Path, image_ref: str) -> tuple[dict[str, Any], bytes]:
    """Return an OCI manifest and its plugin metadata layer contents."""

    # The artifact ref is where the plugin is published. It is unrelated to
    # plugin.spec.runtime.image, which names the runtime for every step.
    if not isinstance(image_ref, str) or not image_ref:
        raise ValueError("publishing requires an artifact reference (--registry)")
    parse_image_reference(image_ref)
    plugin = discover_plugin(plugin_path)
    # Keep the metadata payload independent from the OCI layout.  The OCI
    # client owns transport-specific constants and can change them without
    # changing compiler output or the distribution boundary.
    raw_yaml = yaml.safe_dump(
        {
            "plugin": plugin.manifest,
            "steps": [step.indexed_data() for step in plugin.steps],
        },
        sort_keys=False,
    ).encode()
    empty_config = b"{}"
    config_digest = "sha256:" + hashlib.sha256(empty_config).hexdigest()
    layer_digest = "sha256:" + hashlib.sha256(raw_yaml).hexdigest()
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": OCI_ARTIFACT_TYPE,
        "config": {
            "mediaType": OCI_CONFIG_MEDIA_TYPE,
            "digest": config_digest,
            "size": len(empty_config),
        },
        "layers": [
            {
                "mediaType": OCI_PLUGIN_MANIFEST_MEDIA_TYPE,
                "digest": layer_digest,
                "size": len(raw_yaml),
                "annotations": {"org.opencontainers.image.title": "plugin.yaml"},
            }
        ],
        "annotations": {
            "org.opencontainers.image.title": plugin.manifest["metadata"]["name"],
            "org.opencontainers.image.ref.name": image_ref,
            "org.syntara.plugin.version": plugin.manifest["metadata"]["version"],
            "org.syntara.plugin.step_count": str(len(plugin.steps)),
            "org.syntara.plugin.categories": ",".join(
                sorted({step.manifest["spec"]["category"] for step in plugin.steps})
            ),
        },
    }
    return manifest, raw_yaml


def build_plugin(plugin_path: Path, output: Path, image_ref: str) -> Path:
    """Build one root plugin artifact containing all explicitly targeted steps."""

    oci_manifest, layer_contents = _oci_manifest(plugin_path, image_ref)
    encoded = json.dumps(oci_manifest, indent=2, sort_keys=True).encode()

    if output.suffix == ".json":
        raise ValueError(
            "build output must be an OCI layout directory; a standalone manifest JSON "
            "omits the referenced config and layer blobs"
        )

    digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
    config = b"{}"
    config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
    layer_digest = "sha256:" + hashlib.sha256(layer_contents).hexdigest()
    blob_root = output / "blobs" / "sha256"
    blob_root.mkdir(parents=True, exist_ok=True)
    (blob_root / config_digest.removeprefix("sha256:")).write_bytes(config)
    (blob_root / layer_digest.removeprefix("sha256:")).write_bytes(layer_contents)
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
                        "annotations": {"org.opencontainers.image.ref.name": image_ref},
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return output


class SyntaraRegistrationError(RuntimeError):
    """Raised when the platform catalog cannot accept a published plugin."""


def register_with_syntara(
    image_ref: str,
    api_url: str,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Register a published OCI plugin in Syntara's plugin catalog."""

    owns_client = client is None
    http_client = client or httpx.Client(timeout=10.0)
    url = f"{api_url.rstrip('/')}/api/v1/plugins"
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


def push_plugin(
    plugin_path: Path,
    image_ref: str,
    *,
    registry_client: OCIRegistryClient | None = None,
    register_api_url: str | None = None,
    registration_client: httpx.Client | None = None,
) -> str:
    """Publish one plugin artifact and optionally register the plugin release."""

    oci_manifest, layer_contents = _oci_manifest(plugin_path, image_ref)
    owns_client = registry_client is None
    client = registry_client or OCIRegistryClient()
    try:
        digest = client.push_manifest(image_ref, oci_manifest, layer_contents=[layer_contents])
    finally:
        if owns_client:
            client.close()
    if register_api_url:
        parsed = parse_image_reference(image_ref)
        canonical_image_ref = f"{parsed.registry}/{parsed.repository}@{digest}"
        register_with_syntara(canonical_image_ref, register_api_url, client=registration_client)
    return digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="syntara-cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="scaffold a step package")
    init_parser.add_argument("name")
    init_parser.add_argument("--tier", type=int, choices=[2, 3], required=True)
    init_parser.add_argument("--path", type=Path, default=None)
    init_parser.add_argument("--image")
    init_parser.add_argument("--namespace", default="syntara")

    validate_parser = subparsers.add_parser(
        "validate", help="validate a standalone manifest.yaml or root plugin.yaml"
    )
    validate_parser.add_argument("manifest", type=Path)

    build_parser = subparsers.add_parser("build", help="package a root plugin as an OCI artifact")
    build_parser.add_argument("plugin", type=Path)
    build_parser.add_argument("--output", type=Path, default=Path("oci-layout"))
    build_parser.add_argument("--registry", required=True, help="destination plugin artifact reference")

    push_parser = subparsers.add_parser("push", help="push a root plugin to an OCI registry")
    push_parser.add_argument("plugin", type=Path, nargs="?", default=Path("plugin.yaml"))
    push_parser.add_argument(
        "--registry",
        required=True,
        help="destination plugin artifact reference, e.g. localhost:5000/syntara/plugins/my-plugin:1.0.0",
    )
    push_parser.add_argument(
        "--api-url",
        default=os.getenv("SYNTARA_API_URL", "http://localhost:5173"),
        help="Syntara API base URL used to register the pushed plugin",
    )
    push_parser.add_argument(
        "--skip-register",
        action="store_true",
        help="publish to the OCI registry without registering in Syntara",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init_step(
                args.path or Path(args.name),
                args.name,
                args.tier,
                args.image,
                namespace=args.namespace,
            )
            return 0
        if args.command == "validate":
            document = load_manifest(args.manifest)
            if document.get("kind") == "Plugin":
                descriptor = discover_plugin(args.manifest)
                print(f"validated plugin with {len(descriptor.steps)} step(s)")
                return 0
            errors = validate_manifest(document)
            if errors:
                raise ValueError("Manifest validation failed:\n" + "\n".join(errors))
            print("validated step manifest")
            return 0
        if args.command == "build":
            output = _resolve_within(args.output, Path.cwd())
            result = build_plugin(args.plugin, output, args.registry)
            print(result)
        else:
            digest = push_plugin(
                args.plugin,
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
        PluginDiscoveryError,
        SyntaraRegistrationError,
        yaml.YAMLError,
    ) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
