# Syntara Node SDK Architecture

The Syntara Node SDK is a schema-driven framework for authoring, packaging, and registering custom automation nodes. This document defines the node taxonomy, authoring format, platform integration assumptions, and dynamic dispatch logic.

## Architecture Principles and Boundaries

The following principles are normative for the SDK-owned contracts. The SDK owns schemas, manifests, compiled descriptors, declared requirements, registration metadata, and the abstract task-invocation payload. The execution plane owns worker lifecycle, provisioning backends, pool image selection, runtime credential injection, sandbox transport, retries, persistence, scrubbing implementation, and completion delivery. Later sections provide implementation details and examples without redefining these boundaries.

1. **YAML authoring, JSON registry.** Developers author `manifest.yaml` in a human-friendly format with comments. The SDK validates it against JSON Schema Draft-07 and compiles it to `node-definition.json`; registry authority then follows the node-type registration paths described below.

2. **Four-category taxonomy.** Every node declares exactly one of `action`, `task`, `workflow`, or `trigger`. The category, together with `execution_type`, determines routing and validation.

3. **Explicit execution boundary and abstract task payload.** Every node declares `execution_type` as `in_process` or `container`. In-process nodes run as built-in workflow activities; container nodes are handed to the execution plane with their descriptor, selection metadata, registration controls, and abstract task invocation. The container invocation is one JSON map containing `script`, plain `inputs`, decrypted `credentials`, and `workflow_context` over `stdin`; the node returns JSON over `stdout`. The separate `credentials` map exists because the compiled schema identifies sensitive input values. The execution plane owns the concrete transport, injection, lifecycle, retries, persistence, and completion behavior.

4. **Metadata remains coupled to a container artifact.** Fully decoupling metadata is rejected because independently versioned metadata can drift from the image. A container-backed node stores its manifest as an OCI-compliant referral layer annotation with media type `application/vnd.syntara.node.manifest.v1+yaml`. Registration performs an OCI Distribution API manifest or digest metadata query, inspects the response metadata in `<10 ms`, and does not download image layers. The platform's indexed metadata store consumes the extracted manifest and makes the descriptor, inputs, outputs, execution type, and image reference available to the canvas in `<500 ms` without an edit-time OCI request.

5. **Selection metadata is part of the SDK-to-plane handoff.** `declaredRequirements`, `schedulingControls`, `workloadClassification`, resource requirements, and execution timeout describe what the node needs so the platform can validate and route it. These fields express node needs; they do not define worker lifecycle or runtime enforcement mechanics.

6. **Secret handling has an ordered SDK handoff lifecycle.** Draft-07 input properties must use `secret: true` for sensitive values; `is_secret: true` is the compatibility alias. The SDK-side order is `classify → split → decrypt → construct stdin`: secret-marked values are removed from plain `inputs`, decrypted into the transient `credentials` map, and included in the single stdin envelope. The same schema flags remain available to the execution plane for credential separation and its logging and persistence guarantees.

7. **Requirements and controls have different owners.** Developer manifests may declare requested capabilities in `spec.declaredRequirements` (for example, `capabilities: [network-egress]`). Syntara administrators set the effective infrastructure controls during registration through `sandbox_required`, `egress_policy`, and `worker_pool_selector`; these settings are not hardcoded in developer metadata. The platform registration contract carries those fields so pools can be provisioned automatically or assigned manually without changing the SDK contract.

8. **Registration authority follows the node description.** In-process platform nodes and shared-runner script nodes accept a client-supplied `descriptor` through the platform's direct descriptor registration mechanism. Dedicated container extensions accept an `image_ref`; the platform derives the descriptor from the OCI referral layer and requires a new image tag or digest for descriptor changes.

9. **Strict backwards compatibility.** `StandardOutputWrapper` (`Result`, `StatusCode`, `StatusMessage`, `ErrorMessage`) is immutable. Template expressions like `${task.Result.stdout}` never break across node versions.

