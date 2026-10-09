"""Deterministic, offline OCI assembly for signed Syntara catalog indexes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping, cast

from syntara_plugin.contracts import (
    CatalogCheckpoint,
    load_bundle,
    validate_catalog_index,
    validate_document,
)

from .oci import OCI_IMAGE_MANIFEST_MEDIA_TYPE, OciBlob, canonical_json_bytes


OCI_CATALOG_INDEX_ARTIFACT_TYPE = "application/vnd.syntara.catalog-index.v1"
OCI_CATALOG_INDEX_CONFIG_MEDIA_TYPE = "application/vnd.syntara.catalog-index.config.v1+json"
OCI_CATALOG_INDEX_CONTENT_MEDIA_TYPE = "application/vnd.syntara.catalog-index.content.v1+json"


class CatalogIndexArtifactBuildError(ValueError):
    """Raised when a catalog index cannot safely form a deterministic OCI artifact."""


class CatalogIndexUpdateError(ValueError):
    """Raised when a new catalog entry cannot safely extend a prior index."""


@dataclass(frozen=True)
class CatalogIndexArtifact:
    """Offline OCI catalog-index artifact ready for a later signing or registry adapter."""

    config: OciBlob
    catalog_index: OciBlob
    manifest: OciBlob

    @property
    def digest(self) -> str:
        """Return the immutable manifest digest to sign and publish."""

        return self.manifest.descriptor.digest

    @property
    def blobs(self) -> Mapping[str, OciBlob]:
        """Return every uploadable blob indexed by its verified digest."""

        return {
            blob.descriptor.digest: blob
            for blob in (self.config, self.catalog_index, self.manifest)
        }


def build_catalog_index_artifact(index: Mapping[str, Any]) -> CatalogIndexArtifact:
    """Build a deterministic OCI artifact from one valid `CatalogIndex` document.

    This function validates the source document and its internal catalog
    invariants, but intentionally performs no registry I/O, signing, policy,
    or freshness check against a persisted source checkpoint. Those mutable
    operations belong to the publication and Syntara reconciliation adapters.
    """

    bundle = load_bundle()
    schema_errors = validate_document(bundle, "catalog_index", index)
    if schema_errors:
        raise CatalogIndexArtifactBuildError("; ".join(schema_errors))

    metadata = _mapping(index["metadata"], "metadata")
    specification = _mapping(index["spec"], "spec")
    issued_at = _parse_issued_at(metadata["issuedAt"])
    source_id = _string(metadata["sourceId"], "metadata/sourceId")
    diagnostics = validate_catalog_index(
        bundle,
        index,
        source_id=source_id,
        now=issued_at,
        checkpoint=CatalogCheckpoint(),
    )
    if diagnostics:
        raise CatalogIndexArtifactBuildError("; ".join(item.code for item in diagnostics))

    entries = specification["entries"]
    if not isinstance(
        entries, list
    ):  # Covered by schema validation; keeps the type boundary explicit.
        raise CatalogIndexArtifactBuildError("spec/entries must be an array")
    generation = metadata["generation"]
    if not isinstance(generation, int) or isinstance(generation, bool):
        raise CatalogIndexArtifactBuildError("metadata/generation must be an integer")

    catalog_index = OciBlob.create(
        canonical_json_bytes(index),
        OCI_CATALOG_INDEX_CONTENT_MEDIA_TYPE,
        annotations={"org.opencontainers.image.title": "catalog-index.json"},
    )
    config = OciBlob.create(
        canonical_json_bytes(
            {
                "apiVersion": "syntara.catalog-index.config/v1alpha1",
                "kind": "CatalogIndexArtifactConfig",
                "catalogIndexDigest": catalog_index.descriptor.digest,
                "contractBundleDigest": bundle.digest,
                "entryCount": len(entries),
                "generation": generation,
                "sourceId": source_id,
            }
        ),
        OCI_CATALOG_INDEX_CONFIG_MEDIA_TYPE,
    )
    manifest = OciBlob.create(
        canonical_json_bytes(
            {
                "schemaVersion": 2,
                "mediaType": OCI_IMAGE_MANIFEST_MEDIA_TYPE,
                "artifactType": OCI_CATALOG_INDEX_ARTIFACT_TYPE,
                "config": config.descriptor.as_dict(),
                "layers": [catalog_index.descriptor.as_dict()],
                "annotations": {
                    "org.opencontainers.image.title": f"catalog-index/{source_id}",
                    "org.opencontainers.image.version": str(generation),
                },
            }
        ),
        OCI_IMAGE_MANIFEST_MEDIA_TYPE,
    )
    return CatalogIndexArtifact(config=config, catalog_index=catalog_index, manifest=manifest)


def merge_catalog_entry(
    *,
    current: Mapping[str, Any] | None,
    current_manifest_digest: str | None,
    entry: Mapping[str, Any],
    source_id: str,
    issued_at: datetime,
    expires_at: datetime,
) -> tuple[dict[str, Any], bool]:
    """Create the next immutable index document for one new plugin release.

    A catalog version is an append-only release ledger: an entry whose
    ``namespace``, ``name``, and ``version`` already exists must be identical
    to be considered an idempotent retry.  A conflicting re-publication is
    rejected rather than silently redirecting an already released version to
    different artifact bytes.
    """

    if issued_at.tzinfo is None or expires_at.tzinfo is None or expires_at <= issued_at:
        raise CatalogIndexUpdateError("catalog timestamps must be timezone-aware and increasing")
    if not source_id:
        raise CatalogIndexUpdateError("catalog source_id must be non-empty")
    candidate = dict(entry)
    identity = _entry_identity(candidate)
    if current is None:
        if current_manifest_digest is not None:
            raise CatalogIndexUpdateError("a missing catalog cannot have a previous manifest digest")
        entries = [candidate]
        generation = 1
        previous_digest: str | None = None
    else:
        if current_manifest_digest is None:
            raise CatalogIndexUpdateError("an existing catalog requires its immutable manifest digest")
        metadata = _mapping(current.get("metadata"), "current metadata")
        specification = _mapping(current.get("spec"), "current spec")
        if metadata.get("sourceId") != source_id:
            raise CatalogIndexUpdateError("existing catalog sourceId does not match the requested source")
        generation = metadata.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise CatalogIndexUpdateError("existing catalog generation must be a positive integer")
        raw_entries = specification.get("entries")
        if not isinstance(raw_entries, list):
            raise CatalogIndexUpdateError("existing catalog entries must be an array")
        entries = []
        for index, existing in enumerate(raw_entries):
            existing_entry = dict(_mapping(existing, f"current spec.entries[{index}]"))
            if _entry_identity(existing_entry) == identity:
                if existing_entry == candidate:
                    return dict(current), True
                raise CatalogIndexUpdateError(
                    "catalog already contains a different artifact for "
                    f"{identity[0]}/{identity[1]}:{identity[2]}; publish a new plugin version"
                )
            entries.append(existing_entry)
        entries.append(candidate)
        generation += 1
        previous_digest = current_manifest_digest

    document: dict[str, Any] = {
        "apiVersion": "syntara.io/v1alpha1",
        "kind": "CatalogIndex",
        "metadata": {
            "sourceId": source_id,
            "generation": generation,
            "issuedAt": _rfc3339(issued_at),
            "expiresAt": _rfc3339(expires_at),
        },
        "spec": {
            "contractVersion": "syntara.io/v1alpha1",
            "entries": sorted(entries, key=_entry_identity),
        },
    }
    if previous_digest is not None:
        document["metadata"]["previousIndexDigest"] = previous_digest
    return document, False


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CatalogIndexArtifactBuildError(f"{path} must be an object")
    return cast("Mapping[str, Any]", value)


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise CatalogIndexArtifactBuildError(f"{path} must be a string")
    return value


def _parse_issued_at(value: object) -> datetime:
    timestamp = _string(value, "metadata/issuedAt")
    try:
        return datetime.fromisoformat(
            timestamp.removesuffix("Z") + "+00:00" if timestamp.endswith("Z") else timestamp
        )
    except ValueError as error:
        raise CatalogIndexArtifactBuildError("metadata/issuedAt must be RFC 3339") from error


def _entry_identity(entry: Mapping[str, Any]) -> tuple[str, str, str]:
    try:
        namespace = _string(entry["namespace"], "catalog entry namespace")
        name = _string(entry["name"], "catalog entry name")
        version = _string(entry["version"], "catalog entry version")
    except KeyError as error:
        raise CatalogIndexUpdateError(f"catalog entry is missing {error.args[0]!r}") from error
    return namespace, name, version


def _rfc3339(value: datetime) -> str:
    """Normalize authoring timestamps to the canonical UTC wire form."""

    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
