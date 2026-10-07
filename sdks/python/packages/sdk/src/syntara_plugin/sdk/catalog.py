"""Deterministic, offline OCI assembly for signed Syntara catalog indexes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
