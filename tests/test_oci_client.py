import hashlib
import json
from pathlib import Path

import httpx
import pytest
import yaml
from syntara_tools.cli import init_step, push_plugin
from syntara_tools.compiler import discover_plugin, validate_manifest, validate_plugin_manifest
from syntara_tools.oci_client import (
    OCI_ARTIFACT_TYPE,
    OCI_CONFIG_MEDIA_TYPE,
    OCI_PLUGIN_MANIFEST_MEDIA_TYPE,
    OCIRegistryClient,
    OCIRegistryError,
    parse_image_reference,
)


def _artifact(manifest: dict) -> dict:
    raw_manifest = yaml.safe_dump(manifest).encode()
    plugin = manifest.get("plugin", {})
    metadata = plugin.get("metadata", {}) if isinstance(plugin, dict) else {}
    return {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": OCI_ARTIFACT_TYPE,
        "config": {"mediaType": "application/vnd.unknown.config.v1+json", "digest": "sha256:config", "size": 2},
        "layers": [
            {
                "mediaType": OCI_PLUGIN_MANIFEST_MEDIA_TYPE,
                "digest": "sha256:" + hashlib.sha256(raw_manifest).hexdigest(),
                "size": len(raw_manifest),
            }
        ],
        "annotations": {"org.opencontainers.image.title": metadata.get("name", "plugin")},
    }


def _plugin_source(tmp_path: Path, name: str) -> Path:
    image = f"localhost:5000/syntara/runtimes/{name}@sha256:" + "b" * 64
    init_step(tmp_path / name, name, 3, image, base_dir=tmp_path)
    plugin = {
        "apiVersion": "syntara.io/v1alpha1",
        "kind": "Plugin",
        "metadata": {
            "name": f"{name}_plugin",
            "namespace": "syntara",
            "displayName": f"{name} plugin",
            "version": "1.0.0",
            "description": "Test plugin.",
            "authors": [{"name": "Example"}],
        },
        "spec": {
            "targets": [f"{name}/steps/{name}/manifest.yaml"],
            "runtime": {"image": image},
        },
    }
    path = tmp_path / "plugin.yaml"
    path.write_text(yaml.safe_dump(plugin), encoding="utf-8")
    return path


def test_inspect_reads_plugin_metadata_layer(tmp_path: Path) -> None:
    descriptor = discover_plugin(_plugin_source(tmp_path, "step"))
    payload = {"plugin": descriptor.manifest, "steps": [step.indexed_data() for step in descriptor.steps]}
    artifact = _artifact(payload)
    requests: list[str] = []

    raw_manifest = yaml.safe_dump(payload).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if "/blobs/" in request.url.path:
            return httpx.Response(200, content=raw_manifest)
        return httpx.Response(200, json=artifact)

    with OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(handler)) as client:
        result = client.inspect_plugin_metadata("localhost:5000/syntara/plugins/test:1.0.0")

    assert result["plugin"]["metadata"]["name"] == "step_plugin"
    assert requests == [
        "/v2/",
        "/v2/syntara/plugins/test/manifests/1.0.0",
        "/v2/syntara/plugins/test/blobs/sha256:" + hashlib.sha256(raw_manifest).hexdigest(),
    ]


def test_inspect_rejects_a_layer_digest_mismatch() -> None:
    payload = {
        "plugin": {"metadata": {"name": "test-plugin"}},
        "steps": [],
    }
    artifact = _artifact(payload)
    raw_payload = yaml.safe_dump(payload).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        if "/blobs/" in request.url.path:
            return httpx.Response(200, content=b"x" * len(raw_payload))
        return httpx.Response(200, json=artifact)

    with OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OCIRegistryError, match="digest does not match"):
            client.inspect_plugin_metadata("localhost:5000/syntara/plugins/test:1.0.0")


@pytest.mark.parametrize("mutation", ["invalid-step", "wrong-identity", "wrong-content-digest"])
def test_inspect_rejects_invalid_embedded_plugin_metadata(tmp_path: Path, mutation: str) -> None:
    descriptor = discover_plugin(_plugin_source(tmp_path, "validated"))
    payload = {"plugin": descriptor.manifest, "steps": [step.indexed_data() for step in descriptor.steps]}
    step = payload["steps"][0]
    if mutation == "invalid-step":
        step["manifest"]["spec"]["execution"] = {"image": "invalid"}
    elif mutation == "wrong-identity":
        step["identity"] = "other/plugin/step"
    else:
        step["contentDigest"] = "sha256:" + "0" * 64
    artifact = _artifact(payload)
    raw_payload = yaml.safe_dump(payload).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        if "/blobs/" in request.url.path:
            return httpx.Response(200, content=raw_payload)
        return httpx.Response(200, json=artifact)

    with OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OCIRegistryError, match="plugin metadata validation failed"):
            client.inspect_plugin_metadata("localhost:5000/syntara/plugins/test:1.0.0")


