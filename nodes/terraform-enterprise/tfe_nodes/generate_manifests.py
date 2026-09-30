"""Generate checked-in descriptors from the same models used at runtime."""

import argparse
from pathlib import Path

import yaml
from syntara_sdk.compiler import compile_manifest_data

from .catalog import OPERATIONS
from .models import TFEResult

DEFAULT_IMAGE = "localhost:5000/syntara/tfe-executor:0.1.0"
MANIFEST_ROOT = Path(__file__).resolve().parents[1] / "manifests"


def manifest_for(name: str, image: str = DEFAULT_IMAGE) -> dict:
    operation = OPERATIONS[name]
    descriptor = {
        "apiVersion": "syntara.io/v1alpha1",
        "kind": "NodeType",
        "metadata": {
            "name": "tfe_" + name,
            "displayName": "TFE: " + operation.title,
            "version": "0.1.0",
            "icon": "cloud",
            "description": operation.title + " through the Terraform Enterprise API.",
            "tags": [
                "integration:terraform-enterprise",
                "category:action",
                "domain:" + operation.domain,
            ],
            "license": "Apache-2.0",
        },
        "spec": {
            "category": "action",
            "execution": {
                "type": "container",
                "image": image,
                "entrypoint": "python -m tfe_nodes.runner " + name,
            },
            "declaredRequirements": {
                "capabilities": ["network-egress", "readonly-root-filesystem"],
                "credentialTypes": ["bearer_token"],
            },
            "credentialSpecification": {"workloadClassification": "action"},
            "inputs": operation.model.model_json_schema(),
            "outputs": {
                "allOf": [
                    {
                        "$ref": "../../../schemas/common-definitions.json#/definitions/StandardOutputWrapper"
                    },
                    {
                        "type": "object",
                        "properties": {
                            "Result": {"anyOf": [TFEResult.model_json_schema(), {"type": "null"}]}
                        },
                    },
                ]
            },
            "executionTimeout": 900,
            "resourceRequirements": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            },
        },
    }
    return compile_manifest_data(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    args = parser.parse_args()
    MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)
    for name in OPERATIONS:
        (MANIFEST_ROOT / (name + ".yaml")).write_text(
            yaml.safe_dump(manifest_for(name, args.image), sort_keys=False)
        )


if __name__ == "__main__":
    main()