10. **Zero-trust resources.** Node definitions store only UUID references to platform-managed credentials. Runtime secret handling and the persistence/logging guarantee are execution-plane responsibilities, while the SDK preserves the credential-reference and sensitive-input contracts described above and in **Credential Handling**.

## Core Architectural Standards & Taxonomy

### Node Category Taxonomy

The platform recognizes exactly four categories, defined canonically as `NodeCategory` in `common-definitions.json`:

```json
"enum": ["action", "task", "workflow", "trigger"]
```

| Category | Purpose | Typical `execution_type` | Examples |
|----------|---------|--------------------------|----------|
| `action` | Domain and external API integrations | `container` | `http_request`, `github_issue` |
| `task` | Atomic compute and script executors | `container` | `script_executor` (Python 3.12, Bash 5.2) |
| `workflow` | In-memory control-plane logic | `in_process` | `condition`, `loop`, `switch` |
| `trigger` | Event entry points | `in_process` | Webhook, Schedule, Manual, `subworkflow_trigger` |

### Execution Type

`NodeExecutionType` (`common-definitions.json`) captures *where* a node runs:

```json
"enum": ["in_process", "container"]
```

- **`in_process`** — executed inline as a built-in workflow activity inside the orchestrator process. Reserved for control-plane `workflow` logic and `trigger` nodes that need no isolated runtime.
- **`container`** — handed to the execution plane with the node's descriptor, selection metadata, registration controls, and abstract task invocation. The SDK does not prescribe the execution plane's worker lifecycle, provisioning backend, transport, or runtime isolation implementation.

### The `subworkflow_trigger` Node

`subworkflow_trigger` is a dedicated, first-class node type that lets a parent workflow invoke a child workflow as a composable, reusable unit.

- **Category:** `trigger`
- **Execution type:** `in_process`
- **Reference implementation:** [nodes/subworkflow-trigger/](../nodes/subworkflow-trigger/)

It runs in-process: it accepts the **parent workflow context**, an **ingress payload schema** (the parent↔child contract), and the **caller execution ID**, then hands control to the referenced child workflow. It returns a `StandardOutputWrapper` whose `Result` carries the child workflow's terminal output, so downstream parent nodes can reference it via stable template expressions (e.g., `${call_child.Result.summary}`).

### `manifest.yaml` — The Developer Authoring Format

Developers author a single `manifest.yaml` following Kubernetes Custom Resource Definition (CRD) conventions. The manifest is:

- **Human-friendly** — supports comments and multi-line strings
- **K8s-style structure** — uses `apiVersion`, `kind`, `metadata`, and `spec` sections
- **Validated** — checked against JSON Schema (Draft-07) referencing `common-definitions.json`
- **Compiled** — `syntara-sdk build` produces `node-definition.json`, the artifact stored in the registry

For dedicated container extensions, the manifest remains coupled to the container artifact through the OCI referral layer. In-process platform nodes and shared-runner script nodes use the direct descriptor registration path. In both cases, the canvas consumes the platform's indexed metadata record rather than fetching remote metadata while an editor is open.

**Standard Package Layout:**
```
my-custom-node/
├── manifest.yaml              # Primary authoring manifest (YAML, K8s CRD structure)
├── main.py                    # Imperative execution code (or main.sh for Bash)
├── requirements.txt           # Python dependencies (optional)
├── README.md                  # Node documentation
└── tests/
    └── test_main.py           # Unit tests
```

**Example `manifest.yaml` structure (K8s CRD style):**

The base manifest includes `spec.declaredRequirements`. Extension authors use it to declare requested capabilities, credential types, and minimum platform version. These declarations are inputs to administrative review; they do not themselves grant sandbox, network, or worker-pool access.

**Note (Non-Normative Example):** Payload and manifest examples in this section are provided strictly for illustrative purposes. They do not define or reference implementation-specific API endpoints.

