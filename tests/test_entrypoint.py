"""`spec.execution.entrypoint` is a step handle, not a shell command."""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml
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

    init_step(tmp_path / "my_thing", "my_thing", 3, "quay.io/example/runner:1.0.0")
    manifest = yaml.safe_load((tmp_path / "my_thing" / "manifest.yaml").read_text())

    entrypoint = manifest["spec"]["execution"]["entrypoint"]
    module_path, class_name = parse_entrypoint(entrypoint)
    source = (tmp_path / "my_thing" / f"{module_path}.py").read_text()
    assert f"class {class_name}(" in source


def test_schema_requires_an_entrypoint_whenever_an_image_is_set() -> None:
    """Uniform loading: an image-backed step always declares its handle."""

    validator = jsonschema.Draft7Validator(
        {**SCHEMA, "$ref": "#/definitions/StepTypeManifest"}
    )
    manifest = yaml.safe_load((FIXTURES / "http_request" / "manifest.yaml").read_text())
    del manifest["spec"]["execution"]["entrypoint"]

    errors = [e.message for e in validator.iter_errors(manifest)]
    assert any("entrypoint" in e for e in errors)


def test_scaffolded_containerfile_launches_via_the_sdk_runner(tmp_path: Path) -> None:
    """The image must be runnable, and must go through BaseStep, not a bare script."""

    init_step(tmp_path / "my_thing", "my_thing", 3, "quay.io/example/runner:1.0.0")
    containerfile = (tmp_path / "my_thing" / "Containerfile").read_text()
    manifest = yaml.safe_load((tmp_path / "my_thing" / "manifest.yaml").read_text())
    entrypoint = manifest["spec"]["execution"]["entrypoint"]

    assert "FROM docker.io/library/python" in containerfile
    assert "syntara_sdk.runner" in containerfile
    assert entrypoint in containerfile
    # A bare script invocation would bypass validation and the redact check.
    assert 'CMD ["python", "/app/main.py"]' not in containerfile
