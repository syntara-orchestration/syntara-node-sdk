"""Language-agnostic tooling for building and publishing Syntara steps."""

__version__ = "0.1.0"

from syntara_tools.compiler import (
    PluginDescriptor,
    PluginDiscoveryError,
    StepDescriptor,
    canonical_step_identity,
    compile_manifest,
    compile_manifest_data,
    discover_plugin,
    load_manifest,
    load_plugin_manifest,
    validate_manifest,
    validate_plugin_manifest,
)
from syntara_tools.oci_client import (
    OCI_ARTIFACT_TYPE,
    OCI_CONFIG_MEDIA_TYPE,
    OCI_PLUGIN_MANIFEST_MEDIA_TYPE,
    OCIRegistryClient,
    OCIRegistryError,
)

__all__ = [
    "OCI_ARTIFACT_TYPE",
    "OCI_CONFIG_MEDIA_TYPE",
    "OCI_PLUGIN_MANIFEST_MEDIA_TYPE",
    "OCIRegistryClient",
    "OCIRegistryError",
    "PluginDescriptor",
    "PluginDiscoveryError",
    "StepDescriptor",
    "canonical_step_identity",
    "compile_manifest",
    "compile_manifest_data",
    "discover_plugin",
    "load_manifest",
    "load_plugin_manifest",
    "validate_manifest",
    "validate_plugin_manifest",
]
