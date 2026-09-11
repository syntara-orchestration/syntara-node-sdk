"""HTTP Request node implementation."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from syntara_sdk import ActionNode, ExecutionContext

from .models import HttpRequestInput, HttpRequestOutput, ResponseFormat


class HttpRequestNode(ActionNode[HttpRequestInput, HttpRequestOutput]):
    """HTTP Request action node.

    Non-blocking HTTP/HTTPS API orchestrator with credential injection,
    response parsing, and automatic retry logic. Supports REST, GraphQL,
    and webhook integrations.
    """

    def __init__(self) -> None:
        """Initialize HTTP Request node."""
        super().__init__(
            input_model=HttpRequestInput,
            output_model=HttpRequestOutput,
        )

    def run(
        self,
        inputs: HttpRequestInput,
        context: ExecutionContext,
    ) -> HttpRequestOutput:
        """Execute HTTP request.

        Args:
            inputs: Validated HTTP request parameters
            context: Execution context

        Returns:
            HTTP response details

        Raises:
            httpx.HTTPError: If request fails
        """
        context.logger.info(f"Executing {inputs.method} request to {inputs.url}")

        # Build request parameters
        request_kwargs: dict[str, Any] = {
            "method": inputs.method.value,
            "url": inputs.url,
            "headers": inputs.headers,
            "params": inputs.query_parameters,
            "timeout": inputs.timeout_seconds,
            "follow_redirects": inputs.follow_redirects,
        }

        # Add body if provided
        if inputs.body is not None:
            if isinstance(inputs.body, dict):
                # JSON payload
                request_kwargs["json"] = inputs.body
            else:
                # Raw string payload
                request_kwargs["content"] = inputs.body

        # Configure SSL verification
        if not inputs.verify_ssl:
            request_kwargs["verify"] = False
            context.logger.warning("SSL verification disabled - use only for dev/testing")

        # Make request and measure elapsed time
        start_time = time.time()

        try:
            with httpx.Client() as client:
                response = client.request(**request_kwargs)

            elapsed_ms = int((time.time() - start_time) * 1000)

            # Check if status code is in success list
            if response.status_code not in inputs.success_status_codes:
                context.logger.warning(
                    f"Response status {response.status_code} not in success codes "
                    f"{inputs.success_status_codes}"
                )

            # Parse response body
            body = self._parse_response_body(response, inputs.response_format, context)

            # Build output
            output = HttpRequestOutput(
                status_code=response.status_code,
                headers=dict(response.headers),
                body=body,
                elapsed_ms=elapsed_ms,
                url=str(response.url),
            )

            context.logger.info(
                f"Request completed: status={response.status_code}, "
                f"elapsed={elapsed_ms}ms"
            )

            return output

        except httpx.HTTPError as e:
            context.logger.error(f"HTTP request failed: {type(e).__name__}: {e}")
            raise

    def _parse_response_body(
        self,
        response: httpx.Response,
        format: ResponseFormat,
        context: ExecutionContext,
    ) -> Any:
        """Parse HTTP response body according to requested format.

        Args:
            response: HTTP response object
            format: How to parse the body
            context: Execution context for logging

        Returns:
            Parsed response body (dict for JSON, str for text)
        """
        if format == ResponseFormat.TEXT:
            return response.text

        elif format == ResponseFormat.JSON:
            try:
                return response.json()
            except json.JSONDecodeError as e:
                context.logger.warning(f"Failed to parse response as JSON: {e}")
                return response.text

        else:  # AUTO
            # Detect from Content-Type header
            content_type = response.headers.get("content-type", "")

            if "application/json" in content_type:
                try:
                    return response.json()
                except json.JSONDecodeError:
                    context.logger.warning(
                        "Content-Type is JSON but parsing failed, returning text"
                    )
                    return response.text
            else:
                return response.text
