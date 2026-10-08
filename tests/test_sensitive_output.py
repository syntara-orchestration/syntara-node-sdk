"""R5/AC-4: SDK base classes must not let a step echo sensitive inputs."""

from pydantic import BaseModel, Field
from syntara_sdk.context import ExecutionContext
from syntara_sdk.step import ActionStep


class LookupInput(BaseModel):
    record_id: str
    customer_email: str = Field(json_schema_extra={"redact": True})


class EnvInput(BaseModel):
    environment_variables: dict[str, str] = Field(json_schema_extra={"redact": True})


class LookupOutput(BaseModel):
    summary: str


class EchoStep(ActionStep[LookupInput, LookupOutput]):
    def __init__(self) -> None:
        super().__init__(LookupInput, LookupOutput)

    def run(self, inputs: LookupInput, context: ExecutionContext) -> LookupOutput:
        return LookupOutput(summary=f"looked up {inputs.customer_email}")


class SafeStep(ActionStep[LookupInput, LookupOutput]):
    def __init__(self) -> None:
        super().__init__(LookupInput, LookupOutput)

    def run(self, inputs: LookupInput, context: ExecutionContext) -> LookupOutput:
        return LookupOutput(summary=f"looked up record {inputs.record_id}")


class NestedEchoStep(ActionStep[EnvInput, LookupOutput]):
    def __init__(self) -> None:
        super().__init__(EnvInput, LookupOutput)

    def run(self, inputs: EnvInput, context: ExecutionContext) -> LookupOutput:
        return LookupOutput(summary=" ".join(inputs.environment_variables.values()))


class RaisingStep(ActionStep[LookupInput, LookupOutput]):
    def __init__(self) -> None:
        super().__init__(LookupInput, LookupOutput)

    def run(self, inputs: LookupInput, context: ExecutionContext) -> LookupOutput:
        raise ValueError(f"upstream rejected {inputs.customer_email}")


INPUTS = {"record_id": "rec-1", "customer_email": "person@example.com"}


def test_echoed_redact_input_fails_closed() -> None:
    result = EchoStep().execute_raw(dict(INPUTS))

    assert result.StatusCode == 1
    assert result.Result is None
    assert result.StatusMessage == "Sensitive input echoed in output"
    # The failure names the field but never quotes the value.
    assert "customer_email" in result.ErrorMessage
    assert "person@example.com" not in result.ErrorMessage


def test_non_echoing_step_succeeds() -> None:
    result = SafeStep().execute_raw(dict(INPUTS))

    assert result.StatusCode == 0
    assert result.Result == {"summary": "looked up record rec-1"}


def test_nested_redact_values_are_detected() -> None:
    result = NestedEchoStep().execute_raw(
        {"environment_variables": {"TOKEN": "nested-redacted-value"}}
    )

    assert result.StatusCode == 1
    assert "environment_variables" in result.ErrorMessage
    assert "nested-redacted-value" not in result.ErrorMessage


def test_step_exception_still_reports_failure() -> None:
    """Scrubbing tracebacks is the platform's job, not the SDK's (R5)."""
    result = RaisingStep().execute_raw(dict(INPUTS))

    assert result.StatusCode == 1
    assert "ValueError" in result.StatusMessage


def test_model_without_redact_fields_is_unaffected() -> None:
    class PlainInput(BaseModel):
        value: str

    class PlainStep(ActionStep[PlainInput, LookupOutput]):
        def __init__(self) -> None:
            super().__init__(PlainInput, LookupOutput)

        def run(self, inputs: PlainInput, context: ExecutionContext) -> LookupOutput:
            return LookupOutput(summary=inputs.value)

    result = PlainStep().execute_raw({"value": "echoed-freely"})

    assert result.StatusCode == 0
    assert result.Result == {"summary": "echoed-freely"}
