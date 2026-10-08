"""A small JSON adapter around the plugin-level runtime dispatcher.

The SDK does not define a network protocol. This is intentionally a stdio
adapter so an image has one fixed process entrypoint while a future transport
can use the same ``StepInvocation`` contract directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from syntara_sdk.runtime import PluginRuntime


def load_plugin_runtime(module_path: str) -> PluginRuntime:
    """Load a plugin runtime from a module exposing ``create_runtime()``."""
    module = import_module(module_path)
    factory = getattr(module, "create_runtime", None)
    if not callable(factory):
        raise TypeError(f"runtime module {module_path!r} must define create_runtime()")
    runtime = factory()
    if not isinstance(runtime, PluginRuntime):
        raise TypeError("create_runtime() must return PluginRuntime")
    return runtime


def dispatch_json(runtime: PluginRuntime, request: object) -> dict[str, Any]:
    """Dispatch a decoded request using the transport-neutral contract."""
    return runtime.dispatch(request).model_dump(mode="json")


def _read_request(args: argparse.Namespace) -> object:
    if args.request is not None:
        return cast(object, json.loads(args.request))
    if args.request_file is not None:
        return cast(object, json.loads(args.request_file.read_text(encoding="utf-8")))
    for line in sys.stdin:
        if line.strip():
            return cast(object, json.loads(line))
    raise ValueError("one JSON StepInvocation request is required")


def _exit_code(result: dict[str, Any]) -> int:
    """Return a process status that preserves the dispatched step result."""
    if not result["accepted"]:
        return 1
    output = result.get("output")
    if not isinstance(output, dict):
        return 1
    return 0 if output.get("StatusCode") == 0 else 1


def main() -> int:
    """Run exactly one request and then exit."""
    parser = argparse.ArgumentParser(description="Run a plugin-level Syntara dispatcher")
    parser.add_argument("--runtime-module", required=True)
    request_group = parser.add_mutually_exclusive_group()
    request_group.add_argument("--request", help="one JSON StepInvocation object")
    request_group.add_argument("--request-file", type=Path, help="file containing one request object")
    args = parser.parse_args()

    try:
        runtime = load_plugin_runtime(args.runtime_module)
        request = _read_request(args)
        result = dispatch_json(runtime, request)
        print(json.dumps(result))
        return _exit_code(result)
    except (ImportError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
