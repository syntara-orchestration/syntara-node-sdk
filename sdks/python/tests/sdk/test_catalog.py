from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from syntara_plugin.sdk import (
    OCI_CATALOG_INDEX_ARTIFACT_TYPE,
    OCI_CATALOG_INDEX_CONFIG_MEDIA_TYPE,
    OCI_CATALOG_INDEX_CONTENT_MEDIA_TYPE,
    OCI_IMAGE_MANIFEST_MEDIA_TYPE,
    CatalogIndexArtifactBuildError,
    build_catalog_index_artifact,
)


def _index() -> dict[str, object]:
    return {
        "apiVersion": "syntara.io/v1alpha1",
        "kind": "CatalogIndex",
        "metadata": {
            "sourceId": "local-quay",
            "generation": 42,
            "issuedAt": "2026-10-06T12:00:00Z",
            "expiresAt": "2026-10-13T12:00:00Z",
            "previousIndexDigest": "sha256:" + "a" * 64,
        },
        "spec": {
            "contractVersion": "syntara.io/v1alpha1",
            "entries": [
                {
                    "namespace": "syntara",
                    "name": "github",
                    "version": "1.0.0",
                    "artifactRepository": "syntara/plugins/github",
                    "artifactDigest": "sha256:" + "1" * 64,
                    "documentationDigest": "sha256:" + "2" * 64,
                    "runtimeOwnership": "platform-runner",
                },
                {
                    "namespace": "syntara",
                    "name": "aap",
                    "version": "1.0.0",
                    "artifactRepository": "syntara/plugins/aap",
                    "artifactDigest": "sha256:" + "3" * 64,
                    "documentationDigest": "sha256:" + "4" * 64,
                    "runtimeOwnership": "custom-workload",
                },
            ],
        },
    }


def test_catalog_index_artifact_is_deterministic_and_has_a_complete_oci_envelope() -> None:
    index = _index()

    first = build_catalog_index_artifact(index)
    second = build_catalog_index_artifact(deepcopy(index))

    assert first.digest == second.digest
    assert first.manifest.content == second.manifest.content
    assert first.catalog_index.content == second.catalog_index.content
    assert first.blobs == {
        first.config.descriptor.digest: first.config,
        first.catalog_index.descriptor.digest: first.catalog_index,
        first.manifest.descriptor.digest: first.manifest,
    }

    manifest = json.loads(first.manifest.content)
    assert manifest == {
        "annotations": {
            "org.opencontainers.image.title": "catalog-index/local-quay",
            "org.opencontainers.image.version": "42",
        },
        "artifactType": OCI_CATALOG_INDEX_ARTIFACT_TYPE,
        "config": first.config.descriptor.as_dict(),
        "layers": [first.catalog_index.descriptor.as_dict()],
        "mediaType": OCI_IMAGE_MANIFEST_MEDIA_TYPE,
        "schemaVersion": 2,
    }
    assert first.config.descriptor.media_type == OCI_CATALOG_INDEX_CONFIG_MEDIA_TYPE
    assert first.catalog_index.descriptor.media_type == OCI_CATALOG_INDEX_CONTENT_MEDIA_TYPE
    assert json.loads(first.catalog_index.content) == index

    config = json.loads(first.config.content)
    assert config["catalogIndexDigest"] == first.catalog_index.descriptor.digest
    assert config["entryCount"] == 2
    assert config["generation"] == 42
    assert config["sourceId"] == "local-quay"
    assert first.catalog_index.descriptor.digest == (
        "sha256:" + sha256(first.catalog_index.content).hexdigest()
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda document: document["spec"].update({"entries": []}),
            "spec/entries",
        ),
        (
            lambda document: document["spec"].update(
                {"entries": [document["spec"]["entries"][0]] * 2}
            ),
            "CATALOG_ENTRY_IDENTITY_DUPLICATE",
        ),
        (
            lambda document: document["metadata"].update(
                {"expiresAt": document["metadata"]["issuedAt"]}
            ),
            "CATALOG_INDEX_TIME_WINDOW_INVALID",
        ),
    ],
)
def test_catalog_index_artifact_rejects_invalid_catalogs(mutate, message: str) -> None:
    index = _index()
    mutate(index)

    with pytest.raises(CatalogIndexArtifactBuildError, match=message):
        build_catalog_index_artifact(index)