```yaml
apiVersion: syntara.io/v1alpha1
kind: NodeType

metadata:
  name: http_request
  displayName: HTTP Request
  version: 1.0.0
  icon: globe
  description: |
    Non-blocking HTTP/HTTPS API orchestrator with credential injection,
    response parsing, and automatic retry logic.
  tags:
    - integration:rest-api
    - network:external
  author: Syntara Team
  license: Apache-2.0

spec:
  category: action
  execution:
    type: container
    image: registry.example.com/nodes/http-request:1.0.0

  declaredRequirements:
    capabilities:
      - network-egress
      - readonly-root-filesystem
      - tmpfs-mount
    platformVersion: ">=3.0.0"

  schedulingControls:
    # Optional developer-declared controls. Effective sandbox, egress, and
    # worker-pool policy is supplied by administrators at registration.
    connectivity_requirements:
      - host: api.github.com
        ports:
          - port: 443
            protocol: TCP

  inputs:
    properties:
      url:
        type: string
        description: Target HTTP/HTTPS URL
      api_key:
        type: string
        description: Runtime API key; classified as sensitive by the schema
        secret: true
      method:
        type: string
        enum: [GET, POST, PUT, DELETE, PATCH]
        default: GET
    required:
      - url
      - method

  outputs:
    allOf:
      - $ref: "../common-definitions.json#/definitions/StandardOutputWrapper"

  resourceRequirements:
    limits:
      cpu: 500m
      memory: 256Mi
    requests:
      cpu: 100m
      memory: 128Mi

  executionTimeout: 60
```

### Diagram 1 — Node Definition Composition (`manifest.yaml`)

Structural breakdown of what a `manifest.yaml` composes.

```mermaid
graph TB
    MANIFEST["manifest.yaml<br/>(K8s CRD structure)"]

    subgraph CRD["CRD Structure"]
        API["apiVersion + kind"]
        META["metadata<br/>• name, displayName<br/>• version, icon<br/>• description, tags"]
        SPEC["spec"]
    end

    subgraph SPEC_CONTENTS["spec section"]
        CAT["category + execution"]
        INPUTS["inputs<br/>• typed properties<br/>• required / enum / pattern"]
        OUTPUTS["outputs<br/>StandardOutputWrapper"]
        REQS["declaredRequirements<br/>• capabilities<br/>• platformVersion"]
        SCHED["schedulingControls<br/>• connectivity controls<br/>• affinity controls"]
    end

    MANIFEST --> API
    MANIFEST --> META
    MANIFEST --> SPEC
    SPEC --> CAT
    SPEC --> INPUTS
    SPEC --> OUTPUTS
    SPEC --> REQS
    SPEC --> SCHED

    OUTPUTS -.->|$ref| CD["common-definitions.json"]
    REQS -.->|$ref| CD
    SCHED -.->|$ref| CD
```

### Diagram 2 — SDK Authoring & Packaging Lifecycle

The developer lifecycle from scaffold to registry handoff.

```mermaid
graph LR
    INIT["syntara-sdk init<br/>(Scaffold package)"]
    AUTHOR["Author<br/>manifest.yaml"]
    VALIDATE["syntara-sdk validate<br/>Draft-07 check vs<br/>common-definitions.json"]
    BUILD["syntara-sdk build<br/>Compile →<br/>node-definition.json"]
    PUBLISH["Registry Publish<br/>platform registration mechanism"]
    HANDOFF["Available to<br/>Orchestrator"]

    INIT --> AUTHOR
    AUTHOR --> VALIDATE
    VALIDATE -->|Pass| BUILD
    VALIDATE -.->|Fail: schema errors| AUTHOR
    BUILD --> PUBLISH
    PUBLISH --> HANDOFF
```

## Platform Metadata & Storage Assumptions

The SDK does not prescribe a database schema, ORM, persistence technology, or
REST routing model for the host platform. It assumes that extension
registration populates an indexed platform metadata store that can support the
following uses:

