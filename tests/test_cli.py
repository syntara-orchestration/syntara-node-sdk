import json
from pathlib import Path

import pytest
import yaml
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


ARTIFACT_REF = "quay.io/example/plugins/custom-step:1.0.0"
RUNTIME_IMAGE = "quay.io/example/custom-step:1.0.0"


def test_build_writes_oci_manifest_annotation(tmp_path: Path) -> None:
    source = tmp_path / "custom_step"
    init_step(source, "custom_step", 3, RUNTIME_IMAGE)
    output = tmp_path / "step-manifest.json"

    build_step(source / "manifest.yaml", output, ARTIFACT_REF)

    artifact = json.loads(output.read_text())
    assert artifact["artifactType"] == OCI_ARTIFACT_TYPE
    assert OCI_MANIFEST_ANNOTATION in artifact["annotations"]
    assert "metadata:" in artifact["annotations"][OCI_MANIFEST_ANNOTATION]


def test_artifact_ref_does_not_overwrite_runtime_image(tmp_path: Path) -> None:
    """The packaged plugin artifact and the runtime image are distinct refs."""

    source = tmp_path / "custom_step"
    init_step(source, "custom_step", 3, RUNTIME_IMAGE)
    output = tmp_path / "step-manifest.json"

    build_step(source / "manifest.yaml", output, ARTIFACT_REF)
    artifact = json.loads(output.read_text())

    # Published-to location is the artifact ref...
    assert artifact["annotations"]["org.opencontainers.image.ref.name"] == ARTIFACT_REF
    # ...while the embedded manifest still names the runtime the step runs in.
    embedded = yaml.safe_load(artifact["annotations"][OCI_MANIFEST_ANNOTATION])
    assert embedded["spec"]["execution"]["image"] == RUNTIME_IMAGE


def test_build_requires_an_artifact_reference(tmp_path: Path) -> None:
    source = tmp_path / "custom_step"
    init_step(source, "custom_step", 3, RUNTIME_IMAGE)

    with pytest.raises(ValueError, match="artifact reference"):
        build_step(source / "manifest.yaml", tmp_path / "out.json", "")
