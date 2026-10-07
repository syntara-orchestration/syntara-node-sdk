"""`spec.execution.entrypoint` is a step handle, not a shell command."""

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml
from pydantic import BaseModel
from syntara_sdk import ActionStep, ExecutionContext
from syntara_sdk.runner import parse_entrypoint
from syntara_tools.cli import init_step

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[1] / "schemas" / "common-definitions.json").read_text()
)
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "steps"


def _entrypoint_validator() -> jsonschema.Draft7Validator:
    execution = SCHEMA["definitions"]["StepTypeManifest"]["properties"]["spec"]["properties"][
        "execution"
    ]
    return jsonschema.Draft7Validator({**SCHEMA, **execution["properties"]["entrypoint"]})


def test_parse_entrypoint_splits_module_and_class() -> None:
    assert parse_entrypoint("src.main:HttpRequestStep") == ("src.main", "HttpRequestStep")
    assert parse_entrypoint("main:Step") == ("main", "Step")


@pytest.mark.parametrize(
    "bad",
    ["python /workspace/main.py", "main", ":Step", "main:", ""],
)
def test_parse_entrypoint_rejects_non_handles(bad: str) -> None:
    with pytest.raises(ValueError, match="module.path:ClassName"):
        parse_entrypoint(bad)


def test_schema_rejects_shell_command_entrypoint() -> None:
    """A shell command would bypass BaseStep validation, so the schema blocks it."""

    validator = _entrypoint_validator()
    assert list(validator.iter_errors("python /workspace/main.py"))
    assert not list(validator.iter_errors("src.main:HttpRequestStep"))


def test_fixture_entrypoints_resolve_to_real_classes() -> None:
    """Every declared entrypoint must name a class that actually exists."""

    for manifest_path in sorted(FIXTURES.glob("*/manifest.yaml")):
        manifest = yaml.safe_load(manifest_path.read_text())
        entrypoint = manifest["spec"]["execution"].get("entrypoint")
        if entrypoint is None:
            continue
        module_path, class_name = parse_entrypoint(entrypoint)
        source = manifest_path.parent / Path(*module_path.split(".")).with_suffix(".py")
        assert source.exists(), f"{manifest_path}: no module at {source}"
        assert f"class {class_name}" in source.read_text(), (
            f"{manifest_path}: {class_name} not defined in {source}"
        )


def test_scaffolded_step_defines_the_class_its_entrypoint_names(tmp_path: Path) -> None:
    """The scaffold must not emit a handle pointing at a class it never writes."""

    init_step(
        tmp_path / "my_thing",
        "my_thing",
        3,
        "quay.io/example/runner@sha256:" + "a" * 64,
        base_dir=tmp_path,
    )
    manifest = yaml.safe_load((tmp_path / "my_thing" / "manifest.yaml").read_text())

    entrypoint = manifest["spec"]["execution"]["entrypoint"]
    module_path, class_name = parse_entrypoint(entrypoint)
    source = (tmp_path / "my_thing" / f"{module_path}.py").read_text()
    assert f"class {class_name}(" in source


def test_schema_allows_a_workload_without_a_control_plane_handle() -> None:
    """A workload image may omit the optional control-plane loading handle."""

    validator = jsonschema.Draft7Validator(
        {**SCHEMA, "$ref": "#/definitions/StepTypeManifest"}
    )
    manifest = yaml.safe_load((FIXTURES / "http_request" / "manifest.yaml").read_text())
    del manifest["spec"]["execution"]["entrypoint"]

    assert list(validator.iter_errors(manifest)) == []


