# Syntara Node SDK

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL 15+](https://img.shields.io/badge/postgresql-15+-blue.svg)](https://www.postgresql.org/)

A schema-driven framework for authoring, packaging, and registering custom automation nodes for workflow orchestration. Build type-safe, composable automation nodes with declarative YAML manifests that compile to runtime-ready JSON definitions.

## Features

- **🎯 Type-Safe Authoring** — Author nodes in human-friendly YAML with JSON Schema validation (Draft-07)
- **🔒 Zero-Trust Security** — Credential references only; sensitive values are separated into the transient stdin `credentials` map, with runtime injection and persistence safeguards owned by the execution plane
- **📦 Four-Category Taxonomy** — `action` (integrations), `task` (compute), `workflow` (control flow), `trigger` (events)
- **⚡ Fast Canvas Rendering** — Compiled node definitions enable <500ms dynamic form rendering
- **🔌 Kubernetes-Native** — Follows K8s CRD conventions (`apiVersion`, `kind`, `metadata`, `spec`)
- **🛡️ Declarative Permissions** — Static capability inspection before execution-plane dispatch
- **🔄 Backwards Compatible** — Immutable output envelope (`StandardOutputWrapper`) ensures stable template expressions

## Quick Start

### Installation

```bash
# Install the Python SDK
pip install -e ./sdk-python

# Or install from the repository root
pip install -e .
```

### Scaffold and Package Nodes

Use the CLI to create a shared-runner script node or a dedicated-image node:

```bash
syntara-cli init normalize_payload --tier 2  # shared-runner script node
syntara-cli init customer_lookup --tier 3 --image quay.io/example/customer-lookup:1.0.0  # dedicated container extension
syntara-cli build customer_lookup/manifest.yaml --output customer-lookup-oci

# Local prototype: publish to OCI, then register in Syntara automatically
syntara-cli push customer_lookup/manifest.yaml \
  --registry localhost:5000/syntara/nodes/customer-lookup:1.0.0
```

Dedicated container-extension builds emit a standard OCI image manifest with artifact type
`application/vnd.syntara.node.manifest.v1+yaml` and the validated YAML manifest
in the `org.syntara.node.manifest` annotation.

`push` publishes the OCI metadata and then calls
`POST /api/v1/node-types` to add the node to Syntara's available-node catalog.
Use `--skip-register` for registry-only publishing or `--api-url` to target a
different Syntara instance.

### Create Your First Node

**1. Copy the manifest template:**

```bash
# Use the canonical template as a starting point
cp manifest.yaml nodes/my-http-node/manifest.yaml
cd nodes/my-http-node
```

**2. Edit `manifest.yaml` (K8s CRD structure):**

```yaml
apiVersion: syntara.io/v1alpha1
kind: NodeType

metadata:
  name: my_http_node
  displayName: My HTTP Node
  version: 1.0.0
  icon: globe
  description: Custom HTTP request node with retry logic
  tags:
    - integration:rest-api
    - network:external
  license: Apache-2.0

spec:
  category: action
  execution:
    type: container
    image: registry.example.com/nodes/my-http-node:1.0.0

  declaredRequirements:
    capabilities:
      - network-egress
      - readonly-root-filesystem
    platformVersion: ">=3.0.0"

  schedulingControls:
    connectivity_requirements:
      - host: api.github.com
        ports:
          - port: 443
            protocol: TCP

  inputs:
    properties:
      url:
        type: string
        description: Target URL
      method:
        type: string
        enum: [GET, POST, PUT, DELETE]
        default: GET
    required:
      - url

  outputs:
    allOf:
      - $ref: "../../schemas/common-definitions.json#/definitions/StandardOutputWrapper"

  resourceRequirements:
    limits:
      cpu: 500m
      memory: 256Mi
    requests:
      cpu: 100m
      memory: 128Mi

  executionTimeout: 60
```

### Validate & Test

**Validate manifest using SDK:**

```python
from syntara_sdk.compiler import compile_manifest, validate_manifest

# Validate only
manifest = {"apiVersion": "syntara.io/v1alpha1", ...}
errors = validate_manifest(manifest)
if errors:
    print("Validation errors:", errors)

# Compile (validates + prepares for database)
descriptor = compile_manifest("nodes/my-http-node/manifest.yaml")
print(f"✓ Compiled: {descriptor['metadata']['name']}")
```

**Test your node locally:**

```bash
# Run the SDK runner
PYTHONPATH="nodes/my-http-node:$PYTHONPATH" \
  python -m syntara_sdk.runner \
  --module src.main \
  --class MyNode \
  --inputs-file test_inputs.json
```

### Publish and Register

The OCI registry is the artifact source, and Syntara PostgreSQL is hydrated by
the registration API. The CLI publishes the OCI manifest and then registers the
image with Syntara automatically:

```bash
syntara-cli push nodes/http-request/manifest.yaml \
  --registry localhost:5000/syntara/nodes/http-request:1.0.0 \
  --api-url http://localhost:5173
```

Use `--skip-register` when publishing to a registry without making the node
available in Syntara yet. An administrator or deployment process can then
register the existing image later by posting its `image_ref` to
`POST /api/v1/node-types`.

## Architecture

Syntara follows a **define-once, consume-everywhere** model:

```mermaid
graph LR
    AUTHOR["Author<br/>manifest.yaml"]
    VALIDATE["Validate<br/>(JSON Schema)"]
    BUILD["Build<br/>node-definition.json"]
    REGISTRY["Registry<br/>(PostgreSQL)"]
    CANVAS["Canvas<br/>(React UI)"]
    ORCHESTRATOR["Orchestrator<br/>(Workflow Engine)"]

    AUTHOR --> VALIDATE --> BUILD --> REGISTRY
    REGISTRY --> CANVAS
    REGISTRY --> ORCHESTRATOR
```

### Node Categories

| Category | Purpose | Execution | Examples |
|----------|---------|-----------|----------|
| **action** | External API integrations | `container` | HTTP requests, GitHub issues, Slack messages |
| **task** | Atomic compute operations | `container` | Script executor, data transformation |
| **workflow** | Control flow and composition logic | `in_process` | Loops, conditions, switches, subworkflow calls |
| **trigger** | Event entry points | `in_process` | Webhooks, schedules, subworkflow triggers |

### Execution Types

- **`in_process`** — Runs as a built-in workflow activity inside the orchestrator (zero pod overhead)
- **`container`** — Hands the node contract to the execution plane for isolated execution

## Examples

The SDK includes reference implementations for each node category:

| Example | Category | Location |
|---------|----------|----------|
| **HTTP Request** | action | [nodes/http-request/](nodes/http-request/) |
| **Script Executor** | task | [nodes/script-executor/](nodes/script-executor/) |
| **Subworkflow Call** | workflow | [nodes/subworkflow-call/](nodes/subworkflow-call/) |
| **Subworkflow Trigger** | trigger | [nodes/subworkflow-trigger/](nodes/subworkflow-trigger/) |

### Run Example Tests

```bash
# Registry platform tests (9 tests)
uv run pytest tests/registry/test_postgres_registry.py

# HTTP Request node unit tests (12 tests)
PYTHONPATH="nodes/http-request:$PYTHONPATH" \
  pytest tests/nodes/http-request/test_http_node.py -v

# Run node directly with CLI runner
cd nodes/http-request
PYTHONPATH=".:$PYTHONPATH" \
  python -m syntara_sdk.runner \
  --module src.main \
  --class HttpRequestNode \
  --inputs-file ../../tests/nodes/http-request/test_inputs.json
```

**Expected output:**

```
Registry: 9 passed, 0 skipped, 0 failed
Node tests: 12 passed in 0.07s
CLI runner: StatusCode 0, HTTP 200 OK
```

## Registry REST API

The node registry exposes a versioned REST API for node lifecycle management:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/v1/node-types` | Register a new node |
| `GET` | `/api/v1/node-types` | List nodes (supports filtering) |
| `GET` | `/api/v1/node-types/{id}` | Fetch node details |
| `GET` | `/api/v1/node-types/{id}/descriptor` | Get compiled definition for canvas |
| `PATCH` | `/api/v1/node-types/{id}` | Update node metadata |
| `DELETE` | `/api/v1/node-types/{id}` | Remove node from registry |

**Special Query Parameters:**

- `?view=palette` — Returns UI-optimized summaries for the drag-and-drop node palette
- `?category=action` — Filter by node category
- `?enabled=true` — Filter by enabled status

See [docs/architecture.md](docs/architecture.md) for complete API documentation.

## Security Model

### Zero-Trust Credentials

Node manifests and compiled descriptors store only abstract credential references, never credential values. Credential references are passed to the execution plane so resolved values can be carried separately from plain inputs in the transient stdin payload:

```yaml
spec:
  credentialSpecification:
    workloadClassification: action
    credential_references:
      - credential_id: 550e8400-e29b-41d4-a716-446655440000
        credential_mount_type: tmpfs_file
        credential_mount_path: /tmp/api-key
```

At dispatch time, the SDK contract separates sensitive input values from plain `inputs` and places the resolved values in the `credentials` map of the single JSON stdin invocation. The execution plane owns how those credentials are injected, logged, scrubbed, and persisted.

### Declarative Permissions

Every node declares its requirements upfront in the manifest:

```yaml
spec:
  declaredRequirements:
    capabilities:
      - network-egress        # Can make outbound HTTP requests
      - script-execution      # Can execute scripts
      - tmpfs-mount          # Needs ephemeral storage
    platformVersion: ">=3.0.0"

  schedulingControls:
    connectivity_requirements:
      - host: api.github.com
        ports:
          - port: 443
            protocol: TCP
```

Administrators can audit these requirements **before** execution-plane dispatch. The execution plane consumes the declarations together with registration policy to apply its runtime controls.

### Workload Classification

- **`action`** — Deterministic, scripted execution. May access infrastructure credentials (SSH keys, cloud API tokens)
- **`agentic`** — LLM-driven, non-deterministic execution. **Blocked from infrastructure credentials** to prevent prompt injection escalation

## Documentation

- **[Architecture Guide](docs/architecture.md)** — Complete technical specification
- **[Common Definitions](schemas/common-definitions.json)** — Platform meta-schema (JSON Schema Draft-07)
- **[HTTP Request Example](nodes/http-request/)** — Full `action` node reference implementation
- **[Script Executor Example](nodes/script-executor/)** — Full `task` node reference implementation
- **[Subworkflow Trigger Example](nodes/subworkflow-trigger/)** — Child-side `trigger` descriptor and Reference-mode eligibility contract
- **[Subworkflow Call Example](nodes/subworkflow-call/)** — Parent-side `workflow` node descriptor for Reference-mode child invocation

## Development

### Prerequisites

- **Python 3.12+**
- **PostgreSQL 15+** (for registry storage)
- **Kubernetes/OpenShift cluster** (for container node execution)
- **uv** (Python package manager): `pip install uv`

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/syntara-node-sdk.git
cd syntara-node-sdk

# Install the SDK package
pip install -e ./sdk-python

# Install dev dependencies
pip install -e .

# Install test dependencies
pip install pytest pytest-mock respx httpx

# Set up PostgreSQL test database (optional)
export SYNTARA_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/syntara_test

# Run tests
uv run pytest tests/registry/test_postgres_registry.py

# Or run with pytest
PYTHONPATH="nodes/http-request:$PYTHONPATH" \
  pytest tests/nodes/http-request/test_http_node.py -v
```

### Project Structure

```
syntara-node-sdk/
├── schemas/
│   └── common-definitions.json        # Platform meta-schema
├── nodes/
│   ├── http-request/                  # Action node example
│   ├── script-executor/               # Task node example
│   └── subworkflow-trigger/           # Trigger node example
├── sdk-python/
│   └── syntara_sdk/                   # Python SDK & base classes
├── docs/
│   └── architecture.md                # Technical specification
├── tests/                             # Integration tests
├── pyproject.toml                     # Python package config
└── README.md                          # This file
```

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
