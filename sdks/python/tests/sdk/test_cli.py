"""End-to-end checks for the thin offline authoring CLI."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from syntara_plugin.sdk.cli import main


def test_init_creates_a_compilable_workspace_and_validate_reports_its_digest(
    tmp_path: Path,
    capsys,
) -> None:
    """Generated YAML goes through the same compiler as every other authoring path."""
    workspace = tmp_path / "status-tools"

    assert main(["init", str(workspace), "--namespace", "acme"]) == 0
    assert (workspace / "plugin.yaml").is_file()
    assert (workspace / "steps/request/manifest.yaml").is_file()
    assert (workspace / "schemas/request.input.yaml").is_file()

    assert main(["validate", str(workspace / "plugin.yaml"), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert payload["ok"] is True
    assert payload["digest"].startswith("sha256:")
    assert payload["assetCount"] == 2


def test_inspect_prints_the_canonical_descriptor_for_the_generated_workspace(
    tmp_path: Path,
    capsys,
) -> None:
    """Inspection is deterministic canonical output, not a second parser."""
    workspace = tmp_path / "status-tools"
    assert main(["init", str(workspace)]) == 0
    capsys.readouterr()
    assert main(["inspect", str(workspace / "plugin.yaml")]) == 0
    descriptor = json.loads(capsys.readouterr().out)
    assert descriptor["metadata"]["name"] == "status-tools"
    assert descriptor["spec"]["targets"][0]["runtime"]["driver"] == "http.v1"


def test_inspect_reads_the_verified_metadata_from_a_built_archive(tmp_path: Path, capsys) -> None:
    """Archive inspection does not need the source workspace to still exist."""
    workspace = tmp_path / "status-tools"
    archive = tmp_path / "status-tools.oci.tar"
    assert main(["init", str(workspace)]) == 0
    capsys.readouterr()
    assert main(["build", str(workspace / "plugin.yaml"), "--output", str(archive)]) == 0
    capsys.readouterr()

    assert main(["inspect", str(archive)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifactDigest"].startswith("sha256:")
    assert payload["compiledDigest"].startswith("sha256:")


def test_inspect_rejects_source_only_image_bindings_for_an_archive(tmp_path: Path, capsys) -> None:
    """Archive inspection cannot silently ignore an option that affects source compilation."""
    workspace = tmp_path / "status-tools"
    archive = tmp_path / "status-tools.oci.tar"
    assert main(["init", str(workspace)]) == 0
    capsys.readouterr()
    assert main(["build", str(workspace / "plugin.yaml"), "--output", str(archive)]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "inspect",
                str(archive),
                "--image-binding",
                "workload=quay.io/acme/test@sha256:" + "a" * 64,
            ]
        )
        == 2
    )
    assert "applies only" in capsys.readouterr().err


def test_init_refuses_to_overwrite_an_existing_path(tmp_path: Path, capsys) -> None:
    """A typo cannot replace an author's workspace."""
    workspace = tmp_path / "existing"
    workspace.mkdir()
    marker = workspace / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    assert main(["init", str(workspace)]) == 2
    assert marker.read_text(encoding="utf-8") == "keep"
    assert "refusing to overwrite" in capsys.readouterr().err


def test_validate_reports_compiler_diagnostics_without_a_traceback(tmp_path: Path, capsys) -> None:
    """Invalid source produces the compiler's stable structured diagnostic surface."""
    missing_root = tmp_path / "missing.yaml"

    assert main(["validate", str(missing_root), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["diagnostics"][0]["code"] == "DOCUMENT_UNREADABLE"


def test_validate_rejects_malformed_or_repeated_image_binding(tmp_path: Path, capsys) -> None:
    """The CLI never invents or resolves image references."""
    workspace = tmp_path / "status-tools"
    assert main(["init", str(workspace)]) == 0
    capsys.readouterr()

    assert (
        main(["validate", str(workspace / "plugin.yaml"), "--image-binding", "not-a-binding"]) == 2
    )
    assert "must use" in capsys.readouterr().err
    assert (
        main(
            [
                "validate",
                str(workspace / "plugin.yaml"),
                "--image-binding",
                "workload=quay.io/acme/test@sha256:" + "a" * 64,
                "--image-binding",
                "workload=quay.io/acme/other@sha256:" + "b" * 64,
            ]
        )
        == 2
    )
    assert "repeats logical image ID" in capsys.readouterr().err


def test_build_reports_the_immutable_oci_artifact_metadata(tmp_path: Path, capsys) -> None:
    """Build uses the public compiler and OCI builder without registry I/O."""
    workspace = tmp_path / "status-tools"
    assert main(["init", str(workspace)]) == 0
    capsys.readouterr()

    archive = tmp_path / "status-tools.oci.tar"
    assert main(["build", str(workspace / "plugin.yaml"), "--output", str(archive), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["compiledDigest"].startswith("sha256:")
    assert payload["artifactDigest"].startswith("sha256:")
    assert [blob["name"] for blob in payload["blobs"]] == [
        "config",
        "pluginDescriptor",
        "contentBundle",
    ]
    assert payload["archive"] == str(archive)
    assert archive.is_file()


def test_publish_requires_password_stdin(tmp_path: Path, capsys) -> None:
    """The command never accepts a registry password as an argument."""
    workspace = tmp_path / "status-tools"
    assert main(["init", str(workspace)]) == 0
    capsys.readouterr()
    archive = tmp_path / "status-tools.oci.tar"
    assert main(["build", str(workspace / "plugin.yaml"), "--output", str(archive)]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "publish",
                str(archive),
                "--registry-origin",
                "https://registry.example.test",
                "--repository",
                "acme/status-tools",
                "--channel",
                "0.1.0",
                "--username",
                "publisher",
            ]
        )
        == 2
    )
    assert "requires --password-stdin" in capsys.readouterr().err


def test_publish_reports_immutable_reference(tmp_path: Path, capsys, monkeypatch) -> None:
    """Publication accepts only an explicit destination and stdin credential."""
    workspace = tmp_path / "status-tools"
    assert main(["init", str(workspace)]) == 0
    capsys.readouterr()
    archive = tmp_path / "status-tools.oci.tar"
    assert main(["build", str(workspace / "plugin.yaml"), "--output", str(archive)]) == 0
    capsys.readouterr()

    published: dict[str, object] = {}

    class Publisher:
        def __init__(self, target, *, credentials) -> None:
            published["target"] = target
            published["credentials"] = credentials

        def publish(self, artifact):
            published["artifact"] = artifact
            return SimpleNamespace(
                channel="0.1.0",
                immutable_reference=f"acme/status-tools@{artifact.digest}",
                repository="acme/status-tools",
            )

    monkeypatch.setattr("syntara_plugin.sdk.cli.PluginArtifactPublisher", Publisher)
    monkeypatch.setattr("sys.stdin.read", lambda: "not-printed\n")

    assert (
        main(
            [
                "publish",
                str(archive),
                "--registry-origin",
                "https://registry.example.test",
                "--repository",
                "acme/status-tools",
                "--channel",
                "0.1.0",
                "--username",
                "publisher",
                "--password-stdin",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["immutableReference"] == f"acme/status-tools@{payload['artifactDigest']}"
    assert published["credentials"].password == "not-printed"
