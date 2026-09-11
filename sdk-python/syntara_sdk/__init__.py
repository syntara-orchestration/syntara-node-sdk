"""Syntara Node SDK - Build type-safe automation nodes for Syntara workflows."""

__version__ = "0.1.0"

from .context import ExecutionContext
from .credentials import (
    ApiKeyCredential,
    BasicAuthCredential,
    BearerTokenCredential,
    CredentialMountType,
    CredentialReference,
)
from .node import (
    ActionNode,
    BaseNode,
    StandardOutputWrapper,
    TaskNode,
    TriggerNode,
    WorkflowNode,
)

__all__ = [
    # Core
    "BaseNode",
    "ActionNode",
    "TaskNode",
    "WorkflowNode",
    "TriggerNode",
    # Models
    "StandardOutputWrapper",
    "ExecutionContext",
    # Credentials
    "CredentialReference",
    "CredentialMountType",
    "ApiKeyCredential",
    "BearerTokenCredential",
    "BasicAuthCredential",
]
