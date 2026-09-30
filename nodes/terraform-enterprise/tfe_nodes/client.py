"""Small synchronous JSON:API client; mutations are never retried implicitly."""

import re
from typing import Any
from urllib.parse import urlsplit

import httpx


class TFEError(RuntimeError):
    """Safe diagnostics: never carry remote response bodies or signed URLs."""


def resource_id(document: dict[str, Any]) -> str:
    data = document.get("data")
    value = data.get("id") if isinstance(data, dict) else None
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise TFEError("TFE returned an invalid resource identifier")
    return value


def scrub(value: Any, token: str) -> Any:
    """Remove sensitive values and bearer URLs before returning to the engine."""
    if isinstance(value, list):
        return [scrub(item, token) for item in value]
    if isinstance(value, dict):
        sensitive = value.get("sensitive") is True
        variable = value.get("type") == "vars"
        result = {}
        for key, item in value.items():
            if key in {
                "upload-url",
                "hosted-state-download-url",
                "hosted-json-state-download-url",
                "log-read-url",
                "download",
            }:
                continue
            if sensitive and key == "value":
                result[key] = "[REDACTED]"
            elif key == "variables" and isinstance(item, list):
                result[key] = [
                    scrub({**entry, "value": "[REDACTED]"}, token)
                    if isinstance(entry, dict)
                    else "[REDACTED]"
                    for entry in item
                ]
            elif variable and key == "attributes" and isinstance(item, dict):
                result[key] = scrub({**item, "value": "[REDACTED]"}, token)
            else:
                result[key] = scrub(item, token)
        return result
    if isinstance(value, str) and token:
        return value.replace(token, "[REDACTED]")
    return value


class TFEClient:
    def __init__(self, base_url: str, token: str, timeout: int, transport=None):
        self.base_url = base_url + "/api/v2"
        self.token = token
        self.http = httpx.Client(timeout=timeout, follow_redirects=False, transport=transport)

    def close(self) -> None:
        self.http.close()

    def request(self, method: str, path: str, *, body=None, params=None):
        kwargs = {"params": params}
        if body is not None:
            kwargs["json"] = body
        try:
            response = self.http.request(
                method,
                self.base_url + path,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/vnd.api+json",
                    "Content-Type": "application/vnd.api+json",
                },
                **kwargs,
            )
        except httpx.HTTPError:
            suffix = "; remote outcome unknown; verify before retrying" if method != "GET" else ""
            raise TFEError("TFE transport failure" + suffix) from None
        self.check_status(response)
        if not response.content:
            if method == "GET":
                raise TFEError("TFE returned an empty JSON:API response")
            return {}, response.status_code
        try:
            document = response.json()
        except ValueError:
            raise TFEError("TFE returned invalid JSON; verify mutations before retrying") from None
        if not isinstance(document, dict) or "data" not in document:
            raise TFEError("TFE returned an invalid JSON:API document")
        return document, response.status_code

    @staticmethod
    def check_status(response: httpx.Response) -> None:
        if 200 <= response.status_code < 300:
            return
        code = response.status_code
        category = (
            "authentication failed"
            if code == 401
            else "permission denied"
            if code == 403
            else "not found or inaccessible"
            if code == 404
            else "rate limited"
            if code == 429
            else "server failure; verify mutations before retrying"
            if code >= 500
            else "request rejected"
        )
        raise TFEError(f"TFE HTTP {code}: {category}")

    def upload(self, url: str, archive: bytes) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise TFEError("TFE returned an invalid HTTPS upload URL")
        try:
            # Signed upload URLs may use a separate storage host. Never attach
            # the TFE Authorization header, and never follow redirects.
            response = self.http.put(
                url, content=archive, headers={"Content-Type": "application/octet-stream"}
            )
        except httpx.HTTPError:
            raise TFEError(
                "Configuration upload transport failure; remote outcome unknown"
            ) from None
        self.check_status(response)
