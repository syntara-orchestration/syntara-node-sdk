"""Pydantic models for HTTP Request node inputs and outputs."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class HttpMethod(StrEnum):
    """HTTP method verbs."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class ResponseFormat(StrEnum):
    """How to parse HTTP response body."""

    JSON = "json"  # Parse as JSON object
    TEXT = "text"  # Return raw string
    AUTO = "auto"  # Detect from Content-Type header


class HttpRequestInput(BaseModel):
    """Input parameters for HTTP request node.

    Matches the manifest.yaml input schema exactly.
    """

    # Required fields
    url: str = Field(
        ...,
        description="Target HTTP/HTTPS URL (protocol required)",
        min_length=10,
        max_length=2048,
    )
    method: HttpMethod = Field(
        default=HttpMethod.GET,
        description="HTTP method verb",
    )

    # Optional fields with defaults
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="HTTP request headers (key-value pairs)",
    )
    query_parameters: dict[str, str] = Field(
        default_factory=dict,
        description="URL query parameters (automatically URL-encoded)",
    )
    body: str | dict[str, Any] | None = Field(
        default=None,
        description="Request payload - object for JSON, string for raw",
    )
    timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=600,
        description="Request timeout (connection + read time)",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.AUTO,
        description="How to parse response body",
    )
    follow_redirects: bool = Field(
        default=True,
        description="Automatically follow HTTP 3xx redirects (up to 10 hops)",
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify SSL/TLS certificates (disable only for dev/testing)",
    )
    success_status_codes: list[int] = Field(
        default=[200, 201, 204],
        description="HTTP status codes treated as success",
    )
    context_vars: dict[str, str | int | bool] = Field(
        default_factory=dict,
        description="Arbitrary caller-supplied variables merged into templated fields",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL has protocol."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v

    @field_validator("success_status_codes")
    @classmethod
    def validate_status_codes(cls, v: list[int]) -> list[int]:
        """Validate status codes are in valid range."""
        for code in v:
            if code < 100 or code > 599:
                raise ValueError(f"Invalid HTTP status code: {code}")
        return list(set(v))  # Ensure uniqueness


class HttpRequestOutput(BaseModel):
    """Output from HTTP request node.

    This is the Result payload that gets wrapped in StandardOutputWrapper.
    """

    status_code: int = Field(
        ...,
        ge=100,
        le=599,
        description="HTTP response status code (e.g. 200, 404, 500)",
    )
    headers: dict[str, str] = Field(
        ...,
        description="Response headers as string key-value pairs",
    )
    body: Any = Field(
        ...,
        description="Parsed JSON body, or raw text when the response is not JSON",
    )
    elapsed_ms: int = Field(
        ...,
        ge=0,
        description="Wall-clock request duration in milliseconds",
    )
    url: str = Field(
        ...,
        description="Final URL after any followed redirects",
    )
