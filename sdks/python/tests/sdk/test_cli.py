"""End-to-end checks for the thin offline authoring CLI."""

from __future__ import annotations

import json
from pathlib import Path

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
