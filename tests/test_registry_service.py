from pathlib import Path

import pytest
import yaml
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine
from syntara_tools.compiler import load_manifest

from tests.registry.models import RegistryBase
from tests.registry.service import (
    OCI_ARTIFACT_TYPE,
    OCI_MANIFEST_ANNOTATION,
    RegistryService,
    validate_oci_manifest,
)

TESTS_DIR = Path(__file__).resolve().parent


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    RegistryBase.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    RegistryBase.metadata.drop_all(engine)


def test_register_manifest_persists_dispatch_columns(session: Session) -> None:
    manifest = load_manifest(TESTS_DIR / "fixtures" / "steps" / "subworkflow_trigger" / "manifest.yaml")
    row = RegistryService(session).register_manifest(manifest)

    assert row.category == "trigger"
    assert row.image_ref is None
    assert row.descriptor["spec"]["execution"]["image"] is None


def test_register_manifest_payload_accepts_raw_yaml(session: Session) -> None:
    manifest_path = TESTS_DIR / "fixtures" / "steps" / "subworkflow_trigger" / "manifest.yaml"
    row = RegistryService(session).register_manifest_payload(manifest_path.read_bytes())
    assert row.name == "subworkflow_trigger"


def test_oci_registration_reads_standard_artifact_annotation(session: Session) -> None:
    manifest = load_manifest(TESTS_DIR / "fixtures" / "steps" / "script_executor" / "manifest.yaml")
    oci_manifest = {
        "artifactType": OCI_ARTIFACT_TYPE,
        "annotations": {OCI_MANIFEST_ANNOTATION: yaml.safe_dump(manifest)},
    }

    row = RegistryService(session).register_oci_manifest(
        "quay.io/example/script:1.0.0", oci_manifest
    )
    assert row.category == "task"
    assert row.image_ref == "quay.io/example/script:1.0.0"


def test_oci_validation_rejects_wrong_artifact_type() -> None:
    assert validate_oci_manifest({"artifactType": "application/octet-stream"})


def test_oci_registration_rejects_non_step_artifact(session: Session) -> None:
    with pytest.raises(ValueError, match="not a step manifest"):
        RegistryService(session).register_oci_manifest(
            "quay.io/example/other:1.0.0",
            {"artifactType": "application/octet-stream", "annotations": {}},
        )
