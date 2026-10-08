"""Plugin-level step registration and transport-neutral dispatch.

One plugin image owns one :class:`PluginRuntime`. Callers address a step by
its fully qualified ``namespace/plugin/step`` identity; the runtime validates
that identity before instantiating exactly one step implementation.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from syntara_sdk.context import ExecutionContext
from syntara_sdk.step import BaseStep, StandardOutputWrapper

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class RuntimeRegistrationError(ValueError):
    """Raised when plugin runtime registrations are internally inconsistent."""


@dataclass(frozen=True)
class QualifiedStepIdentity:
    """A validated ``namespace/plugin/step`` identity."""

    namespace: str
    plugin: str
    step: str

    @classmethod
    def parse(cls, value: str) -> QualifiedStepIdentity:
        """Parse an identity without accepting path-like or ambiguous forms."""
        if not isinstance(value, str):
            raise TypeError("step_identity must be a string")
        parts = value.split("/")
        if len(parts) != 3 or any(not _IDENTIFIER.fullmatch(part) for part in parts):
            raise ValueError(
                "step_identity must be a qualified 'namespace/plugin/step' identity"
            )
        return cls(*parts)

    @property
    def plugin_identity(self) -> str:
        """Return the owning ``namespace/plugin`` identity."""
        return f"{self.namespace}/{self.plugin}"

    def __str__(self) -> str:
        return f"{self.plugin_identity}/{self.step}"


class InvocationContext(BaseModel):
    """Serializable execution context supplied by a runtime adapter."""

    model_config = ConfigDict(extra="forbid", strict=True)

    execution_id: str | None = None
    workflow_id: str | None = None
    secret_mount_path: str = "/run/secrets"


class StepInvocation(BaseModel):
    """Transport-neutral request contract for a plugin runtime."""

    model_config = ConfigDict(extra="forbid", strict=True)

    step_identity: str
    inputs: dict[str, Any]
    context: InvocationContext = Field(default_factory=InvocationContext)

    @field_validator("step_identity")
    @classmethod
    def validate_step_identity(cls, value: str) -> str:
        QualifiedStepIdentity.parse(value)
        return value


class StepInvocationResult(BaseModel):
    """Transport-neutral result contract for a plugin runtime."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool
    step_identity: str | None = None
    output: StandardOutputWrapper | None = None
    error: str | None = None


StepFactory = Callable[[], BaseStep[Any, Any]]


class PluginRuntime:
    """Registry and dispatcher for every implementation in one plugin image."""

    def __init__(self, plugin_identity: str) -> None:
        parts = plugin_identity.split("/") if isinstance(plugin_identity, str) else []
        if len(parts) != 2 or any(not _IDENTIFIER.fullmatch(part) for part in parts):
            raise RuntimeRegistrationError(
                "plugin_identity must be a qualified 'namespace/plugin' identity"
            )
        self.plugin_identity = plugin_identity
        self._implementations: dict[str, StepFactory] = {}

    def register(
        self,
        step_identity: str,
        implementation: type[BaseStep[Any, Any]] | StepFactory,
    ) -> None:
        """Register one zero-argument ``BaseStep`` implementation."""
        identity = QualifiedStepIdentity.parse(step_identity)
        if identity.plugin_identity != self.plugin_identity:
            raise RuntimeRegistrationError(
                f"step identity {step_identity!r} is not owned by {self.plugin_identity!r}"
            )
        if step_identity in self._implementations:
            raise RuntimeRegistrationError(f"step identity {step_identity!r} is already registered")

        factory: StepFactory
        if isinstance(implementation, type):
            if not issubclass(implementation, BaseStep):
                raise RuntimeRegistrationError("registered implementation must subclass BaseStep")
            factory = implementation
        elif callable(implementation):
            factory = implementation
        else:
            raise RuntimeRegistrationError("registered implementation must be a BaseStep factory")
        self._implementations[step_identity] = factory

    def dispatch(self, request: object) -> StepInvocationResult:
        """Validate and dispatch one request without executing invalid targets."""
        try:
            # Revalidate model instances too. An adapter can receive a model
            # constructed without validation or mutated after construction.
            payload = request.model_dump(mode="python") if isinstance(request, StepInvocation) else request
            invocation = StepInvocation.model_validate(payload)
            identity = QualifiedStepIdentity.parse(invocation.step_identity)
        except (ValidationError, TypeError, ValueError):
            return StepInvocationResult(accepted=False, error="invalid step invocation request")

        if identity.plugin_identity != self.plugin_identity:
            return StepInvocationResult(
                accepted=False,
                step_identity=invocation.step_identity,
                error="step identity is not owned by this plugin runtime",
            )

        factory = self._implementations.get(invocation.step_identity)
        if factory is None:
            return StepInvocationResult(
                accepted=False,
                step_identity=invocation.step_identity,
                error="step identity is not registered by this plugin runtime",
            )

        try:
            step = factory()
        except Exception:  # noqa: BLE001 - plugin code must not crash the dispatcher
            return StepInvocationResult(
                accepted=False,
                step_identity=invocation.step_identity,
                error="registered step implementation could not be initialized",
            )
        if not isinstance(step, BaseStep):
            return StepInvocationResult(
                accepted=False,
                step_identity=invocation.step_identity,
                error="registered implementation did not create a BaseStep",
            )

        context = ExecutionContext(
            execution_id=invocation.context.execution_id,
            workflow_id=invocation.context.workflow_id,
            step_name=invocation.step_identity,
            secret_mount_path=invocation.context.secret_mount_path,
        )
        return StepInvocationResult(
            accepted=True,
            step_identity=invocation.step_identity,
            output=step.execute_raw(invocation.inputs, context),
        )
