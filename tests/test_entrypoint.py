"""Tests for the plugin-level runtime contract and dispatcher."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel
from syntara_sdk import (
    ActionStep,
    ExecutionContext,
    InvocationContext,
    PluginRuntime,
    QualifiedStepIdentity,
    RuntimeRegistrationError,
    StepInvocation,
)


class Input(BaseModel):
    message: str


class Output(BaseModel):
    message: str
    execution_id: str
    workflow_id: str | None
    step_name: str


class EchoStep(ActionStep[Input, Output]):
    def __init__(self) -> None:
        super().__init__(Input, Output)

    def run(self, inputs: Input, context: ExecutionContext) -> Output:
        return Output(
            message=f"echo:{inputs.message}",
            execution_id=context.execution_id,
            workflow_id=context.workflow_id,
            step_name=context.step_name,
        )


class ReverseStep(ActionStep[Input, Output]):
    def __init__(self) -> None:
        super().__init__(Input, Output)

    def run(self, inputs: Input, context: ExecutionContext) -> Output:
        return Output(
            message=inputs.message[::-1],
            execution_id=context.execution_id,
            workflow_id=context.workflow_id,
            step_name=context.step_name,
        )


def _runtime() -> PluginRuntime:
    runtime = PluginRuntime("example/utility")
    runtime.register("example/utility/echo", EchoStep)
    runtime.register("example/utility/reverse", ReverseStep)
    return runtime


def test_qualified_step_identity_rejects_malformed_values() -> None:
    assert str(QualifiedStepIdentity.parse("example/utility/echo")) == "example/utility/echo"
    for identity in ("echo", "example/utility/echo/extra", "example//echo", "../utility/echo"):
        with pytest.raises(ValueError, match="qualified"):
            QualifiedStepIdentity.parse(identity)


def test_runtime_dispatches_each_qualified_identity_to_its_registered_implementation() -> None:
    runtime = _runtime()

    echo = runtime.dispatch(
        {
            "step_identity": "example/utility/echo",
            "inputs": {"message": "hello"},
            "context": {"execution_id": "exec-1", "workflow_id": "workflow-1"},
        }
    )
    reverse = runtime.dispatch(
        {
            "step_identity": "example/utility/reverse",
            "inputs": {"message": "hello"},
            "context": {"execution_id": "exec-2"},
        }
    )

    assert echo.accepted and echo.output is not None
    assert echo.output.Result == {
        "message": "echo:hello",
        "execution_id": "exec-1",
        "workflow_id": "workflow-1",
        "step_name": "example/utility/echo",
    }
    assert reverse.accepted and reverse.output is not None
    assert reverse.output.Result["message"] == "olleh"
    assert reverse.output.Result["step_name"] == "example/utility/reverse"


@pytest.mark.parametrize(
    "invocation, error",
    [
        ({"step_identity": "example/utility/missing", "inputs": {}}, "not registered"),
        ({"step_identity": "other/utility/echo", "inputs": {}}, "not owned"),
        ({"step_identity": "not-qualified", "inputs": {}}, "invalid step invocation"),
        ({"step_identity": "example/utility/echo", "inputs": [], "context": {}}, "invalid step invocation"),
    ],
)
def test_runtime_rejects_unknown_cross_plugin_and_malformed_requests_safely(
    invocation: dict[str, Any], error: str
) -> None:
    result = _runtime().dispatch(invocation)

    assert not result.accepted
    assert result.output is None
    assert result.error is not None and error in result.error


def test_runtime_revalidates_constructed_invocation_models() -> None:
    invocation = StepInvocation.model_construct(
        step_identity="not-qualified",
        inputs={},
        context=InvocationContext(),
    )

    result = _runtime().dispatch(invocation)

    assert not result.accepted
    assert result.error == "invalid step invocation request"


def test_input_validation_is_preserved_after_dispatch() -> None:
    result = _runtime().dispatch(
        {"step_identity": "example/utility/echo", "inputs": {}, "context": {}}
    )

    assert result.accepted
    assert result.output is not None
    assert result.output.StatusCode == 1
    assert result.output.StatusMessage == "Input validation failed"
    assert "message" in result.output.ErrorMessage


def test_runtime_registration_rejects_cross_plugin_and_duplicate_identities() -> None:
    runtime = PluginRuntime("example/utility")
    runtime.register("example/utility/echo", EchoStep)

    with pytest.raises(RuntimeRegistrationError, match="already registered"):
        runtime.register("example/utility/echo", EchoStep)
    with pytest.raises(RuntimeRegistrationError, match="not owned"):
        runtime.register("other/utility/echo", EchoStep)


def test_reference_manifests_name_existing_implementation_classes() -> None:
    fixtures = Path(__file__).parent / "fixtures" / "steps"
    for manifest_path in sorted(fixtures.glob("*/manifest.yaml")):
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        entrypoint = manifest["spec"]["execution"]["entrypoint"]
        module_path, class_name = entrypoint.split(":", maxsplit=1)
        source = manifest_path.parent / Path(*module_path.split(".")).with_suffix(".py")

        assert source.exists(), f"{manifest_path}: no module at {source}"
        assert f"class {class_name}" in source.read_text(encoding="utf-8"), (
            f"{manifest_path}: {class_name} is not defined in {source}"
        )
