"""Local CLI runner for testing Syntara nodes offline."""

from __future__ import annotations

import argparse
import json
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

from .context import ExecutionContext
from .node import BaseNode


def load_node_class(module_path: str, class_name: str) -> type[BaseNode]:
    """Dynamically load a node class from a Python module.

    Args:
        module_path: Python module path (e.g., 'examples.http_request.src.main')
        class_name: Node class name (e.g., 'HttpRequestNode')

    Returns:
        Node class

    Raises:
        ImportError: If module or class cannot be loaded
    """
    try:
        module = import_module(module_path)
    except ImportError as e:
        raise ImportError(f"Failed to import module '{module_path}': {e}")

    try:
        node_class = getattr(module, class_name)
    except AttributeError:
        raise ImportError(
            f"Class '{class_name}' not found in module '{module_path}'"
        )

    if not issubclass(node_class, BaseNode):
        raise TypeError(
            f"{class_name} must be a subclass of BaseNode"
        )

    return node_class


def load_inputs_from_file(path: Path) -> dict[str, Any]:
    """Load inputs from a JSON file.

    Args:
        path: Path to JSON file

    Returns:
        Input dictionary

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file is not valid JSON
    """
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    with path.open() as f:
        return json.load(f)


def run_node_local(
    node_class: type[BaseNode],
    inputs: dict[str, Any],
    execution_id: str | None = None,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    """Execute a node locally with the given inputs.

    Args:
        node_class: Node class to instantiate and run
        inputs: Input dictionary
        execution_id: Optional execution ID
        workflow_id: Optional workflow ID

    Returns:
        StandardOutputWrapper as dictionary
    """
    # Create execution context
    context = ExecutionContext(
        execution_id=execution_id,
        workflow_id=workflow_id,
        node_name=node_class.__name__,
    )

    # Instantiate node (subclasses must provide input/output models)
    node = node_class()

    # Execute and return wrapped output
    output = node.execute_raw(inputs, context)
    return output.model_dump()


def main() -> int:
    """CLI entrypoint for local node testing.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    parser = argparse.ArgumentParser(
        description="Run a Syntara node locally for testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with inline JSON inputs
  python -m syntara_sdk.runner \\
    --module examples.http_request.src.main \\
    --class HttpRequestNode \\
    --inputs '{"url": "https://httpbin.org/get", "method": "GET"}'

  # Run with inputs from file
  python -m syntara_sdk.runner \\
    --module examples.http_request.src.main \\
    --class HttpRequestNode \\
    --inputs-file inputs.json
        """,
    )

    parser.add_argument(
        "--module",
        required=True,
        help="Python module path (e.g., 'examples.http_request.src.main')",
    )
    parser.add_argument(
        "--class",
        dest="class_name",
        required=True,
        help="Node class name (e.g., 'HttpRequestNode')",
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--inputs",
        help="Input JSON string",
    )
    input_group.add_argument(
        "--inputs-file",
        type=Path,
        help="Path to input JSON file",
    )

    parser.add_argument(
        "--execution-id",
        help="Execution ID (generated if not provided)",
    )
    parser.add_argument(
        "--workflow-id",
        help="Workflow ID",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Write output to file (prints to stdout if not provided)",
    )

    args = parser.parse_args()

    try:
        # Load node class
        print(f"Loading node: {args.module}.{args.class_name}", file=sys.stderr)
        node_class = load_node_class(args.module, args.class_name)

        # Load inputs
        if args.inputs:
            inputs = json.loads(args.inputs)
        else:
            print(f"Loading inputs from: {args.inputs_file}", file=sys.stderr)
            inputs = load_inputs_from_file(args.inputs_file)

        # Run node
        print("Executing node...", file=sys.stderr)
        output = run_node_local(
            node_class,
            inputs,
            execution_id=args.execution_id,
            workflow_id=args.workflow_id,
        )

        # Write output
        output_json = json.dumps(output, indent=2)
        if args.output_file:
            args.output_file.write_text(output_json)
            print(f"Output written to: {args.output_file}", file=sys.stderr)
        else:
            print(output_json)

        # Exit code based on StatusCode
        return 0 if output["StatusCode"] == 0 else 1

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