def test_discover_lists_only_supplied_plugin_artifacts(tmp_path: Path) -> None:
    descriptor = discover_plugin(_plugin_source(tmp_path, "market"))
    payload = {"plugin": descriptor.manifest, "steps": [step.indexed_data() for step in descriptor.steps]}
    artifact = _artifact(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/_catalog":
            raise AssertionError("registry catalog must not be queried")
        if "/blobs/" in request.url.path:
            return httpx.Response(200, content=yaml.safe_dump(payload).encode())
        return httpx.Response(200, json=artifact)

    with OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(handler)) as client:
        discovered = client.discover_plugin_metadata(["localhost:5000/syntara/plugins/market:1.0.0"])

    assert discovered[0][0] == "localhost:5000/syntara/plugins/market:1.0.0"
    assert discovered[0][1]["plugin"]["metadata"]["displayName"] == "market plugin"


@pytest.mark.parametrize(
    "image_ref",
    ["localhost:5000/syntara/plugins/market", "syntara/plugins/market"],
)
def test_parser_rejects_untagged_oci_references(image_ref: str) -> None:
    with pytest.raises(ValueError, match="explicit tag or sha256 digest"):
        parse_image_reference(image_ref, "http://localhost:5000")


def test_digest_reference_rejects_manifest_bytes_that_do_not_match() -> None:
    requested_digest = "sha256:" + "a" * 64

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/":
            return httpx.Response(200)
        return httpx.Response(200, content=b'{"schemaVersion":2}')

    with OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OCIRegistryError, match="manifest digest does not match"):
            client.get_manifest(f"localhost:5000/syntara/plugins/market@{requested_digest}")


def test_digest_reference_still_allows_matching_manifest_bytes() -> None:
    raw_manifest = b'{"schemaVersion":2}'
    digest = "sha256:" + hashlib.sha256(raw_manifest).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/":
            return httpx.Response(200)
        return httpx.Response(200, content=raw_manifest)

    with OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(handler)) as client:
        assert client.get_manifest(f"localhost:5000/syntara/plugins/market@{digest}") == {
            "schemaVersion": 2
        }


def test_discovery_skips_only_a_missing_metadata_artifact() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/":
            return httpx.Response(200)
        return httpx.Response(404, text="MANIFEST_UNKNOWN")

    with OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(handler)) as client:
        assert client.discover_plugin_metadata(["localhost:5000/syntara/plugins/missing:1.0.0"]) == []


@pytest.mark.parametrize("status", [401, 500])
def test_discovery_propagates_non_not_found_registry_errors(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/":
            return httpx.Response(200)
        return httpx.Response(status, text="registry failure")

    with OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OCIRegistryError, match=f"HTTP {status}"):
            client.discover_plugin_metadata(["localhost:5000/syntara/plugins/market:1.0.0"])


def test_push_sends_metadata_manifest_to_mock_registry(tmp_path: Path) -> None:
    plugin_path = _plugin_source(tmp_path, "push_step")
    pushed: dict[str, object] = {}
    uploads: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, headers={"Location": "/v2/syntara/steps/push_step/blobs/uploads/abc"})
        if request.method == "PUT" and "/blobs/uploads/" in request.url.path:
            uploads.append(request.content)
            return httpx.Response(201)
        if request.method == "PUT" and "/manifests/" in request.url.path:
            pushed["manifest"] = json.loads(request.content)
            return httpx.Response(201, headers={"Docker-Content-Digest": "sha256:" + "c" * 64})
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    with OCIRegistryClient("http://localhost:5000", transport=transport) as client:
        digest = push_plugin(
            plugin_path,
            "localhost:5000/syntara/plugins/push-step:1.0.0",
            registry_client=client,
        )

    assert digest == "sha256:" + "c" * 64
    assert pushed["manifest"]["artifactType"] == OCI_ARTIFACT_TYPE
    assert pushed["manifest"]["config"]["digest"].startswith("sha256:")
    assert pushed["manifest"]["config"]["mediaType"] == OCI_CONFIG_MEDIA_TYPE
    assert pushed["manifest"]["layers"][0]["mediaType"] == OCI_PLUGIN_MANIFEST_MEDIA_TYPE
    payload = yaml.safe_load(uploads[1])
    assert payload["plugin"]["metadata"]["name"] == "push_step_plugin"
    assert len(payload["steps"]) == 1


