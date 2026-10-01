from pathlib import Path

from syntara_tools.compiler import load_manifest, validate_manifest

TESTS_DIR = Path(__file__).resolve().parent


def test_platform_owned_manifest_allows_null_image_and_entrypoint() -> None:
    manifest = load_manifest(TESTS_DIR / "fixtures" / "steps" / "subworkflow_trigger" / "manifest.yaml")
    assert validate_manifest(manifest) == []
    assert manifest["spec"]["execution"] == {"image": None, "entrypoint": None}


def test_manifests_cannot_declare_execution_placement() -> None:
    """Placement is Execution-Plane-determined; manifests must not declare it."""

    manifest = load_manifest(TESTS_DIR / "fixtures" / "steps" / "http_request" / "manifest.yaml")
    manifest["spec"]["execution"]["type"] = "container"
    errors = validate_manifest(manifest)
    assert any("type" in error for error in errors)


def test_all_reference_manifests_use_canonical_execution_block() -> None:
    for path in (TESTS_DIR / "fixtures" / "steps").glob("*/manifest.yaml"):
        manifest = load_manifest(path)
        assert validate_manifest(manifest) == [], path
