from pathlib import Path

from syntara_sdk.compiler import load_manifest, validate_manifest

ROOT = Path(__file__).resolve().parents[1]


def test_in_process_manifest_allows_null_image_and_entrypoint() -> None:
    manifest = load_manifest(ROOT / "nodes" / "subworkflow-trigger" / "manifest.yaml")
    assert validate_manifest(manifest) == []
    assert manifest["spec"]["execution"] == {
        "type": "in_process",
        "image": None,
        "entrypoint": None,
    }


def test_container_manifest_requires_image() -> None:
    manifest = load_manifest(ROOT / "nodes" / "http-request" / "manifest.yaml")
    manifest["spec"]["execution"].pop("image")
    errors = validate_manifest(manifest)
    assert any("image" in error and "required" in error for error in errors)


def test_all_reference_manifests_use_canonical_execution_block() -> None:
    for path in (ROOT / "nodes").glob("*/manifest.yaml"):
        manifest = load_manifest(path)
        assert validate_manifest(manifest) == [], path
