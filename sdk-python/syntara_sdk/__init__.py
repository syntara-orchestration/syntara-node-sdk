"""Syntara Node SDK - Build type-safe automation nodes for Syntara workflows."""

__version__ = "0.1.0"

from .compiler import (
    compile_manifest,
    compile_manifest_data,
    load_manifest,
    validate_manifest,
)
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
from .registry.oci_client import (
    OCI_ARTIFACT_TYPE,
    OCI_MANIFEST_ANNOTATION,
    OCIRegistryClient,
    OCIRegistryError,
)

__all__ = [
    "OCI_ARTIFACT_TYPE",
    "OCI_MANIFEST_ANNOTATION",
    "OCIRegistryClient",
    "OCIRegistryError",
    "ActionNode",
    "ApiKeyCredential",
    "BaseNode",
    "BasicAuthCredential",
    "BearerTokenCredential",
    "CredentialMountType",
    "CredentialReference",
    "ExecutionContext",
    "StandardOutputWrapper",
    "TaskNode",
    "TriggerNode",
    "WorkflowNode",
    "compile_manifest",
    "compile_manifest_data",
    "load_manifest",
    "validate_manifest",
]