- retain the compiled `node-definition.json` descriptor or an equivalent canonical representation;
- expose indexed identity, category, version, execution type, and image-reference metadata;
- make input and output schemas available to the canvas and execution plane;
- keep administrative registration policy separate from developer-authored manifests and OCI metadata; and
- satisfy the `<500 ms` canvas discovery and rendering SLA without remote OCI calls during editing.

The metadata store may be implemented with a relational database, document
store, search index, cache, or another platform-owned service. Its schema and
transport are implementation choices outside the SDK specification.

### Illustrative platform registry consumption

The following conceptual projection shows the information a platform registry
could parse from a compiled descriptor. It is an illustrative example only and
is not a final implementation record, ORM model, storage schema, or API
contract.

**Note (Non-Normative Example):** Payload and manifest examples in this section are provided strictly for illustrative purposes. They do not define or reference implementation-specific API endpoints.

```json
{
  "identity": {
    "name": "script_executor",
    "version": "1.0.0"
  },
  "metadata": {
    "displayName": "Python Script Executor",
    "category": "task",
    "description": "Executes a script in a shared runner"
  },
  "descriptor": "compiled node-definition.json",
  "execution": {
    "type": "container",
    "image": "quay.io/syntara/script-python-executor:latest"
  },
  "availability": {
    "enabled": true
  }
}
```

An implementation may map this projection to an ORM model or other indexed
record, but that mapping is non-normative. The SDK contract is the manifest,
compiled descriptor, OCI packaging convention, and execution handoff—not the
platform's persistence representation.

### Authoritative registration paths by node type

The registration source of truth depends on whether the node is a platform-owned
definition, a zero-build script definition, or a dedicated extension image:

| Node type | Authoritative registration mechanism | Image and descriptor rules |
|-----------|--------------------------------------|----------------------------|
| In-process platform nodes | Direct Descriptor Registration Payload | The descriptor is authoritative. These nodes have `execution_type: in_process` and no container image or OCI referral layer. |
| Script nodes using the shared platform runner | Direct Descriptor Registration Payload | The descriptor is authoritative. A node may reference a platform-managed shared script-runner image, but the node does not ship a dedicated OCI image or referral layer. |
| Dedicated container extensions | OCI Distribution API Digest Query | The OCI artifact and its embedded manifest are authoritative. A descriptor change requires registering a new container image tag or digest. |

For dedicated container extensions, `image_ref` identifies the artifact whose
metadata is inspected. The platform performs the OCI metadata query in `<10
ms`, extracts the embedded manifest annotation, and hydrates its indexed
metadata store without downloading image layers. Re-registering a new image
version or digest is the supported descriptor-update path and prevents
image/metadata version drift.

For in-process platform nodes and shared-runner script nodes, the direct
descriptor registration mechanism is authoritative because these nodes are
platform-owned or zero-build definitions. Administrative fields such as
`sandbox_required`, `egress_policy`, and `worker_pool_selector` remain
registration-owned for every node type.

**Note (Non-Normative Example):** Payload and manifest examples in this section are provided strictly for illustrative purposes. They do not define or reference implementation-specific API endpoints.

```json
{
  "name": "script_executor",
  "category": "task",
  "execution_type": "container",
  "image_ref": "registry.example.com/nodes/script-executor:1.0.0",
  "version": "1.0.0",
  "sandbox_required": true,
  "egress_policy": "restricted",
  "worker_pool_selector": {
    "workload": "automation",
    "region": "us-east-1"
  }
}
```

The platform may validate administrative policy fields and may expose indexed
descriptor and palette projections to the canvas through any suitable local
discovery mechanism. Those choices are intentionally outside this SDK
specification.

## Dynamic Dispatch Logic

The orchestrator's workflow engine forks execution on a node's `execution_type`. This fork is the boundary between the control plane and the execution plane.

