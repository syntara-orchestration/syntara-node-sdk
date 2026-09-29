from pathlib import Path

from syntara_tools.compiler import load_manifest, validate_manifest

TESTS_DIR = Path(__file__).resolve().parent


def test_in_process_manifest_allows_null_image_and_entrypoint() -> None:
    manifest = load_manifest(TESTS_DIR / "fixtures" / "steps" / "subworkflow_trigger" / "manifest.yaml")
    assert validate_manifest(manifest) == []
    assert manifest["spec"]["execution"] == {
        "type": "in_process",
        "image": None,
        "entrypoint": None,
    }


def test_container_manifest_requires_image() -> None:
    manifest = load_manifest(TESTS_DIR / "fixtures" / "steps" / "http_request" / "manifest.yaml")
    manifest["spec"]["execution"].pop("image")
    errors = validate_manifest(manifest)
    assert any("image" in error and "required" in error for error in errors)


def test_all_reference_manifests_use_canonical_execution_block() -> None:
    for path in (TESTS_DIR / "fixtures" / "steps").glob("*/manifest.yaml"):
        manifest = load_manifest(path)
        assert validate_manifest(manifest) == [], path