def test_push_uploads_config_and_plugin_manifest_layer() -> None:
    pushed: dict[str, object] = {}
    uploads: list[bytes] = []
    plugin_manifest = b"metadata:\n  name: published-step\n"
    artifact = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": OCI_ARTIFACT_TYPE,
        "config": {"mediaType": OCI_CONFIG_MEDIA_TYPE, "digest": "", "size": 0},
        "layers": [{"mediaType": OCI_PLUGIN_MANIFEST_MEDIA_TYPE, "digest": "", "size": 0}],
        "annotations": {"org.opencontainers.image.title": "published-step"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/":
            return httpx.Response(200)
        if request.method == "POST":
            return httpx.Response(202, headers={"Location": "/v2/example/plugin/blobs/uploads/abc"})
        if request.method == "PUT" and "/blobs/uploads/" in request.url.path:
            uploads.append(request.content)
            return httpx.Response(201)
        if request.method == "PUT" and "/manifests/" in request.url.path:
            pushed["manifest"] = json.loads(request.content)
            return httpx.Response(201, headers={"Docker-Content-Digest": "sha256:" + "c" * 64})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(handler)) as client:
        assert client.push_manifest(
            "localhost:5000/example/plugin:1",
            artifact,
            layer_contents=[plugin_manifest],
        ) == "sha256:" + "c" * 64

    assert uploads == [b"{}", plugin_manifest]
    pushed_artifact = pushed["manifest"]
    assert pushed_artifact["config"]["mediaType"] == OCI_CONFIG_MEDIA_TYPE
    assert pushed_artifact["layers"][0]["mediaType"] == OCI_PLUGIN_MANIFEST_MEDIA_TYPE


def test_push_rejects_cross_host_upload_redirect() -> None:
    artifact = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": OCI_ARTIFACT_TYPE,
        "config": {"mediaType": OCI_CONFIG_MEDIA_TYPE, "digest": "", "size": 0},
        "layers": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/":
            return httpx.Response(200)
        if request.method == "POST":
            return httpx.Response(
                202,
                headers={"Location": "https://registry-attacker.example/v2/example/plugin/blobs/uploads/abc"},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OCIRegistryError, match="different scheme, host, or port"):
            client.push_manifest("localhost:5000/example/plugin:1", artifact)


def test_plugin_metadata_artifact_publish_inspect_and_registration_flow(tmp_path: Path) -> None:
    """Repository doubles cover publishing, metadata inspection, and registration together."""

    plugin_path = _plugin_source(tmp_path, "full_flow")
    uploaded_blobs: dict[str, bytes] = {}
    pushed_manifest: dict[str, object] = {}
    registration_requests: list[dict[str, object]] = []

    def registry_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/":
            return httpx.Response(200)
        if request.method == "POST":
            return httpx.Response(202, headers={"Location": "/v2/syntara/plugins/full-flow/blobs/uploads/abc"})
        if request.method == "PUT" and "/blobs/uploads/" in request.url.path:
            digest = request.url.params["digest"]
            uploaded_blobs[digest] = request.content
            return httpx.Response(201)
        if request.method == "PUT" and "/manifests/" in request.url.path:
            pushed_manifest.update(json.loads(request.content))
            return httpx.Response(201, headers={"Docker-Content-Digest": "sha256:" + "c" * 64})
        if request.method == "GET" and "/manifests/" in request.url.path:
            return httpx.Response(200, json=pushed_manifest)
        if request.method == "GET" and "/blobs/" in request.url.path:
            digest = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, content=uploaded_blobs[digest])
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    def registration_handler(request: httpx.Request) -> httpx.Response:
        registration_requests.append(json.loads(request.content))
        return httpx.Response(201, json={"data": {"metadata": {"name": "full_flow_plugin"}}})

    image_ref = "localhost:5000/syntara/plugins/full-flow:1.0.0"
    with (
        OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(registry_handler)) as registry,
        httpx.Client(transport=httpx.MockTransport(registration_handler)) as registration,
    ):
        assert push_plugin(
            plugin_path,
            image_ref,
            registry_client=registry,
            register_api_url="http://syntara.local",
            registration_client=registration,
        ) == "sha256:" + "c" * 64
        metadata = registry.inspect_plugin_metadata(image_ref)
        assert validate_plugin_manifest(metadata["plugin"]) == []
        assert all(validate_manifest(step["manifest"]) == [] for step in metadata["steps"])

    assert pushed_manifest["artifactType"] == OCI_ARTIFACT_TYPE
    assert metadata["plugin"]["metadata"]["name"] == "full_flow_plugin"
    assert registration_requests == [
        {"image_ref": "localhost:5000/syntara/plugins/full-flow@sha256:" + "c" * 64}
    ]