```mermaid
graph TB
    NODE["Node to execute<br/>(from workflow graph)"]
    FORK{"execution_type?"}

    subgraph INPROC["in_process — built-in workflow activities"]
        WF["workflow nodes<br/>Loop / Condition / Switch / Converge"]
        TRIG["trigger nodes<br/>Webhook / Schedule / Manual"]
        SUBWF["subworkflow_trigger<br/>(invoke child workflow)"]
    end

    subgraph CONTAINER["container — execution-plane handoff"]
        ACT["action nodes<br/>http_request, github_issue"]
        TASK["task nodes<br/>script_executor"]
    end

    NODE --> FORK
    FORK -->|in_process| INPROC
    FORK -->|container| CONTAINER
    INPROC --> RESULT["StandardOutputWrapper"]
    CONTAINER --> RESULT
```

- **`in_process` branch** — the engine dispatches the node as a built-in workflow activity within the orchestrator process. This path serves control-plane `workflow` logic and `trigger` nodes.
- **`container` branch** — the engine resolves the local descriptor and registration policy, performs the ordered classify/split/decrypt/envelope-construction flow, and hands the execution plane the abstract JSON task invocation plus the node-specific selection metadata. The execution plane consumes that handoff and returns the standard output contract; worker lifecycle, provisioning backend, transport, retries, persistence, and completion delivery are outside the SDK.

Both branches return the identical `StandardOutputWrapper` envelope, so downstream nodes are agnostic to where a node ran.

### Diagram 3 — SDK-to-Execution-Plane Handoff Contract

The contract the control plane hands to the execution plane for a `container` node.

```mermaid
graph LR
    subgraph CONTROL["Control Plane (Orchestrator)"]
        DESC["node-definition.json<br/>descriptor"]
    end

    subgraph CONTRACT["Handoff Contract →"]
        C1["image_ref"]
        C2["stdin JSON map<br/>script + inputs + decrypted credentials + context"]
        C3["selection metadata<br/>requirements + classification + resources"]
        C4["registration controls<br/>sandbox + egress + pool selector"]
    end

    subgraph PLANE["Execution Plane<br/>(implementation boundary)"]
        BB["Receive · Execute ·<br/>Return standard output"]
    end

    subgraph RETURN["← StandardOutputWrapper"]
        R1["Result"]
        R2["StatusCode"]
        R3["StatusMessage"]
        R4["ErrorMessage"]
    end

    DESC --> C1 --> BB
    DESC --> C2 --> BB
    DESC --> C3 --> BB
    DESC --> C4 --> BB
    BB --> R1
    BB --> R2
    BB --> R3
    BB --> R4
```

The handoff fields have distinct purposes:

- **`image_ref`** identifies the registered container artifact for a dedicated container extension; its OCI-derived descriptor remains authoritative for that node type.
- **The stdin JSON map** carries the script, plain inputs, decrypted credentials, and workflow context required to execute the node without exposing secret-marked values in the plain `inputs` map.
- **Selection metadata** carries the node's declared requirements, classification, resource shape, and timeout so the platform can validate and route the invocation.
- **Registration controls** carry the administrator's authoritative sandbox, egress, and worker-pool binding independently of developer-authored metadata.

## Policy & Security Enforcement

### The Three-Party Enforcement Model

1. **The node declares its contract and requirements.** `manifest.yaml` declares the node's category, execution image, input/output schemas, secret markers, resource shape, and `declaredRequirements`. For example, `declaredRequirements.capabilities: [network-egress]` states that the extension needs outbound connectivity. Sensitive input definitions must use `secret: true` (or `is_secret: true`). The manifest declares the need; it does not grant infrastructure access.

2. **Administrators set registration policy.** Syntara supplies `sandbox_required`, `egress_policy`, and `worker_pool_selector` through the platform registration contract. These settings are authoritative for the registered extension and remain independent of the image metadata. The platform may provision pools automatically or use an operations assignment.

