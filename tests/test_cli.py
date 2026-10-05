import json
from pathlib import Path

import pytest
import yaml
from syntara_tools.cli import build_plugin, init_step, main
from syntara_tools.oci_client import OCI_ARTIFACT_TYPE, OCI_PLUGIN_MANIFEST_MEDIA_TYPE


def test_init_tier_two_creates_script_package(tmp_path: Path) -> None:
    target = tmp_path / "normalize_payload"
    init_step(target, "normalize_payload", 2, None, base_dir=tmp_path)
    assert (target / "main.py").exists()
    assert (target / "manifest.yaml").exists()
    manifest = yaml.safe_load((target / "manifest.yaml").read_text())
    assert "version" not in manifest["metadata"]
    assert "namespace" not in manifest["metadata"]
    assert manifest["metadata"]["tags"] == []


def test_init_tier_three_creates_dedicated_package(tmp_path: Path) -> None:
    target = tmp_path / "custom_step"
    init_step(
        target, "custom_step", 3, "quay.io/example/custom-step@sha256:" + "a" * 64, base_dir=tmp_path
    )
    assert (target / "Containerfile").exists()
    assert (target / "manifest.yaml").exists()


def test_init_rejects_mutable_workload_image(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="execution/image"):
        init_step(tmp_path / "custom_step", "custom_step", 3, "quay.io/example/custom-step:1.0.0", base_dir=tmp_path)


ARTIFACT_REF = "quay.io/example/plugins/custom-step:1.0.0"
RUNTIME_IMAGE = "quay.io/example/custom-step@sha256:" + "a" * 64


def _plugin_source(tmp_path: Path) -> Path:
    source = tmp_path / "custom_step"
    init_step(source, "custom_step", 3, "quay.io/example/custom-step@sha256:" + "a" * 64, base_dir=tmp_path)
    plugin = {
        "apiVersion": "syntara.io/v1alpha1",
        "kind": "Plugin",
        "metadata": {
            "name": "custom_plugin",
            "namespace": "example",
            "displayName": "Custom Plugin",
            "version": "1.0.0",
            "description": "A test plugin.",
            "authors": [{"name": "Example"}],
        },
        "spec": {
            "targets": ["custom_step/manifest.yaml"],
            "images": [{"repository": "quay.io/example/custom-step", "digest": "sha256:" + "a" * 64}],
        },
    }
    path = tmp_path / "plugin.yaml"
    path.write_text(yaml.safe_dump(plugin), encoding="utf-8")
    return path


def test_build_writes_oci_manifest_with_plugin_layer(tmp_path: Path) -> None:
    plugin_path = _plugin_source(tmp_path)
    output = tmp_path / "oci-layout"

    build_plugin(plugin_path, output, ARTIFACT_REF)

    index = json.loads((output / "index.json").read_text())
    descriptor = index["manifests"][0]
    artifact = json.loads(
        (output / "blobs" / "sha256" / descriptor["digest"].removeprefix("sha256:")).read_text()
    )
    assert artifact["artifactType"] == OCI_ARTIFACT_TYPE
    assert len(artifact["layers"]) == 1
    assert artifact["layers"][0]["mediaType"] == OCI_PLUGIN_MANIFEST_MEDIA_TYPE
    layer = artifact["layers"][0]
    payload = yaml.safe_load(
        (output / "blobs" / "sha256" / layer["digest"].removeprefix("sha256:")).read_text()
    )
    assert payload["plugin"]["metadata"]["name"] == "custom_plugin"
    assert len(payload["steps"]) == 1
    assert payload["steps"][0]["contentDigest"].startswith("sha256:")


