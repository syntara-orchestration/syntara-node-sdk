import json
from pathlib import Path

from syntara_tools.cli import build_step, init_step
from syntara_tools.oci_client import OCI_ARTIFACT_TYPE, OCI_MANIFEST_ANNOTATION


def test_init_tier_two_creates_script_package(tmp_path: Path) -> None:
    target = tmp_path / "normalize_payload"
    init_step(target, "normalize_payload", 2, None)
    assert (target / "main.py").exists()
    assert (target / "manifest.yaml").exists()


def test_init_tier_three_creates_dedicated_package(tmp_path: Path) -> None:
    target = tmp_path / "custom_step"
    init_step(target, "custom_step", 3, "quay.io/example/custom-step:1.0.0")
    assert (target / "Containerfile").exists()
    assert (target / "manifest.yaml").exists()


def test_build_writes_oci_manifest_annotation(tmp_path: Path) -> None:
    source = tmp_path / "custom_step"
    init_step(source, "custom_step", 3, "quay.io/example/custom-step:1.0.0")
    output = tmp_path / "step-manifest.json"

    build_step(source / "manifest.yaml", output)

    artifact = json.loads(output.read_text())
    assert artifact["artifactType"] == OCI_ARTIFACT_TYPE
    assert OCI_MANIFEST_ANNOTATION in artifact["annotations"]
    assert "metadata:" in artifact["annotations"][OCI_MANIFEST_ANNOTATION]