def test_retries_throttling_and_honors_retry_after() -> None:
    requests = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        if request.url.path == "/v2/":
            return httpx.Response(200)
        requests += 1
        if requests == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, json={"schemaVersion": 2})

    with OCIRegistryClient(
        "http://localhost:5000",
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    ) as client:
        assert client.get_manifest("localhost:5000/example/plugin:1") == {"schemaVersion": 2}

    assert requests == 2
    assert delays == [3.0]


def test_bearer_authentication_probes_before_token_exchange() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v2/":
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": 'Bearer realm="https://auth.example/token",service="registry.example"'
                },
            )
        if request.url.host == "auth.example":
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"token": "registry-token"})
        assert request.headers["Authorization"] == "Bearer registry-token"
        return httpx.Response(200, json={"schemaVersion": 2})

    with OCIRegistryClient(
        "https://registry.example",
        username="registry-user",
        password="registry-password",
        trusted_auth_hosts=["auth.example"],
        transport=httpx.MockTransport(handler),
    ) as client:
        client.get_manifest("registry.example/example/plugin:1")

    assert paths == ["/v2/", "/token", "/v2/example/plugin/manifests/1"]


@pytest.mark.parametrize("realm", ["https://attacker.example/token", "http://auth.example/token"])
def test_bearer_authentication_rejects_untrusted_or_plaintext_realm(realm: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, headers={"WWW-Authenticate": f'Bearer realm="{realm}"'})

    with OCIRegistryClient(
        "https://registry.example",
        username="registry-user",
        password="registry-password",
        trusted_auth_hosts=["auth.example"],
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(OCIRegistryError, match="token realm"):
            client.get_manifest("registry.example/example/plugin:1")

    assert [request.url.host for request in requests] == ["registry.example"]


def test_push_rejects_invalid_manifest_digest_header() -> None:
    artifact = {
        "schemaVersion": 2,
        "config": {"mediaType": OCI_CONFIG_MEDIA_TYPE, "digest": "", "size": 0},
        "layers": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/":
            return httpx.Response(200)
        if request.method == "POST":
            return httpx.Response(202, headers={"Location": "/v2/example/plugin/blobs/uploads/abc"})
        if request.method == "PUT" and "/blobs/uploads/" in request.url.path:
            return httpx.Response(201)
        return httpx.Response(201, headers={"Docker-Content-Digest": "sha256:not-a-digest"})

    with OCIRegistryClient("http://localhost:5000", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OCIRegistryError, match="valid sha256"):
            client.push_manifest("localhost:5000/example/plugin:1", artifact)


def test_basic_authentication_retries_probe_and_authenticates_requests() -> None:
    requests: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path, request.headers.get("Authorization")))
        if request.headers.get("Authorization") != "Basic cmVnaXN0cnktdXNlcjpyZWdpc3RyeS1wYXNzd29yZA==":
            return httpx.Response(401, headers={"WWW-Authenticate": 'Basic realm="registry"'})
        return httpx.Response(200, json={"schemaVersion": 2})

    with OCIRegistryClient(
        "https://registry.example",
        username="registry-user",
        password="registry-password",
        transport=httpx.MockTransport(handler),
    ) as client:
        assert client.get_manifest("registry.example/example/plugin:1") == {"schemaVersion": 2}

    assert requests == [
        ("/v2/", None),
        ("/v2/", "Basic cmVnaXN0cnktdXNlcjpyZWdpc3RyeS1wYXNzd29yZA=="),
        ("/v2/example/plugin/manifests/1", "Basic cmVnaXN0cnktdXNlcjpyZWdpc3RyeS1wYXNzd29yZA=="),
    ]
