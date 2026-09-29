"""Unit tests for HTTP Request step."""

from __future__ import annotations

import httpx
import pytest
import respx
from respx import MockRouter
from syntara_sdk import ExecutionContext
from tests.fixtures.steps.http_request.src.main import HttpRequestStep
from tests.fixtures.steps.http_request.src.models import (
    HttpMethod,
    HttpRequestInput,
    ResponseFormat,
)


class TestHttpRequestStep:
    """Test suite for HttpRequestStep."""

    def test_step_initialization(self) -> None:
        """Test step can be instantiated."""
        step = HttpRequestStep()
        assert step.input_model == HttpRequestInput
        assert step.output_model.__name__ == "HttpRequestOutput"

    @respx.mock
    def test_successful_get_request_with_mock(self) -> None:
        """Test successful GET request with mocked response."""
        # Mock HTTP response
        respx.get("https://api.example.com/data").mock(
            return_value=httpx.Response(200, json={"message": "success"})
        )

        # Create step and execute
        step = HttpRequestStep()
        context = ExecutionContext(step_name="test_http_request")

        inputs = HttpRequestInput(
            url="https://api.example.com/data",
            method=HttpMethod.GET,
        )

        output = step.run(inputs, context)

        # Verify output
        assert output.status_code == 200
        assert output.body == {"message": "success"}
        assert output.elapsed_ms >= 0
        assert output.url == "https://api.example.com/data"
        assert isinstance(output.headers, dict)

    @respx.mock
    def test_post_request_with_json_body(self) -> None:
        """Test POST request with JSON body."""
        respx.post("https://api.example.com/create").mock(
            return_value=httpx.Response(201, json={"id": "123", "created": True})
        )

        step = HttpRequestStep()
        context = ExecutionContext()

        inputs = HttpRequestInput(
            url="https://api.example.com/create",
            method=HttpMethod.POST,
            body={"name": "Test Item", "value": 42},
            headers={"Content-Type": "application/json"},
        )

        output = step.run(inputs, context)

        assert output.status_code == 201
        assert output.body == {"id": "123", "created": True}

    @respx.mock
    def test_execute_raw_with_valid_inputs(self) -> None:
        """Test execute_raw wraps result in StandardOutputWrapper."""
        respx.get("https://httpbin.org/get").mock(
            return_value=httpx.Response(200, json={"url": "https://httpbin.org/get"})
        )

        step = HttpRequestStep()

        raw_inputs = {
            "url": "https://httpbin.org/get",
            "method": "GET",
        }

        wrapper = step.execute_raw(raw_inputs)

        # Verify StandardOutputWrapper structure
        assert wrapper.StatusCode == 0
        assert wrapper.StatusMessage == "Execution completed successfully"
        assert wrapper.ErrorMessage == ""
        assert wrapper.Result is not None
        assert wrapper.Result["status_code"] == 200

    def test_execute_raw_with_invalid_inputs(self) -> None:
        """Test execute_raw handles validation errors."""
        step = HttpRequestStep()

        # Missing required 'url' field
        raw_inputs = {
            "method": "GET",
        }

        wrapper = step.execute_raw(raw_inputs)

        # Verify error is wrapped
        assert wrapper.StatusCode == 1
        assert wrapper.StatusMessage == "Input validation failed"
        assert "url" in wrapper.ErrorMessage
        assert wrapper.Result is None

    def test_input_validation_requires_url(self) -> None:
        """Test that url is required."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            HttpRequestInput(method=HttpMethod.GET)

    def test_input_validation_url_must_have_protocol(self) -> None:
        """Test URL must start with http:// or https://."""
        with pytest.raises(ValueError, match="must start with http"):
            HttpRequestInput(
                url="api.example.com/data",
                method=HttpMethod.GET,
            )

    def test_default_values_applied(self) -> None:
        """Test default values are applied correctly."""
        inputs = HttpRequestInput(
            url="https://api.example.com/test",
            method=HttpMethod.GET,
        )

        assert inputs.method == HttpMethod.GET
        assert inputs.timeout_seconds == 30
        assert inputs.response_format == ResponseFormat.AUTO
        assert inputs.follow_redirects is True
        assert inputs.verify_ssl is True
        assert inputs.success_status_codes == [200, 201, 204]
        assert inputs.headers == {}
        assert inputs.query_parameters == {}
        assert inputs.context_vars == {}

    @respx.mock
    def test_query_parameters_handling(self) -> None:
        """Test query parameters are properly passed."""
        respx.get("https://api.example.com/search").mock(
            return_value=httpx.Response(200, json={"results": []})
        )

        step = HttpRequestStep()
        context = ExecutionContext()

        inputs = HttpRequestInput(
            url="https://api.example.com/search",
            method=HttpMethod.GET,
            query_parameters={"q": "test", "limit": "10"},
        )

        output = step.run(inputs, context)
        assert output.status_code == 200

    @respx.mock
    def test_custom_headers(self) -> None:
        """Test custom headers are sent."""
        respx.get("https://api.example.com/data").mock(
            return_value=httpx.Response(200, json={})
        )

        step = HttpRequestStep()
        context = ExecutionContext()

        inputs = HttpRequestInput(
            url="https://api.example.com/data",
            method=HttpMethod.GET,
            headers={
                "Authorization": "Bearer token123",
                "X-Custom-Header": "value",
            },
        )

        output = step.run(inputs, context)
        assert output.status_code == 200

    @respx.mock
    def test_text_response_format(self) -> None:
        """Test text response format returns raw text."""
        respx.get("https://api.example.com/text").mock(
            return_value=httpx.Response(200, text="Plain text response")
        )

        step = HttpRequestStep()
        context = ExecutionContext()

        inputs = HttpRequestInput(
            url="https://api.example.com/text",
            method=HttpMethod.GET,
            response_format=ResponseFormat.TEXT,
        )

        output = step.run(inputs, context)
        assert output.body == "Plain text response"

    @respx.mock
    def test_timeout_parameter(self) -> None:
        """Test custom timeout is used."""
        respx.get("https://api.example.com/slow").mock(
            return_value=httpx.Response(200, json={})
        )

        step = HttpRequestStep()
        context = ExecutionContext()

        inputs = HttpRequestInput(
            url="https://api.example.com/slow",
            method=HttpMethod.GET,
            timeout_seconds=60,
        )

        output = step.run(inputs, context)
        assert output.status_code == 200
