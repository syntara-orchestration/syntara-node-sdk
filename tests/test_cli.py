import json
from pathlib import Path

from syntara_sdk.cli import build_node, init_node
from syntara_sdk.registry.service import OCI_ARTIFACT_TYPE, OCI_MANIFEST_ANNOTATION


def test_init_tier_two_creates_script_package(tmp_path: Path) -> None:
    target = tmp_path / "normalize_payload"
    init_node(target, "normalize_payload", 2, None)
    assert (target / "main.py").exists()
    assert (target / "manifest.yaml").exists()


def test_init_tier_three_creates_dedicated_package(tmp_path: Path) -> None:
    target = tmp_path / "custom_node"
    init_node(target, "custom_node", 3, "quay.io/example/custom-node:1.0.0")
    assert (target / "Containerfile").exists()
    assert (target / "manifest.yaml").exists()


def test_build_writes_oci_manifest_annotation(tmp_path: Path) -> None:
    source = tmp_path / "custom_node"
    init_node(source, "custom_node", 3, "quay.io/example/custom-node:1.0.0")
    output = tmp_path / "node-manifest.json"

    build_node(source / "manifest.yaml", output)

    artifact = json.loads(output.read_text())
    assert artifact["artifactType"] == OCI_ARTIFACT_TYPE
    assert OCI_MANIFEST_ANNOTATION in artifact["annotations"]
    assert "metadata:" in artifact["annotations"][OCI_MANIFEST_ANNOTATION]
