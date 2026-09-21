"""Small OCI Distribution API client for local node registry simulations."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

OCI_ARTIFACT_TYPE = "application/vnd.syntara.node.manifest.v1+yaml"
OCI_MANIFEST_ANNOTATION = "org.syntara.node.manifest"

OCI_MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.index.v1+json",
    )
)


class OCIRegistryError(RuntimeError):
    """Raised when a registry request fails or returns an invalid response."""


@dataclass(frozen=True)
class ParsedImageReference:
    """Registry, repository, and tag/digest components of an image reference."""

    registry: str
    repository: str
    reference: str
    scheme: str

    @property
    def image_ref(self) -> str:
        return f"{self.registry}/{self.repository}@{self.reference}" if self.reference.startswith("sha256:") else f"{self.registry}/{self.repository}:{self.reference}"


def _default_registry_url() -> str:
    return os.getenv("SYNTARA_OCI_REGISTRY_URL", "http://localhost:5000")


def parse_image_reference(image_ref: str, registry_url: str | None = None) -> ParsedImageReference:
    """Parse a local or remote OCI reference without contacting the registry."""

    raw = image_ref.strip()
    if not raw:
        raise ValueError("image_ref must not be empty")

    configured_url = registry_url or _default_registry_url()
    configured = urlsplit(configured_url if "://" in configured_url else f"http://{configured_url}")
    explicit = urlsplit(raw if "://" in raw else "")
    if explicit.scheme and explicit.netloc:
        scheme = explicit.scheme
        remainder = f"{explicit.netloc}{explicit.path}".lstrip("/")
    else:
        scheme = configured.scheme or "http"
        remainder = raw.removeprefix("//")

    parts = remainder.split("/", 1)
    first = parts[0]
    has_registry = len(parts) == 2 and (
        "." in first or ":" in first or first == "localhost" or first == "host.docker.internal"
    )
    if has_registry:
        registry = first
        repository = parts[1]
        if not explicit.scheme:
            scheme = "http" if first.startswith(("localhost", "127.", "0.0.0.0")) else "https"
    else:
        registry = configured.netloc or configured.path
        repository = remainder

    if not repository:
        raise ValueError(f"image_ref has no repository: {image_ref!r}")

    if "@" in repository:
        repository, reference = repository.rsplit("@", 1)
        reference = f"sha256:{reference.removeprefix('sha256:')}"
    else:
        last = repository.rsplit("/", 1)[-1]
        if ":" in last:
            repository, reference = repository.rsplit(":", 1)
        else:
            reference = "latest"
    if not repository or not reference:
        raise ValueError(f"image_ref has an invalid repository or tag: {image_ref!r}")
    return ParsedImageReference(registry, repository, reference, scheme)


class OCIRegistryClient:
    """OCI Distribution API v2 client optimized for metadata-only operations.

    The default endpoint is unencrypted ``http://localhost:5000`` for local
    prototype use. Pass an ``httpx.MockTransport`` through ``transport`` for
    deterministic tests without a running registry.
    """

    def __init__(
        self,
        registry_url: str | None = None,
        *,
        timeout: float = 0.25,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        configured = registry_url or _default_registry_url()
        self.registry_url = (configured if "://" in configured else f"http://{configured}").rstrip("/")
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OCIRegistryClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _base_url(self, parsed: ParsedImageReference) -> str:
        if "://" in self.registry_url:
            configured = urlsplit(self.registry_url)
            if parsed.registry == configured.netloc:
                return self.registry_url
        return f"{parsed.scheme}://{parsed.registry}"

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self._client.request(method, url, **kwargs)
        if response.is_error:
            raise OCIRegistryError(f"OCI {method} {url} failed with HTTP {response.status_code}: {response.text[:200]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OCIRegistryError(f"OCI {method} {url} returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise OCIRegistryError(f"OCI {method} {url} returned a non-object JSON response")
        return payload

    def get_manifest(self, image_ref: str) -> dict[str, Any]:
        """Fetch only the OCI manifest JSON; layers are never requested."""

        parsed = parse_image_reference(image_ref, self.registry_url)
        url = f"{self._base_url(parsed)}/v2/{parsed.repository}/manifests/{parsed.reference}"
        return self._request_json("GET", url, headers={"Accept": OCI_MANIFEST_ACCEPT})

    def inspect_oci_manifest_annotations(self, image_ref: str) -> dict[str, Any]:
        """Return the embedded node manifest from the OCI annotation.

        This performs one manifest request and does not pull config or layer
        blobs. The returned mapping is ready for ``RegistryService`` validation.
        """

        manifest = self.get_manifest(image_ref)
        if manifest.get("artifactType") != OCI_ARTIFACT_TYPE:
            raise OCIRegistryError("OCI artifact is not a Syntara node manifest")
        annotations = manifest.get("annotations")
        if not isinstance(annotations, dict):
            raise OCIRegistryError("OCI node manifest has no annotations")
        raw_manifest = annotations.get(OCI_MANIFEST_ANNOTATION)
        if not isinstance(raw_manifest, str) or not raw_manifest.strip():
            raise OCIRegistryError(f"missing OCI annotation {OCI_MANIFEST_ANNOTATION!r}")

        import yaml

        node_manifest = yaml.safe_load(raw_manifest)
        if not isinstance(node_manifest, dict):
            raise OCIRegistryError("embedded OCI node manifest is not a mapping")
        return node_manifest

    def catalog(self) -> list[str]:
        """List repositories from the local registry catalog."""

        payload = self._request_json("GET", f"{self.registry_url}/v2/_catalog")
        repositories = payload.get("repositories", [])
        if not isinstance(repositories, list) or not all(isinstance(item, str) for item in repositories):
            raise OCIRegistryError("OCI catalog response has an invalid repositories field")
        return repositories

    def tags(self, repository: str) -> list[str]:
        """List tags for one repository."""

        payload = self._request_json("GET", f"{self.registry_url}/v2/{repository}/tags/list")
        tags = payload.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
            raise OCIRegistryError("OCI tags response has an invalid tags field")
        return tags

    def discover_node_manifests(self) -> list[tuple[str, dict[str, Any]]]:
        """Discover all annotated node images in the configured registry."""

        discovered: list[tuple[str, dict[str, Any]]] = []
        configured = urlsplit(self.registry_url if "://" in self.registry_url else f"http://{self.registry_url}")
        registry = configured.netloc or configured.path
        for repository in self.catalog():
            for tag in self.tags(repository):
                image_ref = f"{registry}/{repository}:{tag}"
                try:
                    discovered.append((image_ref, self.inspect_oci_manifest_annotations(image_ref)))
                except OCIRegistryError:
                    continue
        return discovered

    def push_manifest(self, image_ref: str, manifest: dict[str, Any], config: bytes = b"{}") -> str:
        """Push a metadata-only OCI manifest and its empty config blob."""

        parsed = parse_image_reference(image_ref, self.registry_url)
        base_url = self._base_url(parsed)
        config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
        config_descriptor = manifest.get("config")
        if not isinstance(config_descriptor, dict):
            raise ValueError("OCI manifest must contain a config descriptor")
        config_descriptor["digest"] = config_digest
        config_descriptor["size"] = len(config)

        start = self._client.post(f"{base_url}/v2/{parsed.repository}/blobs/uploads/")
        if start.status_code not in {200, 201, 202, 204}:
            raise OCIRegistryError(f"OCI blob upload start failed with HTTP {start.status_code}")
        location = start.headers.get("Location")
        if location:
            upload_url = urljoin(f"{base_url}/", location)
            separator = "&" if "?" in upload_url else "?"
            upload = self._client.put(
                f"{upload_url}{separator}digest={config_digest}",
                content=config,
                headers={"Content-Type": "application/octet-stream"},
            )
            if upload.status_code not in {200, 201, 202, 204}:
                raise OCIRegistryError(f"OCI config upload failed with HTTP {upload.status_code}")

        response = self._client.put(
            f"{base_url}/v2/{parsed.repository}/manifests/{parsed.reference}",
            content=json.dumps(manifest, separators=(",", ":")).encode(),
            headers={"Content-Type": "application/vnd.oci.image.manifest.v1+json"},
        )
        if response.status_code not in {200, 201, 202}:
            raise OCIRegistryError(f"OCI manifest push failed with HTTP {response.status_code}: {response.text[:200]}")
        return response.headers.get("Docker-Content-Digest", "")
