"""Base node classes for Syntara automation nodes."""

from __future__ import annotations

import traceback
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, ValidationError

from .context import ExecutionContext


class StandardOutputWrapper(BaseModel):
    """Immutable output envelope for all node executions.

    This standardized structure ensures backwards compatibility and enables
    stable template expressions like ${task.Result.stdout} across node versions.
    """

    Result: Any = Field(
        ...,
        description="Primary task return payload (type varies by node)",
    )
    StatusCode: int = Field(
        default=0,
        ge=0,
        le=255,
        description="Execution status (0 = success, non-zero = failure)",
    )
    StatusMessage: str = Field(
        default="",
        max_length=500,
        description="Human-readable execution summary",
    )
    ErrorMessage: str = Field(
        default="",
        max_length=10000,
        description="Detailed error diagnostics (populated only on failure)",
    )


# Type variables for generic input/output types
TInput = TypeVar("TInput", bound=BaseModel)
TOutput = TypeVar("TOutput", bound=BaseModel)


class BaseNode(ABC, Generic[TInput, TOutput]):
    """Abstract base for all Syntara nodes.

    Provides typed input validation, automatic StandardOutputWrapper wrapping,
    and error handling. Subclasses implement the `run()` method with their
    business logic.

    Type Parameters:
        TInput: Pydantic model for node inputs
        TOutput: Pydantic model for node outputs

    Example:
        ```python
        class MyInput(BaseModel):
            url: str
            method: str = "GET"

        class MyOutput(BaseModel):
            status_code: int
            body: str

        class MyNode(ActionNode[MyInput, MyOutput]):
            def run(self, inputs: MyInput, context: ExecutionContext) -> MyOutput:
                # Implementation
                return MyOutput(status_code=200, body="OK")
        ```
    """

    def __init__(self, input_model: type[TInput], output_model: type[TOutput]) -> None:
        """Initialize base node.

        Args:
            input_model: Pydantic model class for inputs
            output_model: Pydantic model class for outputs
        """
        self.input_model = input_model
        self.output_model = output_model

    @abstractmethod
    def run(self, inputs: TInput, context: ExecutionContext) -> TOutput:
        """Execute the node's business logic.

        This is the main entrypoint that subclasses must implement.

        Args:
            inputs: Validated, typed input parameters
            context: Execution context with logging and secrets

        Returns:
            Typed output result

        Raises:
            Exception: Any exception will be caught and wrapped in StandardOutputWrapper
        """
        pass

    def execute_raw(
        self,
        raw_inputs: dict[str, Any],
        context: ExecutionContext | None = None,
    ) -> StandardOutputWrapper:
        """Execute node with raw dictionary inputs and return wrapped output.

        This is the entrypoint called by the execution plane. It:
        1. Validates raw inputs against TInput schema
        2. Creates execution context if not provided
        3. Calls run() with typed inputs
        4. Wraps result in StandardOutputWrapper
        5. Catches and wraps any exceptions

        Args:
            raw_inputs: Raw input dictionary from workflow engine
            context: Execution context (created if not provided)

        Returns:
            StandardOutputWrapper with result or error
        """
        if context is None:
            context = ExecutionContext(node_name=self.__class__.__name__)

        context.log_execution_start(raw_inputs)

        try:
            # Validate and parse inputs
            try:
                inputs = self.input_model.model_validate(raw_inputs)
            except ValidationError as e:
                error_msg = self._format_validation_error(e)
                context.log_execution_error(e)
                return StandardOutputWrapper(
                    Result=None,
                    StatusCode=1,
                    StatusMessage="Input validation failed",
                    ErrorMessage=error_msg,
                )

            # Execute node logic
            output = self.run(inputs, context)

            # Validate output
            if not isinstance(output, self.output_model):
                output = self.output_model.model_validate(output)

            # Wrap in StandardOutputWrapper
            result = StandardOutputWrapper(
                Result=output.model_dump(),
                StatusCode=0,
                StatusMessage=f"Execution completed successfully",
                ErrorMessage="",
            )

            context.log_execution_complete(0, "Success")
            return result

        except Exception as e:
            # Catch any unhandled exceptions
            error_msg = self._format_exception(e)
            context.log_execution_error(e)

            return StandardOutputWrapper(
                Result=None,
                StatusCode=1,
                StatusMessage=f"Execution failed: {type(e).__name__}",
                ErrorMessage=error_msg,
            )

    def _format_validation_error(self, error: ValidationError) -> str:
        """Format Pydantic validation errors for ErrorMessage field.

        Args:
            error: Pydantic validation error

        Returns:
            Formatted error message with field-level details
        """
        errors = []
        for err in error.errors():
            loc = ".".join(str(x) for x in err["loc"])
            msg = err["msg"]
            errors.append(f"{loc}: {msg}")
        return "Input validation errors:\n" + "\n".join(errors)

    def _format_exception(self, error: Exception) -> str:
        """Format exception with stack trace for ErrorMessage field.

        Args:
            error: Exception that occurred

        Returns:
            Formatted error message with stack trace
        """
        tb = traceback.format_exc()
        return f"{type(error).__name__}: {error}\n\nStack trace:\n{tb}"


class ActionNode(BaseNode[TInput, TOutput]):
    """Base class for action nodes (domain and API integrations).

    Action nodes:
    - Execute in isolated containers
    - Can access API credentials (workloadClassification: action)
    - Typically make external HTTP requests or interact with third-party services

    Examples: http_request, github_issue, slack_message
    """

    pass


class TaskNode(BaseNode[TInput, TOutput]):
    """Base class for task nodes (atomic compute operations).

    Task nodes:
    - Execute in isolated containers
    - Run scripts, process data, or perform computations
    - Can access infrastructure credentials (workloadClassification: action)

    Examples: script_executor, data_transformer
    """

    pass


class WorkflowNode(BaseNode[TInput, TOutput]):
    """Base class for workflow nodes (in-memory control flow logic).

    Workflow nodes:
    - Execute in-process (execution_type: in_process)
    - Implement control flow (loops, conditions, switches)
    - No container overhead

    Examples: loop, condition, switch, converge
    """

    pass


class TriggerNode(BaseNode[TInput, TOutput]):
    """Base class for trigger nodes (event entry points).

    Trigger nodes:
    - Execute in-process (execution_type: in_process)
    - Start workflows in response to events
    - Includes special subworkflow_trigger for composable workflows

    Examples: webhook, schedule, manual, subworkflow_trigger
    """

    pass