def test_artifact_ref_does_not_overwrite_runtime_image(tmp_path: Path) -> None:
    """The packaged plugin artifact and the runtime image are distinct refs."""

    plugin_path = _plugin_source(tmp_path)
    output = tmp_path / "oci-layout"

    build_plugin(plugin_path, output, ARTIFACT_REF)
    index = json.loads((output / "index.json").read_text())
    descriptor = index["manifests"][0]
    artifact = json.loads(
        (output / "blobs" / "sha256" / descriptor["digest"].removeprefix("sha256:")).read_text()
    )

    # Published-to location is the artifact ref...
    assert artifact["annotations"]["org.opencontainers.image.ref.name"] == ARTIFACT_REF
    # ...while the embedded manifest still names the runtime the step runs in.
    layer = artifact["layers"][0]
    embedded = yaml.safe_load(
        (output / "blobs" / "sha256" / layer["digest"].removeprefix("sha256:")).read_text()
    )
    assert embedded["steps"][0]["manifest"]["spec"]["execution"]["image"].startswith(
        "quay.io/example/custom-step@sha256:"
    )


def test_build_requires_an_artifact_reference(tmp_path: Path) -> None:
    plugin_path = _plugin_source(tmp_path)

    with pytest.raises(ValueError, match="artifact reference"):
        build_plugin(plugin_path, tmp_path / "out.json", "")

    with pytest.raises(ValueError, match="OCI layout directory"):
        build_plugin(plugin_path, tmp_path / "out.json", ARTIFACT_REF)

    with pytest.raises(ValueError, match="explicit tag or sha256 digest"):
        build_plugin(plugin_path, tmp_path / "oci-layout", "quay.io/example/plugins/custom-step")


@pytest.mark.parametrize(
    "hostile",
    [
        Path("../escaped"),
        Path("../../etc/cron.d"),
        Path("nested/../../escaped"),
    ],
)
def test_init_rejects_paths_escaping_the_base(tmp_path: Path, hostile: Path) -> None:
    """--path may be model-generated in an agentic workflow; it must stay in-tree."""

    with pytest.raises(ValueError, match="escapes the base directory"):
        init_step(hostile, "custom_step", 3, RUNTIME_IMAGE, base_dir=tmp_path)

    assert not (tmp_path.parent / "escaped").exists()


def test_init_rejects_absolute_path_outside_base(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_target"

    with pytest.raises(ValueError, match="escapes the base directory"):
        init_step(outside, "custom_step", 3, RUNTIME_IMAGE, base_dir=tmp_path)

    assert not outside.exists()


def test_init_still_allows_a_nested_in_tree_path(tmp_path: Path) -> None:
    init_step(Path("plugins/custom_step"), "custom_step", 3, RUNTIME_IMAGE, base_dir=tmp_path)

    assert (tmp_path / "plugins" / "custom_step" / "manifest.yaml").exists()


def test_validate_detects_step_and_plugin_resources(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    step_path = tmp_path / "step"
    init_step(step_path, "step", 3, RUNTIME_IMAGE, base_dir=tmp_path)
    assert main(["validate", str(step_path / "manifest.yaml")]) == 0
    assert "validated step manifest" in capsys.readouterr().out

    step = yaml.safe_load((step_path / "manifest.yaml").read_text())
    step["spec"]["execution"] = {
        "image": "quay.io/example/custom-step@sha256:" + "a" * 64,
        "entrypoint": None,
    }
    (step_path / "manifest.yaml").write_text(yaml.safe_dump(step), encoding="utf-8")
    plugin = {
        "apiVersion": "syntara.io/v1alpha1",
        "kind": "Plugin",
        "metadata": {
            "name": "sample",
            "namespace": "syntara",
            "displayName": "Sample",
            "version": "0.1.0",
            "description": "Sample plugin.",
            "authors": [{"name": "Example"}],
        },
        "spec": {
            "targets": ["step/manifest.yaml"],
            "images": [
                {"repository": "quay.io/example/custom-step", "digest": "sha256:" + "a" * 64}
            ],
        },
    }
    (tmp_path / "plugin.yaml").write_text(yaml.safe_dump(plugin), encoding="utf-8")
    assert main(["validate", str(tmp_path / "plugin.yaml")]) == 0
    assert "validated plugin with 1 step" in capsys.readouterr().out
