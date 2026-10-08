"""Validation and discovery for step and root plugin manifests.

The SDK validates source contracts and returns descriptors. It intentionally does
not choose how a platform persists or indexes those descriptors.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Literal, cast
from urllib.parse import urlparse

import yaml
from jsonschema import Draft7Validator  # type: ignore[import-untyped]

ManifestKind = Literal["StepTypeManifest", "PluginManifest"]


@dataclass(frozen=True)
class StepDescriptor:
    """A validated step discovered from a root plugin manifest."""

    target: Path
    manifest: dict[str, Any]
    identity: str
    content_digest: str

    def indexed_data(self) -> dict[str, Any]:
        """Return the stable data consumers index for this discovered step.

        This deliberately excludes the source target. Moving an unchanged
        manifest within a plugin must not change the content address exposed
        to a registry or catalog.
        """
        return {
            "identity": self.identity,
            "manifest": self.manifest,
            "contentDigest": self.content_digest,
        }


@dataclass(frozen=True)
class PluginDescriptor:
    """A validated plugin and its ordered, validated step descriptors."""

    root: Path
    manifest: dict[str, Any]
    steps: tuple[StepDescriptor, ...]


class PluginDiscoveryError(ValueError):
    """Raised when a root plugin manifest or one of its targets is invalid."""


def _load_yaml_mapping(path: Path, resource_name: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{resource_name} not found: {path}")
    if not path.is_file():
        raise ValueError(f"{resource_name} is not a file: {path}")
    with path.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream)
    if not isinstance(document, dict):
        raise ValueError(f"{resource_name} must contain a YAML mapping: {path}")
    return document


def load_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Load a standalone StepType manifest mapping.

    This public API retains its existing name and behaviour for valid step
    manifests while producing a clear error for non-mapping YAML documents.
    """
    return _load_yaml_mapping(Path(manifest_path).resolve(), "Manifest")


def load_plugin_manifest(plugin_path: str | Path) -> dict[str, Any]:
    """Load a root ``plugin.yaml`` mapping without discovering its targets."""
    return _load_yaml_mapping(Path(plugin_path).resolve(), "Plugin manifest")


def load_common_definitions(schemas_root: Path | None = None) -> dict[str, Any]:
    """Load the SDK's shared Draft-07 schema definitions."""
    if schemas_root is None:
        source_schemas = Path(__file__).parent.parent.parent / "schemas"
        packaged_schemas = Path(__file__).parent / "schemas"
        schemas_root = source_schemas if source_schemas.exists() else packaged_schemas
    schema_path = Path(schemas_root) / "common-definitions.json"
    if not schema_path.exists():
        raise FileNotFoundError(
            f"common-definitions.json not found at {schema_path}. "
            "Pass schemas_root or preserve the SDK repository layout."
        )
    with schema_path.open(encoding="utf-8") as stream:
        return cast("dict[str, Any]", json.load(stream))


def build_validator(
    schemas_root: Path | None = None,
    manifest_kind: ManifestKind = "StepTypeManifest",
) -> Draft7Validator:
    """Build a validator for a StepType or Plugin manifest.

    Calling this with no arguments remains the public standalone-step API.
    """
    common = load_common_definitions(schemas_root)
    schema: dict[str, Any] = {"$ref": f"common-definitions.json#/definitions/{manifest_kind}"}
    try:
        from referencing import Registry, Resource

        registry = Registry().with_resources(
            [
                ("common-definitions.json", Resource.from_contents(common)),
                (common["$id"], Resource.from_contents(common)),
            ]
        )
        return Draft7Validator(schema, registry=registry)
    except ImportError:  # pragma: no cover - legacy jsonschema
        from jsonschema import RefResolver

        resolver = RefResolver(
            base_uri="",
            referrer=schema,
            store={"common-definitions.json": common, common["$id"]: common},
        )
        return Draft7Validator(schema, resolver=resolver)


