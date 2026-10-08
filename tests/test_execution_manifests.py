"""Tests for the plugin-owned runtime contract."""

from __future__ import annotations

from pathlib import Path

import yaml
from syntara_tools.compiler import load_manifest, validate_manifest, validate_plugin_manifest

TESTS_DIR = Path(__file__).resolve().parent


def test_step_manifests_do_not_select_a_runtime_image() -> None:
    manifest = load_manifest(TESTS_DIR / "fixtures" / "steps" / "subworkflow_trigger" / "manifest.yaml")
    assert validate_manifest(manifest) == []
    assert set(manifest["spec"]["execution"]) == {"entrypoint"}

    manifest["spec"]["execution"] = {
        "image": "quay.io/example/other@sha256:" + "a" * 64,
    }
    assert any("execution" in error for error in validate_manifest(manifest))


def test_step_manifests_require_an_implementation_entrypoint() -> None:
    manifest = load_manifest(TESTS_DIR / "fixtures" / "steps" / "subworkflow_trigger" / "manifest.yaml")
    assert manifest["spec"]["execution"]["entrypoint"] == "main:SubworkflowTriggerStep"

    del manifest["spec"]["execution"]
    assert any("execution" in error for error in validate_manifest(manifest))


def test_root_plugin_runtime_image_must_be_digest_pinned() -> None:
    plugin_path = TESTS_DIR / "fixtures" / "plugins" / "terraform_enterprise" / "plugin.yaml"
    plugin = yaml.safe_load(plugin_path.read_text(encoding="utf-8"))
    assert validate_plugin_manifest(plugin) == []
    assert plugin["spec"]["runtime"]["image"].startswith("quay.io/syntara/")

    plugin["spec"]["runtime"]["image"] = "quay.io/example/runtime:latest"
    assert any("runtime/image" in error for error in validate_plugin_manifest(plugin))


def test_all_reference_step_manifests_declare_only_an_execution_entrypoint() -> None:
    for path in (TESTS_DIR / "fixtures" / "steps").glob("*/manifest.yaml"):
        manifest = load_manifest(path)
        assert validate_manifest(manifest) == [], path
        assert set(manifest["spec"]["execution"]) == {"entrypoint"}, path
