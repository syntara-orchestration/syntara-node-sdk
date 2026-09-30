"""Optional JSON stdin/stdout container adapter for the SDK node contract."""

import argparse
import json
import sys
from typing import Any

from syntara_sdk import ExecutionContext
from syntara_sdk.node import StandardOutputWrapper

from .catalog import OPERATIONS
from .nodes import NODE_CLASSES


def invoke(operation: str, payload: dict[str, Any], *, transport=None) -> StandardOutputWrapper:
    try:
        if not isinstance(payload, dict) or payload.keys() - {
            "inputs",
            "credentials",
            "workflow_context",
        }:
            raise ValueError
        inputs = payload.get("inputs", {})
        credentials = payload.get("credentials", {})
        if not isinstance(inputs, dict) or not isinstance(credentials, dict):
            raise ValueError
        node_type = NODE_CLASSES[operation]
        secret_fields = {
            name
            for name, field in OPERATIONS[operation].model.model_fields.items()
            if (field.json_schema_extra or {}).get("secret") is True
        }
        if credentials.keys() - secret_fields - {"token"}:
            raise ValueError
        token = credentials.get("token")
        if token is not None and (not isinstance(token, str) or not token.strip()):
            raise ValueError
        # Sensitive inputs arrive separately; reject ambiguous duplicate values.
        if inputs.keys() & secret_fields:
            raise ValueError
        merged = {**inputs, **{key: value for key, value in credentials.items() if key != "token"}}
        node = node_type(token=token, transport=transport)
        workflow_context = payload.get("workflow_context", {})
        if not isinstance(workflow_context, dict):
            raise ValueError
        context = ExecutionContext(
            execution_id=workflow_context.get("execution_id"),
            workflow_id=workflow_context.get("workflow_id"),
            node_name="tfe_" + operation,
        )
        return node.execute_raw(merged, context)
    except (KeyError, ValueError, TypeError, AttributeError):
        return StandardOutputWrapper(
            Result=None,
            StatusCode=1,
            StatusMessage="Invalid TFE invocation",
            ErrorMessage="Check operation, inputs, credentials, and workflow_context against the documented contract",
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=NODE_CLASSES)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read(100 * 1024 * 1024 + 1)
        if len(raw) > 100 * 1024 * 1024:
            raise ValueError
        result = invoke(args.operation, json.loads(raw))
    except (ValueError, UnicodeError):
        result = StandardOutputWrapper(
            Result=None,
            StatusCode=1,
            StatusMessage="Invalid TFE invocation",
            ErrorMessage="Expected one JSON object on stdin (maximum 100 MiB)",
        )
    print(result.model_dump_json())
    return 0 if result.StatusCode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