3. **The Execution Plane consumes the SDK contract.** It receives the local descriptor, abstract task invocation, declared requirements, and administrative registration controls. It owns worker lifecycle, provisioning, runtime credential injection, sandbox and transport enforcement, retries, persistence, log scrubbing, and completion delivery. Those mechanisms are intentionally not defined by the SDK.

### Diagram 4 — Declared Capabilities & Permission Manifest

Static administrative inspection before execution-plane dispatch.

```mermaid
graph TB
    subgraph MANIFEST["Declared Permission Manifest (static)"]
        WC["workloadClassification<br/>action | agentic"]
        REQS["manifest.declaredRequirements<br/>capabilities"]
        CONN["registration.egress_policy<br/>none | restricted | unrestricted"]
        CAPS["registration.sandbox_required<br/>+ worker_pool_selector"]
    end

    subgraph AUDIT["Static Administrative Inspection"]
        REVIEW["Security review /<br/>policy gate"]
        DECISION{"Approve for<br/>execution?"}
    end

    WC --> REVIEW
    REQS --> REVIEW
    CONN --> REVIEW
    CAPS --> REVIEW
    REVIEW --> DECISION
    DECISION -->|Approved| ALLOW["Eligible for<br/>container execution"]
    DECISION -->|Rejected| BLOCK["Blocked before<br/>execution-plane dispatch"]
```

Key inspection points, all resolvable without executing the node:

- **`workloadClassification`** (`action` | `agentic`) — gates which credential classes the node may access; `agentic` nodes are blocked from infrastructure credentials
- **`egress_policy`** — the administrator-selected egress mode supplied to the execution plane for runtime policy enforcement
- **`sandbox_required`** — the administrative requirement supplied to the execution plane for sandbox enforcement
- **`worker_pool_selector`** — affinity labels supplied to the execution plane for eligible worker selection

### Credential Handling

Secret handling has the following required order:

1. **Classify.** Before execution-plane dispatch and before `stdin` is constructed, the dispatcher validates the logical invocation against the compiled input schema. A property is sensitive when it has the canonical `secret: true` flag; the compatibility alias `is_secret: true` is also recognized.
2. **Split.** The dispatcher uses those schema flags to separate the invocation values into plain `inputs` and secret-marked values. Secret values are not copied into the plain `inputs` map.
3. **Decrypt.** The credential service resolves and decrypts the secret-marked values, producing the transient `credentials` map. A decryption or authorization failure stops dispatch before the execution plane receives the invocation.
4. **Construct stdin.** The dispatcher builds exactly one JSON invocation envelope containing the script code, plain `inputs`, decrypted `credentials`, and `workflow_context`:

   **Note (Non-Normative Example):** Payload and manifest examples in this section are provided strictly for illustrative purposes. They do not define or reference implementation-specific API endpoints.

   ```json
   {
     "script": "...",
     "inputs": {"url": "https://example.com"},
     "credentials": {"api_key": "..."},
     "workflow_context": {"execution_id": "..."}
   }
   ```

5. **Hand off the abstract invocation.** The complete envelope—including decrypted `credentials`—is the SDK-to-execution-plane task payload. A container node reads this JSON map from `stdin` and writes its JSON result to `stdout`; the execution plane owns the concrete worker transport and credential-injection mechanism.
6. **Retain schema sensitivity metadata for the execution plane.** The compiled `secret: true`/`is_secret: true` definitions accompany the node contract so the execution plane can separate credentials and apply its logging and persistence guarantees. The SDK does not define the scrubbing implementation.

The node process does not implement a technology-specific execution-plane entry point. Its SDK-facing contract is to read the JSON invocation from `stdin` and write JSON to `stdout`; the execution plane owns any transport adaptation and completion signaling.

**Security classification (`workloadClassification`):**

- **`action`** — scripted, deterministic execution. May request infrastructure credentials (SSH, cloud API keys, vault access).
- **`agentic`** — LLM-driven, non-deterministic execution. **Restricted from requesting high-privilege infrastructure credentials.** This prevents a prompt-injection attack against an AI agent node from escalating into infrastructure compromise.

