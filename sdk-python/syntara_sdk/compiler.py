"""Manifest compiler for the Syntara Node SDK.

Provides functions to:
1. Load and validate manifest.yaml files against the platform schema
2. Compile manifests into registry-ready descriptors
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator

# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def load_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Load a manifest.yaml file and return parsed dict.

    Args:
        manifest_path: Path to manifest.yaml file

    Returns:
        Parsed manifest dictionary

    Raises:
        FileNotFoundError: If manifest file doesn't exist
        yaml.YAMLError: If manifest is invalid YAML
    """
    path = Path(manifest_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    with path.open() as f:
        return yaml.safe_load(f)


def load_common_definitions(schemas_root: Path | None = None) -> dict[str, Any]:
    """Load the platform's common-definitions.json schema.

    Args:
        schemas_root: Path to schemas directory (auto-detected if None)

    Returns:
        Parsed schema dictionary
    """
    if schemas_root is None:
        # Try to find schemas directory relative to this file
        sdk_root = Path(__file__).parent.parent.parent
        schemas_root = sdk_root / "schemas"

    schema_path = Path(schemas_root) / "common-definitions.json"
    if not schema_path.exists():
        raise FileNotFoundError(
            f"common-definitions.json not found at {schema_path}. "
            f"Pass schemas_root parameter or ensure repository structure is correct."
        )

    with schema_path.open() as f:
        return json.load(f)


def build_validator(schemas_root: Path | None = None) -> Draft7Validator:
    """Build a JSON Schema validator for NodeTypeManifest.

    The validator enforces the K8s CRD structure (apiVersion, kind, metadata, spec)
    and references shared platform types via $ref.

    Args:
        schemas_root: Path to schemas directory (auto-detected if None)

    Returns:
        Draft7Validator configured for manifest validation
    """
    common = load_common_definitions(schemas_root)

    # Use the NodeTypeManifest schema from common-definitions.json
    node_schema: dict[str, Any] = {"$ref": "common-definitions.json#/definitions/NodeTypeManifest"}

    # jsonschema >= 4.18 uses the `referencing` library; fall back to legacy
    # RefResolver on older installs for portability
    try:
        from referencing import Registry, Resource

        registry = Registry().with_resources(
            [
                ("common-definitions.json", Resource.from_contents(common)),
                (common["$id"], Resource.from_contents(common)),
            ]
        )
        return Draft7Validator(node_schema, registry=registry)
    except ImportError:  # pragma: no cover - legacy jsonschema
        from jsonschema import RefResolver

        resolver = RefResolver(
            base_uri="",
            referrer=node_schema,
            store={"common-definitions.json": common, common["$id"]: common},
        )
        return Draft7Validator(node_schema, resolver=resolver)


def validate_manifest(
    manifest: dict[str, Any],
    schemas_root: Path | None = None,
) -> list[str]:
    """Validate a manifest against the platform schema.

    Args:
        manifest: Parsed manifest dictionary
        schemas_root: Path to schemas directory (auto-detected if None)

    Returns:
        List of validation error messages (empty if valid)
    """
    validator = build_validator(schemas_root)
    errors = sorted(validator.iter_errors(manifest), key=lambda e: list(e.path))
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors]


def compile_manifest_data(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate and compile an already-parsed manifest mapping."""

    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("Manifest validation failed:\n" + "\n".join(errors))
    return manifest


def compile_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Compile manifest.yaml into a database-ready descriptor.

    The K8s CRD structure (apiVersion, kind, metadata, spec) is preserved
    in the compiled output and stored directly in PostgreSQL JSONB.

    Args:
        manifest_path: Path to manifest.yaml file

    Returns:
        Compiled manifest descriptor (K8s CRD structure preserved)

    Raises:
        FileNotFoundError: If manifest file doesn't exist
        ValueError: If manifest fails validation
    """
    # Load manifest
    manifest = load_manifest(manifest_path)

    return compile_manifest_data(manifest)
