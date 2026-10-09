"""Tests for the bounded Podman workload-image adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from syntara_plugin.sdk.workload import WorkloadBuildRequest, build_and_push_workload


def test_podman_build_and_push_returns_only_a_registry_digest(tmp_path: Path, monkeypatch) -> None:
    """The compiler receives repository@digest, never the mutable local tag."""
    context = tmp_path / "context"
    context.mkdir()
    containerfile = context / "Containerfile"
    containerfile.write_text("FROM scratch\n", encoding="utf-8")
    commands: list[list[str]] = []

    def run(command, **kwargs):
        commands.append(command)
        if command[1] == "push":
            Path(command[3]).write_text("sha256:" + "b" * 64, encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("syntara_plugin.sdk.workload.subprocess.run", run)
    image = build_and_push_workload(
        WorkloadBuildRequest(
            engine="podman",
            context=context,
            containerfile=containerfile,
            repository="registry.example.test/acme/custom",
            tag="0.1.0",
            platform="linux/amd64",
        )
    )

    assert image == "registry.example.test/acme/custom@sha256:" + "b" * 64
    assert commands[0] == [
        "podman",
        "build",
        "--format",
        "oci",
        "--platform",
        "linux/amd64",
        "--file",
        str(containerfile),
        "--tag",
        "registry.example.test/acme/custom:0.1.0",
        str(context),
    ]
    assert commands[1][:3] == ["podman", "push", "--digestfile"]


def test_verbose_workload_output_uses_stderr_so_json_stdout_stays_clean(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The CLI can safely combine --verbose with --json."""
    context = tmp_path / "context"
    context.mkdir()
    containerfile = context / "Containerfile"
    containerfile.write_text("FROM scratch\n", encoding="utf-8")

    def run(command, **kwargs):
        assert kwargs["stdout"] is not None
        assert kwargs["stdin"] is not None
        if command[1] == "push":
            Path(command[3]).write_text("sha256:" + "c" * 64, encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("syntara_plugin.sdk.workload.subprocess.run", run)
    build_and_push_workload(
        WorkloadBuildRequest(
            engine="podman",
            context=context,
            containerfile=containerfile,
            repository="registry.example.test/acme/custom",
            tag="0.1.0",
            platform="linux/amd64",
        ),
        verbose=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "+ podman build" in captured.err
    assert "+ podman push" in captured.err


def test_loopback_workload_push_requires_explicit_opt_in_and_passes_tls_flag(
    tmp_path: Path, monkeypatch
) -> None:
    """Local HTTP is opt-in and cannot weaken a non-loopback workload push."""
    context = tmp_path / "context"
    context.mkdir()
    containerfile = context / "Containerfile"
    containerfile.write_text("FROM scratch\n", encoding="utf-8")
    commands: list[list[str]] = []

    def run(command, **kwargs):
        commands.append(command)
        if command[1] == "push":
            Path(command[3]).write_text("sha256:" + "d" * 64, encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("syntara_plugin.sdk.workload.subprocess.run", run)
    image = build_and_push_workload(
        WorkloadBuildRequest(
            engine="podman",
            context=context,
            containerfile=containerfile,
            repository="localhost:8443/syntara-admin/custom",
            tag="0.1.0",
            platform="linux/arm64",
            allow_insecure_loopback_http=True,
        )
    )

    assert image == "localhost:8443/syntara-admin/custom@sha256:" + "d" * 64
    assert commands[1][4:] == [
        "--tls-verify=false",
        "localhost:8443/syntara-admin/custom:0.1.0",
    ]