## Schema Reference

### Platform Meta-Schema

The platform maintains a **single meta-schema** that defines shared types, enums, and validation rules:

| File | Role |
|------|------|
| `common-definitions.json` | **Sole platform meta-schema** — defines `NodeTypeManifest`, `NodeCategory`, `NodeExecutionType`, `WorkloadClassification`, `StandardOutputWrapper`, `CredentialReference`, `InputParameter`, `ResourceRequirements`, `SchedulingControls`, and `DependencyDeclaration` |

Individual node schemas are **not** maintained as separate `.schema.json` files. Instead:

1. **Developers author** `manifest.yaml` instances following the K8s CRD structure
2. **The SDK compiles** each manifest into a `node-definition.json` build artifact via `syntara-sdk build`
3. **The platform metadata store persists** the compiled `node-definition.json` or an equivalent canonical descriptor
4. **The orchestrator and canvas consume** the compiled artifact, not the source manifest

`common-definitions.json` is the authoritative source for shared platform types. All `manifest.yaml` instances reference these definitions via `$ref` during validation.

### Key Common Definitions

| Definition | Purpose | Shape |
|---|---|---|
| `NodeTypeManifest` | K8s CRD structure validation | `{apiVersion, kind, metadata, spec}` |
| `NodeCategory` | Four-category taxonomy | `enum: ["action", "task", "workflow", "trigger"]` |
| `NodeExecutionType` | Execution plane fork | `enum: ["in_process", "container"]` |
| `WorkloadClassification` | Credential access control | `enum: ["action", "agentic"]` |
| `StandardOutputWrapper` | Immutable output contract | `{Result, StatusCode, StatusMessage, ErrorMessage}` |
| `CredentialReference` | UUID-based credential reference | `{credential_id, credential_mount_type, credential_mount_path}` |
| `InputParameter` | Sensitive-input classification | `secret: true` or `is_secret: true` |
| `NodeRegistrationPolicy` | Syntara-owned execution policy | `{sandbox_required, egress_policy, worker_pool_selector}` |
| `ResourceRequirements` | Kubernetes resource limits | `{limits: {cpu, memory}, requests: {cpu, memory}}` |
| `SchedulingControls` | Developer-declared scheduling controls | `{connectivity_requirements, affinity_labels}` |

### Compiled Definition Shape (K8s CRD)

Every compiled `node-definition.json` follows the K8s CRD structure:

**Note (Non-Normative Example):** Payload and manifest examples in this section are provided strictly for illustrative purposes. They do not define or reference implementation-specific API endpoints.

```json
{
  "apiVersion": "syntara.io/v1alpha1",
  "kind": "NodeType",
  "metadata": {
    "name": "http_request",
    "displayName": "HTTP Request",
    "version": "1.0.0",
    "icon": "globe",
    "description": "...",
    "tags": ["integration:rest-api", "network:external"]
  },
  "spec": {
    "category": "action",
    "execution": {
      "type": "container",
      "image": "registry.example.com/nodes/http-request:1.0.0"
    },
    "inputs": { "...": "typed properties" },
    "outputs": { "$ref": "common-definitions.json#/definitions/StandardOutputWrapper" }
  }
}
```

## Example Nodes

The SDK includes reference implementations demonstrating each node category:

| Example | Category | Execution Type | Location |
|---------|----------|----------------|----------|
| `http_request` | action | container | [nodes/http-request/](../nodes/http-request/) |
| `script_executor` | task | container | [nodes/script-executor/](../nodes/script-executor/) |
| `subworkflow_trigger` | trigger | in_process | [nodes/subworkflow-trigger/](../nodes/subworkflow-trigger/) |

Each example includes:
- Complete `manifest.yaml` following K8s CRD structure
- Compiled `node-definition.json` artifact
- Test suite demonstrating validation and registration
- README with usage instructions
