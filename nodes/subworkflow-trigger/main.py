#!/usr/bin/env python3
"""Conceptual reference for the child-side ``subworkflow_trigger`` contract.

The trigger marks a workflow as eligible for Reference-mode invocation and
defines the child input/output boundary. It does not select or invoke another
workflow; that responsibility belongs to the parent-side ``subworkflow_call``
node.

In production, eligibility checks and child lifecycle management are performed
by the control-plane orchestrator. This module only demonstrates the shape of a
validated child-entry result for local contract tests.
"""

from __future__ import annotations

from typing import Any


def validate_child_entry(inputs: dict[str, Any]) -> dict[str, Any]:
    """Return a standard result for a child workflow entry payload."""

    input_variables = inputs.get("input_variables")
    if not isinstance(input_variables, dict):
        return {
            "Result": None,
            "StatusCode": 1,
            "StatusMessage": "Child workflow input validation failed",
            "ErrorMessage": "input_variables must be an object",
        }

    return {
        "Result": {"input_variables": input_variables},
        "StatusCode": 0,
        "StatusMessage": "Child workflow entry accepted",
        "ErrorMessage": "",
    }