def _validation_errors(validator: Draft7Validator, manifest: dict[str, Any]) -> list[str]:
    errors = sorted(validator.iter_errors(manifest), key=lambda error: list(error.path))
    return [f"{'/'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors]


def validate_manifest(manifest: dict[str, Any], schemas_root: Path | None = None) -> list[str]:
    """Validate one standalone StepType manifest and return error messages."""
    return _validation_errors(build_validator(schemas_root), manifest)


def validate_plugin_manifest(
    manifest: dict[str, Any], schemas_root: Path | None = None
) -> list[str]:
    """Validate one root Plugin manifest without loading its target files."""
    return _validation_errors(build_validator(schemas_root, "PluginManifest"), manifest)


def canonical_step_identity(plugin_namespace: str, plugin_name: str, step_name: str) -> str:
    """Return the source-contract identity for a step in a plugin."""
    return f"{plugin_namespace}/{plugin_name}/{step_name}"


def _step_content_digest(identity: str, manifest: dict[str, Any]) -> str:
    """Hash the canonical compiled/indexed representation of one step.

    The digest is derived after YAML parsing and validation, rather than from
    authored bytes, so comments, key ordering, and YAML formatting cannot
    affect it. It is intentionally not written back into source manifests.
    """
    indexed = {"identity": identity, "manifest": manifest}
    canonical = json.dumps(indexed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_plugin_metadata_payload(payload: object, schemas_root: Path | None = None) -> list[str]:
    """Validate the self-contained plugin metadata carried in an OCI layer.

    The payload is intentionally validated without reading the authoring tree:
    an OCI consumer has only the embedded root manifest and compiled step
    descriptors.  Each descriptor must therefore be internally consistent
    with the root identity and with the deterministic digest used at publish
    time.
    """
    if not isinstance(payload, dict):
        return ["plugin metadata payload must be a mapping"]
    plugin = payload.get("plugin")
    steps = payload.get("steps")
    if not isinstance(plugin, dict):
        return ["plugin metadata payload.plugin must be a mapping"]
    if not isinstance(steps, list):
        return ["plugin metadata payload.steps must be a list"]

    errors = [f"plugin: {error}" for error in validate_plugin_manifest(plugin, schemas_root)]
    if errors:
        return errors
    targets = plugin["spec"]["targets"]
    if len(steps) != len(targets):
        errors.append("steps must contain exactly one descriptor for every plugin target")

    metadata = plugin["metadata"]
    identities: set[str] = set()
    for index, descriptor in enumerate(steps):
        prefix = f"steps/{index}"
        if not isinstance(descriptor, dict):
            errors.append(f"{prefix}: descriptor must be a mapping")
            continue
        manifest = descriptor.get("manifest")
        identity = descriptor.get("identity")
        content_digest = descriptor.get("contentDigest")
        if not isinstance(manifest, dict):
            errors.append(f"{prefix}/manifest: must be a mapping")
            continue
        errors.extend(f"{prefix}/manifest: {error}" for error in validate_manifest(manifest, schemas_root))
        if not isinstance(identity, str):
            errors.append(f"{prefix}/identity: must be a string")
            continue
        if not isinstance(content_digest, str):
            errors.append(f"{prefix}/contentDigest: must be a string")
            continue
        if identity in identities:
            errors.append(f"{prefix}/identity: duplicate identity {identity!r}")
        identities.add(identity)
        if isinstance(manifest.get("metadata"), dict) and isinstance(manifest["metadata"].get("name"), str):
            expected_identity = canonical_step_identity(
                metadata["namespace"], metadata["name"], manifest["metadata"]["name"]
            )
            if identity != expected_identity:
                errors.append(f"{prefix}/identity: does not match plugin and step metadata")
            if content_digest != _step_content_digest(identity, manifest):
                errors.append(f"{prefix}/contentDigest: does not match identity and manifest")
    return errors


def _inventory_image(repository: str, digest: str) -> str:
    return f"{repository}@{digest}"


def _target_path(plugin_root: Path, target: str) -> Path:
    parsed = urlparse(target)
    raw_path = Path(target)
    windows_path = PureWindowsPath(target)
    if parsed.scheme or "://" in target:
        raise PluginDiscoveryError(f"target {target!r}: URLs are not supported")
    if raw_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise PluginDiscoveryError(f"target {target!r}: absolute paths are not supported")
    if any(part == ".." for part in raw_path.parts):
        raise PluginDiscoveryError(f"target {target!r}: path traversal is not supported")

    resolved = (plugin_root / raw_path).resolve()
    if resolved != plugin_root and plugin_root not in resolved.parents:
        raise PluginDiscoveryError(f"target {target!r}: resolves outside the plugin root")
    return resolved


def discover_plugin(plugin_path: str | Path, schemas_root: Path | None = None) -> PluginDescriptor:
    """Load, validate, and explicitly discover every step named by ``plugin.yaml``.

    Targets are resolved from the root manifest's directory in listed order. No
    directory scanning occurs; the explicit target list is authoritative.
    """
    plugin_file = Path(plugin_path).resolve()
    plugin_root = plugin_file.parent
    try:
        plugin = load_plugin_manifest(plugin_file)
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        raise PluginDiscoveryError(str(exc)) from exc

    errors = validate_plugin_manifest(plugin, schemas_root)
    if errors:
        raise PluginDiscoveryError("Plugin validation failed:\n" + "\n".join(errors))

    metadata = plugin["metadata"]
    steps: list[StepDescriptor] = []
    names: set[str] = set()
    used_images: set[str] = set()
    inventory = {
        _inventory_image(image["repository"], image["digest"])
        for image in plugin["spec"]["images"]
    }
    if len(inventory) != len(plugin["spec"]["images"]):
        raise PluginDiscoveryError("Plugin image inventory contains duplicate repository and digest entries")
    for target in plugin["spec"]["targets"]:
        assert isinstance(target, str)
        try:
            target_path = _target_path(plugin_root, target)
            if not target_path.exists():
                raise PluginDiscoveryError(f"target {target!r}: file does not exist")
            if not target_path.is_file():
                raise PluginDiscoveryError(f"target {target!r}: expected a file, found a directory")
            step = _load_yaml_mapping(target_path, f"target {target!r}")
        except (OSError, ValueError, yaml.YAMLError) as exc:
            message = str(exc)
            if message.startswith("target "):
                raise PluginDiscoveryError(message) from exc
            raise PluginDiscoveryError(f"target {target!r}: {message}") from exc

        if step.get("kind") != "StepType":
            raise PluginDiscoveryError(f"target {target!r}: kind must be StepType")
        step_errors = validate_manifest(step, schemas_root)
        if step_errors:
            raise PluginDiscoveryError(
                f"target {target!r}: step validation failed:\n" + "\n".join(step_errors)
            )
        step_metadata = step["metadata"]
        step_name = step_metadata["name"]
        if step_name in names:
            raise PluginDiscoveryError(f"target {target!r}: duplicate step metadata/name {step_name!r}")
        names.add(step_name)
        image = step["spec"]["execution"]["image"]
        if image not in inventory:
            raise PluginDiscoveryError(
                f"target {target!r}: execution image {image!r} is not in the plugin image inventory"
            )
        used_images.add(image)
        identity = canonical_step_identity(metadata["namespace"], metadata["name"], step_name)
        steps.append(
            StepDescriptor(
                target=target_path,
                manifest=step,
                identity=identity,
                content_digest=_step_content_digest(identity, step),
            )
        )
    unused_images = inventory - used_images
    if unused_images:
        raise PluginDiscoveryError(
            "Plugin image inventory contains entries not referenced by targeted steps: "
            + ", ".join(sorted(unused_images))
        )
    return PluginDescriptor(root=plugin_root, manifest=plugin, steps=tuple(steps))


def compile_manifest_data(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate and return an already-parsed standalone step manifest."""
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("Manifest validation failed:\n" + "\n".join(errors))
    return manifest


def compile_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Compile a standalone StepType manifest into its validated source descriptor."""
    return compile_manifest_data(load_manifest(manifest_path))
