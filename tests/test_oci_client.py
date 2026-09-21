import json
from pathlib import Path

import httpx
import yaml

from syntara_sdk.cli import init_node, push_node
from syntara_sdk.registry.oci_client import OCIRegistryClient
from syntara_sdk.registry.service import OCI_ARTIFACT_TYPE, OCI_MANIFEST_ANNOTATION


def _artifact(manifest: dict) -> dict:
    return {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": OCI_ARTIFACT_TYPE,
        "config": {"mediaType": "application/vnd.oci.empty.v1+json", "digest": "sha256:config", "size": 2},
        "layers": [],
        "annotations": {OCI_MANIFEST_ANNOTATION: yaml.safe_dump(manifest)},
    }


def test_inspect_reads_annotation_without_fetching_layers(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.yaml"
    init_node(tmp_path / "node", "node", 3, "localhost:5000/syntara/nodes/node:1.0.0")
    manifest_path = tmp_path / "node" / "manifest.yaml"
    artifact = _artifact(yaml.safe_load(manifest_path.read_text()))
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json=artifact)

    with OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(handler)) as client:
        result = client.inspect_oci_manifest_annotations("localhost:5000/syntara/nodes/node:1.0.0")

    assert result["metadata"]["name"] == "node"
    assert requests == ["/v2/syntara/nodes/node/manifests/1.0.0"]


def test_discover_lists_only_annotated_node_images() -> None:
    manifest = {
        "metadata": {"name": "market-node", "displayName": "Market Node", "version": "1.0.0"},
        "spec": {"category": "task", "execution": {"type": "container", "image": "ignored"}},
    }
    artifact = _artifact(manifest)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/_catalog":
            return httpx.Response(200, json={"repositories": ["syntara/nodes/market-node"]})
        if request.url.path.endswith("/tags/list"):
            return httpx.Response(200, json={"name": "syntara/nodes/market-node", "tags": ["1.0.0"]})
        return httpx.Response(200, json=artifact)

    with OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(handler)) as client:
        discovered = client.discover_node_manifests()

    assert discovered[0][0] == "localhost:5000/syntara/nodes/market-node:1.0.0"
    assert discovered[0][1]["metadata"]["displayName"] == "Market Node"


def test_push_sends_metadata_manifest_to_mock_registry(tmp_path: Path) -> None:
    source = tmp_path / "node"
    init_node(source, "push_node", 3, "localhost:5000/syntara/nodes/push_node:1.0.0")
    pushed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, headers={"Location": "/v2/syntara/nodes/push_node/blobs/uploads/abc"})
        if request.method == "PUT" and "/manifests/" in request.url.path:
            pushed["manifest"] = json.loads(request.content)
            return httpx.Response(201, headers={"Docker-Content-Digest": "sha256:published"})
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    with OCIRegistryClient("http://localhost:5000", transport=transport) as client:
        digest = push_node(
            source / "manifest.yaml",
            "localhost:5000/syntara/nodes/push_node:1.0.0",
            registry_client=client,
        )

    assert digest == "sha256:published"
    assert pushed["manifest"]["artifactType"] == OCI_ARTIFACT_TYPE
    embedded = pushed["manifest"]["annotations"][OCI_MANIFEST_ANNOTATION]
    assert "localhost:5000/syntara/nodes/push_node:1.0.0" in embedded


def test_push_registers_with_syntara_after_publishing(tmp_path: Path) -> None:
    source = tmp_path / "node"
    init_node(source, "joined_node", 3, "localhost:5000/syntara/nodes/joined_node:1.0.0")
    registration_requests: list[tuple[str, dict[str, object]]] = []

    def registry_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, headers={"Location": "/v2/syntara/nodes/joined_node/blobs/uploads/abc"})
        if request.method == "PUT" and "/manifests/" in request.url.path:
            return httpx.Response(201, headers={"Docker-Content-Digest": "sha256:published"})
        return httpx.Response(201)

    def api_handler(request: httpx.Request) -> httpx.Response:
        registration_requests.append((str(request.url), json.loads(request.content)))
        return httpx.Response(201, json={"data": {"metadata": {"name": "joined_node"}}})

    with (
        OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(registry_handler)) as registry,
        httpx.Client(transport=httpx.MockTransport(api_handler)) as api,
    ):
        digest = push_node(
            source / "manifest.yaml",
            "localhost:5000/syntara/nodes/joined_node:1.0.0",
            registry_client=registry,
            register_api_url="http://syntara.local",
            registration_client=api,
        )

    assert digest == "sha256:published"
    assert registration_requests == [
        (
            "http://syntara.local/api/v1/node-types",
            {"image_ref": "localhost:5000/syntara/nodes/joined_node:1.0.0"},
        )
    ]
