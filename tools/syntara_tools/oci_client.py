"""Small, resilient OCI Distribution API client for plugin metadata."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from syntara_tools.compiler import validate_plugin_metadata_payload

OCI_ARTIFACT_TYPE = "application/vnd.syntara.plugin.v1+yaml"
OCI_PLUGIN_MANIFEST_MEDIA_TYPE = "application/vnd.syntara.plugin.manifest.v1+yaml"
OCI_CONFIG_MEDIA_TYPE = "application/vnd.unknown.config.v1+json"

OCI_MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.index.v1+json",
    )
)
_BEARER_CHALLENGE = re.compile(r"^Bearer\s+(.+)$", re.IGNORECASE)
_BASIC_CHALLENGE = re.compile(r"^Basic(?:\s|$)", re.IGNORECASE)
_CHALLENGE_PARAMETER = re.compile(r'([A-Za-z][A-Za-z0-9_-]*)="([^"]*)"')
_SHA256_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


class OCIRegistryError(RuntimeError):
    """Raised when a registry request fails or returns an invalid response."""


class _OCIArtifactNotFound(OCIRegistryError):
    """Raised only when the requested manifest does not exist in the registry."""


@dataclass(frozen=True)
class ParsedImageReference:
    """Registry, repository, and tag/digest components of an image reference."""

    registry: str
    repository: str
    reference: str
    scheme: str

    @property
    def image_ref(self) -> str:
        if self.reference.startswith("sha256:"):
            return f"{self.registry}/{self.repository}@{self.reference}"
        return f"{self.registry}/{self.repository}:{self.reference}"


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
        registry, repository = first, parts[1]
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
            raise ValueError(
                "image_ref must include an explicit tag or sha256 digest; "
                "implicit :latest is not allowed"
            )
    if not repository or not reference:
        raise ValueError(f"image_ref has an invalid repository or tag: {image_ref!r}")
    return ParsedImageReference(registry, repository, reference, scheme)


class OCIRegistryClient:
    """OCI Distribution API v2 client for known plugin artifact references."""

    def __init__(
        self,
        registry_url: str | None = None,
        *,
        timeout: float = 10.0,
        max_retries: int = 2,
        retry_backoff: float = 0.25,
        username: str | None = None,
        password: str | None = None,
        trusted_auth_hosts: Iterable[str] | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if retry_backoff < 0:
            raise ValueError("retry_backoff must not be negative")
        configured = registry_url or _default_registry_url()
        self.registry_url = (configured if "://" in configured else f"http://{configured}").rstrip("/")
        self._client = httpx.Client(timeout=timeout, transport=transport)
        self._registry_auth = (
            httpx.BasicAuth(
                username if username is not None else os.getenv("SYNTARA_OCI_USERNAME", ""),
                password if password is not None else os.getenv("SYNTARA_OCI_PASSWORD", ""),
            )
            if username is not None
            or password is not None
            or os.getenv("SYNTARA_OCI_USERNAME") is not None
            or os.getenv("SYNTARA_OCI_PASSWORD") is not None
            else None
        )
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._sleep = sleep
        self._probed_registries: set[str] = set()
        self._basic_registries: set[str] = set()
        self._bearer_tokens: dict[tuple[str, str], str] = {}
        configured_auth_hosts = os.getenv("SYNTARA_OCI_TRUSTED_AUTH_HOSTS", "")
        requested_auth_hosts = trusted_auth_hosts or configured_auth_hosts.split(",")
        self._trusted_auth_origins = {
            self._auth_origin(host) for host in requested_auth_hosts if host.strip()
        }

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OCIRegistryClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _base_url(self, parsed: ParsedImageReference) -> str:
        configured = urlsplit(self.registry_url)
        if parsed.registry == configured.netloc:
            return self.registry_url
        return f"{parsed.scheme}://{parsed.registry}"

    @staticmethod
    def _retry_after(response: httpx.Response, fallback: float) -> float:
        value = response.headers.get("Retry-After")
        if not value:
            return fallback
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
            except (TypeError, ValueError, IndexError, OverflowError):
                return fallback

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send a request with bounded retries for transient failures."""
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.RequestError as exc:
                if attempt == self._max_retries:
                    raise OCIRegistryError(f"OCI {method} {url} failed: {exc}") from exc
                self._sleep(self._retry_backoff * (2**attempt))
                continue
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == self._max_retries:
                return response
            self._sleep(self._retry_after(response, self._retry_backoff * (2**attempt)))
        raise AssertionError("unreachable")

    @staticmethod
    def _bearer_parameters(response: httpx.Response) -> dict[str, str] | None:
        match = _BEARER_CHALLENGE.match(response.headers.get("WWW-Authenticate", ""))
        if not match:
            return None
        parameters = dict(_CHALLENGE_PARAMETER.findall(match.group(1)))
        return parameters if parameters.get("realm") else None

    def _token_for_challenge(self, base_url: str, parameters: Mapping[str, str]) -> str:
        scope = parameters.get("scope", "")
        cache_key = (base_url, scope)
        if cache_key in self._bearer_tokens:
            return self._bearer_tokens[cache_key]
        realm = self._trusted_token_realm(base_url, parameters["realm"])
        params = {key: value for key, value in parameters.items() if key in {"service", "scope"}}
        token_kwargs: dict[str, Any] = {"params": params}
        if self._registry_auth is not None:
            token_kwargs["auth"] = self._registry_auth
        response = self._send("GET", realm, **token_kwargs)
        if response.is_error:
            raise OCIRegistryError(f"OCI token exchange failed with HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OCIRegistryError("OCI token exchange returned invalid JSON") from exc
        token = (payload.get("token") or payload.get("access_token")) if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise OCIRegistryError("OCI token exchange returned no bearer token")
        self._bearer_tokens[cache_key] = token
        return token

    def _trusted_token_realm(self, base_url: str, realm: str) -> str:
        """Return a token realm only when it is an explicitly safe endpoint.

        A registry may delegate authentication to a different HTTPS host, but
        registry Basic credentials must never follow an arbitrary challenge.
        Same-origin realms are allowed (including local HTTP development
        registries); delegated realms require HTTPS and an explicit host
        allowlist supplied by the caller or environment.
        """
        parsed_realm = urlsplit(realm)
        if not parsed_realm.scheme or not parsed_realm.netloc or parsed_realm.username or parsed_realm.password:
            raise OCIRegistryError("OCI token realm must be an absolute URL without userinfo")
        parsed_registry = urlsplit(base_url)
        try:
            same_origin = (
                parsed_realm.scheme == parsed_registry.scheme
                and parsed_realm.hostname == parsed_registry.hostname
                and parsed_realm.port == parsed_registry.port
            )
        except ValueError as exc:
            raise OCIRegistryError("OCI token realm has an invalid port") from exc
        if same_origin:
            return realm
        if parsed_realm.scheme != "https" or self._origin(parsed_realm) not in self._trusted_auth_origins:
            raise OCIRegistryError(
                "OCI token realm must be same-origin or an HTTPS origin in trusted_auth_hosts"
            )
        return realm

    @staticmethod
    def _origin(parsed: object) -> tuple[str, str, int]:
        assert hasattr(parsed, "scheme") and hasattr(parsed, "hostname") and hasattr(parsed, "port")
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        if not hostname:
            raise OCIRegistryError("OCI token realm must include a hostname")
        return scheme, hostname.lower(), parsed.port or (443 if scheme == "https" else 80)

    @classmethod
    def _auth_origin(cls, configured_host: str) -> tuple[str, str, int]:
        raw = configured_host.strip()
        parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
        try:
            origin = cls._origin(parsed)
        except ValueError as exc:
            raise ValueError(f"invalid trusted auth host {configured_host!r}") from exc
        if origin[0] != "https" or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("trusted_auth_hosts entries must be HTTPS origins without paths")
        return origin

    def _probe_registry(self, base_url: str) -> str | None:
        if base_url in self._probed_registries:
            return self._bearer_tokens.get((base_url, ""))
        response = self._send("GET", f"{base_url}/v2/")
        self._probed_registries.add(base_url)
        parameters = self._bearer_parameters(response)
        if parameters:
            token = self._token_for_challenge(base_url, parameters)
            self._bearer_tokens[(base_url, "")] = token
            return token
        if (
            response.status_code == 401
            and self._registry_auth is not None
            and _BASIC_CHALLENGE.match(response.headers.get("WWW-Authenticate", ""))
        ):
            response = self._send("GET", f"{base_url}/v2/", auth=self._registry_auth)
            if not response.is_error:
                self._basic_registries.add(base_url)
        if response.is_error:
            raise OCIRegistryError(f"OCI registry probe {base_url}/v2/ failed with HTTP {response.status_code}")
        return None

    def _request(self, method: str, base_url: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        token = self._probe_registry(base_url)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if base_url in self._basic_registries:
            kwargs["auth"] = self._registry_auth
        response = self._send(method, f"{base_url}{path}", headers=headers, **kwargs)
        parameters = self._bearer_parameters(response) if response.status_code == 401 else None
        if parameters:
            headers["Authorization"] = f"Bearer {self._token_for_challenge(base_url, parameters)}"
            response = self._send(method, f"{base_url}{path}", headers=headers, **kwargs)
        return response

    def get_manifest(self, image_ref: str) -> dict[str, Any]:
        """Fetch OCI manifest JSON for a known artifact reference."""
        parsed = parse_image_reference(image_ref, self.registry_url)
        response = self._request(
            "GET", self._base_url(parsed), f"/v2/{parsed.repository}/manifests/{parsed.reference}",
            headers={"Accept": OCI_MANIFEST_ACCEPT},
        )
        if response.status_code == 404:
            raise _OCIArtifactNotFound(f"OCI manifest {image_ref} was not found")
        if response.is_error:
            raise OCIRegistryError(
                f"OCI GET {response.request.url} failed with HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )
        if parsed.reference.startswith("sha256:"):
            actual_digest = "sha256:" + hashlib.sha256(response.content).hexdigest()
            if actual_digest != parsed.reference:
                raise OCIRegistryError("OCI manifest digest does not match digest reference")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OCIRegistryError(f"OCI GET {response.request.url} returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise OCIRegistryError(f"OCI GET {response.request.url} returned a non-object JSON response")
        return payload

    def inspect_plugin_metadata(self, image_ref: str) -> dict[str, Any]:
        """Fetch and validate the plugin metadata layer for a known artifact."""
        parsed = parse_image_reference(image_ref, self.registry_url)
        base_url = self._base_url(parsed)
        manifest = self.get_manifest(image_ref)
        if manifest.get("artifactType") != OCI_ARTIFACT_TYPE:
            raise OCIRegistryError("OCI artifact is not a Syntara plugin metadata artifact")
        layers = manifest.get("layers")
        if not isinstance(layers, list):
            raise OCIRegistryError("OCI plugin metadata artifact has no layers")
        layer = next((item for item in layers if isinstance(item, dict) and item.get("mediaType") == OCI_PLUGIN_MANIFEST_MEDIA_TYPE), None)
        if layer is None or not isinstance(layer.get("digest"), str):
            raise OCIRegistryError("OCI plugin metadata artifact has no plugin manifest layer")
        response = self._request("GET", base_url, f"/v2/{parsed.repository}/blobs/{layer['digest']}")
        if response.is_error:
            raise OCIRegistryError(f"OCI plugin manifest layer fetch failed with HTTP {response.status_code}: {response.text[:200]}")
        if isinstance(layer.get("size"), int) and len(response.content) != layer["size"]:
            raise OCIRegistryError("OCI plugin manifest layer size does not match descriptor")
        expected_digest = layer["digest"]
        if not expected_digest.startswith("sha256:"):
            raise OCIRegistryError("OCI plugin manifest layer must use a sha256 digest")
        actual_digest = "sha256:" + hashlib.sha256(response.content).hexdigest()
        if actual_digest != expected_digest:
            raise OCIRegistryError("OCI plugin manifest layer digest does not match descriptor")
        import yaml

        try:
            plugin_metadata = yaml.safe_load(response.content)
        except yaml.YAMLError as exc:
            raise OCIRegistryError("OCI plugin manifest layer contains invalid YAML") from exc
        if not isinstance(plugin_metadata, dict):
            raise OCIRegistryError("OCI plugin manifest layer is not a mapping")
        errors = validate_plugin_metadata_payload(plugin_metadata)
        if errors:
            raise OCIRegistryError("OCI plugin metadata validation failed: " + "; ".join(errors))
        return plugin_metadata

    def discover_plugin_metadata(self, image_refs: Iterable[str]) -> list[tuple[str, dict[str, Any]]]:
        """Inspect only supplied references; registry catalog access is never used."""
        discovered: list[tuple[str, dict[str, Any]]] = []
        for image_ref in image_refs:
            try:
                discovered.append((image_ref, self.inspect_plugin_metadata(image_ref)))
            except _OCIArtifactNotFound:
                continue
        return discovered

    def push_manifest(
        self,
        image_ref: str,
        manifest: dict[str, Any],
        config: bytes = b"{}",
        layer_contents: Sequence[bytes] = (),
    ) -> str:
        """Push config and descriptor-matched layers before the OCI manifest."""
        parsed = parse_image_reference(image_ref, self.registry_url)
        base_url = self._base_url(parsed)
        config_descriptor = manifest.get("config")
        layers = manifest.get("layers", [])
        if not isinstance(config_descriptor, dict) or not isinstance(layers, list):
            raise ValueError("OCI manifest must contain config and layers descriptors")
        if len(layers) != len(layer_contents) or not all(isinstance(item, dict) for item in layers):
            raise ValueError("layer_contents must correspond to OCI manifest layers")
        config_descriptor["digest"] = "sha256:" + hashlib.sha256(config).hexdigest()
        config_descriptor["size"] = len(config)
        blobs: list[tuple[dict[str, Any], bytes]] = [(config_descriptor, config)]
        blobs.extend(zip(layers, layer_contents, strict=True))
        for descriptor, content in blobs:
            digest = "sha256:" + hashlib.sha256(content).hexdigest()
            descriptor["digest"], descriptor["size"] = digest, len(content)
            start = self._request("POST", base_url, f"/v2/{parsed.repository}/blobs/uploads/")
            if start.status_code not in {200, 201, 202, 204}:
                raise OCIRegistryError(f"OCI blob upload start failed with HTTP {start.status_code}")
            location = start.headers.get("Location")
            if not location:
                raise OCIRegistryError("OCI blob upload start response omitted Location")
            upload_url = urljoin(f"{base_url}/", location)
            upload_target = urlsplit(upload_url)
            registry_target = urlsplit(base_url)
            try:
                same_registry = (
                    upload_target.scheme == registry_target.scheme
                    and upload_target.hostname == registry_target.hostname
                    and upload_target.port == registry_target.port
                )
            except ValueError as exc:
                raise OCIRegistryError("OCI registry returned an invalid upload Location") from exc
            if not same_registry:
                raise OCIRegistryError(
                    "OCI registry returned an upload location with a different scheme, host, or port"
                )
            upload_path = upload_target.path
            if upload_target.query:
                upload_path += f"?{upload_target.query}"
            separator = "&" if "?" in upload_url else "?"
            upload = self._request(
                "PUT", base_url, upload_path + f"{separator}digest={digest}",
                content=content, headers={"Content-Type": "application/octet-stream"},
            )
            if upload.status_code not in {200, 201, 202, 204}:
                raise OCIRegistryError(f"OCI blob upload failed with HTTP {upload.status_code}")

        response = self._request(
            "PUT", base_url, f"/v2/{parsed.repository}/manifests/{parsed.reference}",
            content=json.dumps(manifest, separators=(",", ":")).encode(),
            headers={"Content-Type": "application/vnd.oci.image.manifest.v1+json"},
        )
        if response.status_code not in {200, 201, 202}:
            raise OCIRegistryError(f"OCI manifest push failed with HTTP {response.status_code}: {response.text[:200]}")
        digest_header: str | None = response.headers.get("Docker-Content-Digest")
        if not digest_header or not _SHA256_DIGEST.fullmatch(digest_header):
            raise OCIRegistryError("OCI manifest push response omitted a valid sha256 Docker-Content-Digest")
        return digest_header
