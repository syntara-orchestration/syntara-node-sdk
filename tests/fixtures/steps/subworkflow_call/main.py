"""Conceptual reference for the parent-side subworkflow call contract."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from syntara_sdk import ExecutionContext, WorkflowStep


class SubworkflowCallInput(BaseModel):
    workflow_id: UUID
    input_variables: dict[str, Any] = Field(default_factory=dict)


class SubworkflowCallOutput(BaseModel):
    workflow_id: UUID
    input_variables: dict[str, Any]


class SubworkflowCallStep(WorkflowStep[SubworkflowCallInput, SubworkflowCallOutput]):
    """Control-plane-loadable implementation for Reference-mode invocation."""

    def __init__(self) -> None:
        super().__init__(SubworkflowCallInput, SubworkflowCallOutput)

    def run(
        self, inputs: SubworkflowCallInput, context: ExecutionContext
    ) -> SubworkflowCallOutput:
        return SubworkflowCallOutput(
            workflow_id=inputs.workflow_id,
            input_variables=inputs.input_variables,
        )