def test_workload_boundary_contract_without_control_plane_handle() -> None:
    """SDK boundary contract pending a real protobuf/gRPC transport implementation.

    The SDK has no gRPC service or generated protobuf runtime. This test fixes the
    transport-neutral request/response contract that a step-side adapter must carry.
    """

    manifest = yaml.safe_load((FIXTURES / "http_request" / "manifest.yaml").read_text())
    del manifest["spec"]["execution"]["entrypoint"]

    class Input(BaseModel):
        message: str

    class Output(BaseModel):
        message: str

    class WorkloadStep(ActionStep[Input, Output]):
        def __init__(self) -> None:
            super().__init__(Input, Output)

        def run(self, inputs: Input, context: ExecutionContext) -> Output:
            return Output(message=inputs.message)

    def invoke_boundary(request: dict[str, Any]) -> dict[str, Any]:
        """Explicit protocol fixture; this is not a gRPC server integration."""
        if set(request) != {"inputs", "workflow_context"} or not isinstance(request["inputs"], dict):
            raise ValueError("invalid SDK boundary input envelope")
        context_data = request["workflow_context"]
        if not isinstance(context_data, dict):
            raise ValueError("workflow_context must be a mapping")
        return WorkloadStep().execute_raw(
            request["inputs"],
            ExecutionContext(step_name=context_data.get("step_name", "unknown")),
        ).model_dump()

    response = invoke_boundary(
        {
            "inputs": {"message": "accepted by step-side adapter"},
            "workflow_context": {"step_name": "workload-boundary"},
        }
    )

    assert manifest["spec"]["execution"]["image"]
    assert "entrypoint" not in manifest["spec"]["execution"]
    assert response == {
        "Result": {"message": "accepted by step-side adapter"},
        "StatusCode": 0,
        "StatusMessage": "Execution completed successfully",
        "ErrorMessage": "",
    }
    invalid_response = invoke_boundary({"inputs": {}, "workflow_context": {}})
    assert invalid_response["StatusCode"] == 1
    assert invalid_response["StatusMessage"] == "Input validation failed"


def test_schema_requires_a_workload_image_even_without_a_control_plane_handle() -> None:
    """Every separately packaged step has a workload image."""

    validator = jsonschema.Draft7Validator(
        {**SCHEMA, "$ref": "#/definitions/StepTypeManifest"}
    )
    manifest = yaml.safe_load((FIXTURES / "subworkflow_call" / "manifest.yaml").read_text())
    del manifest["spec"]["execution"]["image"]

    errors = list(validator.iter_errors(manifest))
    assert any(
        error.validator == "required" and list(error.absolute_path) == ["spec", "execution"]
        for error in errors
    )


def test_scaffolded_containerfile_has_a_safe_local_development_runner(tmp_path: Path) -> None:
    """The scaffold's local command must not bypass BaseStep safeguards."""

    init_step(
        tmp_path / "my_thing",
        "my_thing",
        3,
        "quay.io/example/runner@sha256:" + "a" * 64,
        base_dir=tmp_path,
    )
    containerfile = (tmp_path / "my_thing" / "Containerfile").read_text()
    manifest = yaml.safe_load((tmp_path / "my_thing" / "manifest.yaml").read_text())
    entrypoint = manifest["spec"]["execution"]["entrypoint"]

    assert "FROM docker.io/library/python" in containerfile
    assert "syntara_sdk.runner" in containerfile
    assert entrypoint in containerfile
    # A bare script invocation would bypass validation.
    assert 'CMD ["python", "/app/main.py"]' not in containerfile


def test_manifests_never_carry_credential_identifiers() -> None:
    """A step type is published before any credential exists, so it cannot name one."""

    validator = jsonschema.Draft7Validator({**SCHEMA, "$ref": "#/definitions/CredentialRequirement"})
    requirement = {
        "name": "api_auth",
        "types": ["API Key"],
        "credential_id": "550e8400-e29b-41d4-a716-446655440000",
    }
    assert list(validator.iter_errors(requirement)), "must reject a credential UUID"
    assert not list(validator.iter_errors({"name": "api_auth", "types": ["API Key"]}))


def test_no_fixture_declares_a_credential_uuid() -> None:
    for manifest_path in sorted(FIXTURES.glob("*/manifest.yaml")):
        assert "credential_id" not in manifest_path.read_text(), manifest_path
