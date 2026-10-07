"""Small offline command-line adapter for the Syntara plugin authoring API.

The CLI deliberately delegates every source interpretation to
``compile_workspace``. It does not resolve image tags, build workload images,
sign, publish, contact a registry, or store credentials.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Sequence

from .authoring import BuildRequest, CompilationError, compile_workspace


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_VERSION = re.compile(r"^(?:0|[1-9][0-9]*)\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the authoring CLI and return its process status."""
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "init":
        return _init_workspace(arguments)
    if arguments.command in {"validate", "inspect"}:
        return _compile_workspace(arguments)
    parser.error("a command is required")
    return 2


def _parser() -> argparse.ArgumentParser:
    """Build the stable, dependency-free command surface."""
    parser = argparse.ArgumentParser(
        prog="syntara-plugin", description="Author Syntara plugin workspaces offline."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser(
        "init", help="Create one safe, compilable HTTP-action plugin workspace."
    )
    init.add_argument("directory", type=Path, help="New empty directory for the plugin workspace.")
    init.add_argument("--namespace", default="example", help="Plugin namespace (default: example).")
    init.add_argument("--name", help="Plugin name (default: final directory name).")
    init.add_argument("--version", default="0.1.0", help="Plugin SemVer version (default: 0.1.0).")
    init.add_argument("--action", default="request", help="Initial action name (default: request).")

    for command, help_text in (
        ("validate", "Compile and validate a plugin workspace."),
        ("inspect", "Print the canonical descriptor for a plugin workspace."),
    ):
        compile_command = commands.add_parser(command, help=help_text)
        compile_command.add_argument("manifest", type=Path, help="Path to plugin.yaml.")
        compile_command.add_argument(
            "--image-binding",
            action="append",
            default=[],
            metavar="ID=REPOSITORY@sha256:DIGEST",
            help="Immutable custom-workload image binding; repeat for each logical image ID.",
        )
        compile_command.add_argument(
            "--json", action="store_true", help="Print machine-readable output."
        )
    return parser


def _init_workspace(arguments: argparse.Namespace) -> int:
    """Create a contained source-only workspace without overwriting author files."""
    directory = arguments.directory.expanduser()
    name = arguments.name or directory.name
    for label, value, pattern in (
        ("namespace", arguments.namespace, _IDENTIFIER),
        ("name", name, _IDENTIFIER),
        ("action", arguments.action, _IDENTIFIER),
        ("version", arguments.version, _VERSION),
    ):
        if not pattern.fullmatch(value):
            print(f"error: {label} is not valid: {value!r}", file=sys.stderr)
            return 2
    if directory.exists():
        print(f"error: refusing to overwrite existing path: {directory}", file=sys.stderr)
        return 2

    action_path = Path("steps") / arguments.action / "manifest.yaml"
    input_path = Path("schemas") / f"{arguments.action}.input.yaml"
    try:
        directory.mkdir(parents=True)
        (directory / action_path).parent.mkdir(parents=True)
        (directory / input_path).parent.mkdir(parents=True)
        (directory / "docs").mkdir()
        (directory / "plugin.yaml").write_text(
            _plugin_template(arguments.namespace, name, arguments.version, action_path),
            encoding="utf-8",
        )
        (directory / action_path).write_text(
            _action_template(arguments.action, input_path), encoding="utf-8"
        )
        (directory / input_path).write_text(_input_template(), encoding="utf-8")
        (directory / "docs" / "README.md").write_text(
            _readme_template(name, arguments.action), encoding="utf-8"
        )
    except OSError as error:
        print(f"error: could not create workspace: {error}", file=sys.stderr)
        return 1

    print(f"Created {directory / 'plugin.yaml'}")
    print(f"Next: syntara-plugin validate {directory / 'plugin.yaml'}")
    return 0


def _compile_workspace(arguments: argparse.Namespace) -> int:
    """Compile through the public SDK API and print only safe compiler output."""
    try:
        result = compile_workspace(
            BuildRequest(
                arguments.manifest.expanduser(),
                image_bindings=_parse_image_bindings(arguments.image_binding),
            )
        )
    except CompilationError as error:
        payload = {
            "ok": False,
            "diagnostics": [diagnostic.as_dict() for diagnostic in error.diagnostics],
        }
        if arguments.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            for diagnostic in error.diagnostics:
                location = diagnostic.location
                print(
                    f"{location.file}:{location.line}:{location.column}: {diagnostic.code}: {diagnostic.message}",
                    file=sys.stderr,
                )
                print(f"  fix: {diagnostic.remediation}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if arguments.command == "inspect":
        print(result.canonical_json().decode("utf-8"))
        return 0
    payload = {"ok": True, "digest": result.digest, "assetCount": len(result.assets)}
    if arguments.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Valid: {arguments.manifest} ({result.digest}, {len(result.assets)} bundled assets)")
    return 0


def _parse_image_bindings(raw_bindings: Sequence[str]) -> dict[str, str]:
    """Parse explicit ``logical-id=immutable-reference`` inputs without I/O."""
    bindings: dict[str, str] = {}
    for raw_binding in raw_bindings:
        identifier, separator, image = raw_binding.partition("=")
        if not separator or not identifier or not image:
            msg = "--image-binding must use ID=REPOSITORY@sha256:DIGEST"
            raise ValueError(msg)
        if identifier in bindings:
            msg = f"--image-binding repeats logical image ID {identifier!r}"
            raise ValueError(msg)
        bindings[identifier] = image
    return bindings


def _plugin_template(namespace: str, name: str, version: str, action_path: Path) -> str:
    """Return the minimal root manifest for the platform-runner template."""
    return (
        "apiVersion: syntara.io/v1alpha1\n"
        "kind: Plugin\n"
        "metadata:\n"
        f"  namespace: {namespace}\n"
        f"  name: {name}\n"
        f"  version: {version}\n"
        f"  displayName: {_display_name(name)}\n"
        "  description: A Syntara plugin.\n"
        "spec:\n"
        "  documentation:\n"
        "    path: docs/README.md\n"
        "  targets:\n"
        f"    - {action_path.as_posix()}\n"
    )


def _action_template(action: str, input_path: Path) -> str:
    """Return a compilable, non-product-specific ``http.v1`` action."""
    return (
        "apiVersion: syntara.io/v1alpha1\n"
        "kind: Action\n"
        "metadata:\n"
        f"  name: {action}\n"
        f"  displayName: {_display_name(action)}\n"
        "  description: Replace this example operation with a provider-specific action.\n"
        "spec:\n"
        "  runtime:\n"
        "    kind: platform-runner\n"
        "    driver: http.v1\n"
        "    operation:\n"
        "      method: GET\n"
        "      path: /resources/{input.resource}\n"
        "  input:\n"
        "    kind: asset\n"
        f"    path: {input_path.as_posix()}\n"
        "  output:\n"
        "    kind: inline\n"
        "    value:\n"
        "      type: object\n"
        "  error:\n"
        "    kind: inline\n"
        "    value:\n"
        "      type: object\n"
    )


def _input_template() -> str:
    """Return one bounded input schema for the generated action."""
    return (
        "type: object\n"
        "additionalProperties: false\n"
        "required:\n"
        "  - resource\n"
        "properties:\n"
        "  resource:\n"
        "    type: string\n"
        "    minLength: 1\n"
        "    maxLength: 128\n"
        "    description: Provider resource identifier.\n"
    )


def _readme_template(name: str, action: str) -> str:
    """Explain the generated files and their intentionally incomplete route."""
    return (
        f"# {_display_name(name)}\n\n"
        f"This workspace starts with one `{action}` platform-runner action. "
        "Replace its generic path, schemas, documentation, integration, and credential declarations "
        "before publishing it for a real provider.\n\n"
        "Validate source without network access:\n\n"
        "```sh\n"
        "syntara-plugin validate plugin.yaml\n"
        "```\n"
    )


def _display_name(value: str) -> str:
    """Turn a valid identifier into a human-readable scaffold label."""
    return " ".join(part.capitalize() for part in value.split("-"))


if __name__ == "__main__":
    raise SystemExit(main())
