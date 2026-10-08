from pathlib import Path

from syntara_tools.compiler import load_manifest, validate_manifest

TESTS_DIR = Path(__file__).resolve().parent


def test_every_step_manifest_requires_a_workload_image() -> None:
    manifest = load_manifest(TESTS_DIR / "fixtures" / "steps" / "subworkflow_trigger" / "manifest.yaml")
    assert validate_manifest(manifest) == []
    assert manifest["spec"]["execution"]["image"].startswith("quay.io/syntara/")

    del manifest["spec"]["execution"]["image"]
    assert any("image" in error for error in validate_manifest(manifest))


def test_manifests_cannot_declare_execution_placement() -> None:
    """Placement is Execution-Plane-determined; manifests must not declare it."""

    manifest = load_manifest(TESTS_DIR / "fixtures" / "steps" / "http_request" / "manifest.yaml")
    manifest["spec"]["execution"]["type"] = "container"
    errors = validate_manifest(manifest)
    assert any("type" in error for error in errors)


def test_workload_images_must_be_pinned_by_sha256_digest() -> None:
    manifest = load_manifest(TESTS_DIR / "fixtures" / "steps" / "http_request" / "manifest.yaml")
    manifest["spec"]["execution"]["image"] = "quay.io/syntara/http-request-executor:1.0.0"

    assert any("execution/image" in error for error in validate_manifest(manifest))


def test_all_reference_manifests_use_canonical_execution_block() -> None:
    for path in (TESTS_DIR / "fixtures" / "steps").glob("*/manifest.yaml"):
        manifest = load_manifest(path)
        assert validate_manifest(manifest) == [], path
