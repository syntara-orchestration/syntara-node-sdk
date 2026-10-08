"""Tests for the single-invocation runtime process adapter."""

from __future__ import annotations

import io
import json
import sys

from pydantic import BaseModel
from syntara_sdk import ActionStep, ExecutionContext, PluginRuntime, runner


class Input(BaseModel):
    message: str


class Output(BaseModel):
    message: str


class CountingStep(ActionStep[Input, Output]):
    calls = 0

    def __init__(self) -> None:
        super().__init__(Input, Output)

    def run(self, inputs: Input, context: ExecutionContext) -> Output:
        type(self).calls += 1
        return Output(message=inputs.message)


def _runtime() -> PluginRuntime:
    runtime = PluginRuntime("example/plugin")
    runtime.register("example/plugin/count", CountingStep)
    return runtime


def test_runner_dispatches_one_stdin_request_and_exits(monkeypatch, capsys) -> None:
    CountingStep.calls = 0
    first = {"step_identity": "example/plugin/count", "inputs": {"message": "first"}}
    second = {"step_identity": "example/plugin/count", "inputs": {"message": "second"}}
    monkeypatch.setattr(runner, "load_plugin_runtime", lambda _: _runtime())
    monkeypatch.setattr(sys, "argv", ["runner", "--runtime-module", "plugin_runtime"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{json.dumps(first)}\n{json.dumps(second)}\n"))

    assert runner.main() == 0
    assert CountingStep.calls == 1
    assert json.loads(capsys.readouterr().out)["output"]["Result"] == {"message": "first"}


def test_runner_returns_failure_for_a_step_failure(monkeypatch, capsys) -> None:
    request = {"step_identity": "example/plugin/count", "inputs": {}}
    monkeypatch.setattr(runner, "load_plugin_runtime", lambda _: _runtime())
    monkeypatch.setattr(sys, "argv", ["runner", "--runtime-module", "plugin_runtime"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request)))

    assert runner.main() == 1
    response = json.loads(capsys.readouterr().out)
    assert response["accepted"] is True
    assert response["output"]["StatusCode"] == 1
