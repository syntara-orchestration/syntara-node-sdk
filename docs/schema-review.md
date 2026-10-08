# Plugin SDK schema review

Status: review disposition, revised 2026-10-08

This document records the cross-team review of the plugin and step manifest
contracts. It is an architectural review only; it does not change the JSON
schemas or runtime implementation. The evidence set was the schema files,
compiler, Python reference SDK, fixtures, examples, tests, and
`docs/architecture.md`.

## Decision vocabulary

* **Approved** — needed, correctly shaped for the current contract, and owned.
* **Requires revision** — needed, but the shape, validation, or ownership is
  incomplete or inconsistent.
* **Deferred** — useful or plausible, but its contract depends on an unresolved
  platform decision.
* **Removed/rehome** — not an SDK manifest concern; remove it from this
  contract or move it to its owning boundary.

## Ownership model

| Owner | Contract responsibility |
|---|---|
| SDK | Authoring schemas, descriptor shape, identity derivation, target discovery, input/output contract, and step-side validation contract |
| Registration | Metadata indexing and administrator-owned controls |
| Control plane | Category-aware dispatch, workflow lifecycle, and credential authorization |
| Execution plane | Image execution, credential injection, resource/timeout enforcement, retries, persistence, scrubbing, and completion delivery |
| Canvas/workflow designer | Form rendering, author-time validation, and credential binding |

A declaration in a manifest expresses a requirement or hint. It does not grant
authorization or override registration policy.

## Plugin manifest matrix

| Field | Current shape and validation | Consumer / owner | Disposition and rationale |
|---|---|---|---|
| `apiVersion` | Required string, constant `syntara.io/v1alpha1` | SDK validator | **Approved.** Stable schema identity. |
| `kind` | Required string, constant `Plugin` | SDK validator and discovery | **Approved.** Distinguishes the root resource. |
| `metadata` | Required object; no additional properties | SDK validator | **Approved.** Plugin-level identity and catalog metadata. |
| `metadata.name` | Required snake_case string, 1–64 characters | SDK identity/compiler | **Approved.** Stable plugin identifier. |
| `metadata.namespace` | Required snake_case string, 1–64 characters | SDK identity/compiler | **Approved.** Ownership namespace; used in derived step identity. |
| `metadata.displayName` | Required non-empty string, max 128 | Canvas/catalog | **Approved.** Human-facing name. |
| `metadata.version` | Required string matching the current release-version regex | Registration and upgrade checks | **Requires revision.** The regex is not a complete SemVer contract. Define release-version semantics separately from runtime platform requirements. |
| `metadata.description` | Required non-empty string, max 2000 | Catalog and authoring tools | **Approved.** Purpose and discovery text. |
| `metadata.authors` | Required non-empty array of `Author` | Catalog and attribution | **Approved.** `Author.name` is required; email and URL are optional. |
| `metadata.authors[].name` | Required string, 1–256 | Catalog | **Approved.** |
| `metadata.authors[].email` | Optional string; email format is currently an annotation only because the compiler does not enable a format checker | Catalog | **Requires revision.** Either enforce formats consistently or explicitly make them informational. |
| `metadata.authors[].url` | Optional string; URI format is currently an annotation only | Catalog | **Requires revision.** Either enforce formats consistently or explicitly make them informational. |
| `metadata.license` | Optional string | Catalog and compliance | **Approved.** Keep free-form until a license vocabulary is selected. |
| `metadata.documentationUrl` | Optional string; URI format is currently an annotation only | Catalog and authoring tools | **Requires revision.** Either enforce formats consistently or explicitly make them informational. |
| `spec` | Required object; no additional properties | SDK validator/compiler | **Approved.** Root contract boundary. |
| `spec.targets` | Required non-empty unique array of relative `.yaml`/`.yml` paths; rejects URLs, absolute paths, and traversal | SDK discovery/compiler | **Approved.** Explicit discovery is deterministic. The compiler also rejects target symlink escapes; unlisted manifests are not included because discovery is explicit. |
| `spec.runtime.image` | Required single digest-pinned plugin runtime image | SDK compiler, packaging, descriptor consumers, and execution plane | **Approved.** The plugin is the image ownership boundary. The image contains the fixed dispatcher and every step implementation; every targeted step inherits it. A distinct dependency or isolation boundary is a distinct plugin. |
| compiled descriptor `runtimeImage` | Compiler-inherited runtime image copied from `spec.runtime.image` | Registration, dispatch, and execution plane | **Approved.** It makes the runtime image explicit at the step descriptor boundary. |
| compiled descriptor `contentDigest` | SHA-256 digest over qualified identity, step manifest, and inherited runtime image | Registration and upgrade/rollback tracking | **Approved.** Changing the plugin runtime image changes every affected step descriptor digest. |
| private SDK compatibility | No field in the reachable plugin schema | N/A | **Approved.** This private SDK has no separate compatibility contract; step-level `platformVersion` remains the only declared runtime platform requirement. |
| plugin language/runtime dependencies | No reachable field; `DependencyDeclaration` is currently orphaned | SDK packaging and registration | **Removed.** The private SDK has no dependency contract at this boundary. Remove the orphan definition unless a concrete consumer is introduced later. |

## Step manifest matrix

| Field | Current shape and validation | Consumer / owner | Disposition and rationale |
|---|---|---|---|
| `apiVersion` | Required string, constant `syntara.io/v1alpha1` | SDK validator | **Approved.** |
| `kind` | Required string, constant `StepType` | SDK validator and discovery | **Approved.** |
| `metadata` | Required object; no additional properties | SDK validator, catalog | **Approved.** Namespace and plugin version are inherited from the parent plugin. |
| `metadata.name` | Required snake_case string, 1–64 characters | SDK identity/compiler | **Approved.** Local step identifier; canonical identity is derived with parent context. |
| `metadata.displayName` | Required non-empty string, max 128 | Canvas/catalog | **Approved.** |
| `metadata.icon` | Optional lower-case hyphenated string | Canvas | **Requires revision.** The schema uses a broad pattern while the documentation describes a palette vocabulary. Choose either a governed icon enum/catalog or explicitly document the extension rule. |
| `metadata.description` | Required non-empty string, max 2000 | Canvas/catalog | **Approved.** |
| `metadata.tags` | Optional unique array of `key:value` strings | Catalog/filtering | **Approved.** Keep the current organization/filtering role; document reserved keys if any are introduced. |
| `metadata.authors` | Optional non-empty `Author` array | Catalog and attribution | **Approved.** |
| `metadata.license` | Optional string | Catalog and compliance | **Approved.** |
| `metadata.documentationUrl` | Optional URI string | Catalog/authoring | **Approved.** |
| `spec.category` | Required enum: `action`, `task`, `workflow`, `trigger` | Canvas and control-plane dispatch | **Approved.** Exactly one category is enforced by the scalar enum. |
| `spec.execution` | Required object containing only `entrypoint`; no additional properties | SDK compiler, control plane, and image dispatcher | **Approved.** A step cannot select an image, container command, or execution placement. |
| `spec.execution.entrypoint` | Required `module.path:ClassName` implementation handle | SDK compiler, control plane, and fixed image dispatcher | **Approved.** Every step identifies its code. Direct control-plane execution and the runtime image dispatcher use the same handle; it is not a container command or placement selector. |
| `spec.declaredRequirements` | Optional object; no unknown properties | Registration review and dispatch preparation | **Approved with revision.** It correctly expresses requirements, not authorization, but its version grammar and capability vocabulary need a single owner. |
| `spec.declaredRequirements.platformVersion` | Optional string with a custom range regex | Registration compatibility check | **Requires revision.** Adopt one documented SemVer-range grammar for the declared runtime platform requirement. |
| `spec.declaredRequirements.capabilities` | Optional unique array of an allow-listed capability enum | Registration/security review | **Approved with revision.** The declaration/authorization distinction is correct; confirm the vocabulary and whether each capability is functional or administrative. |
| `spec.schedulingControls` | Optional object with developer-declared affinity/connectivity hints | Registration review and execution-plane policy | **Deferred.** These fields are not effective placement or egress controls. Resolve their value and ownership before treating them as stable SDK contract. |
| `spec.schedulingControls.affinity_labels` | Optional array of key/value or key-only label strings, default `[]` | Registration/worker-pool selection | **Removed/rehome.** It overlaps the registration-owned worker-pool selector and invites authors to express placement policy. Rehome as an administrator-owned control if required. |
| `spec.schedulingControls.connectivity_requirements` | Optional array, default `[]`; string destination or object destination plus ports | Registration/security review | **Deferred.** A useful declaration may remain, but the allowed destination grammar, CIDR support, wildcard semantics, and relationship to effective egress policy need an owner. |
| `connectivity_requirements[]` string | Host/FQDN/IPv4/CIDR pattern; all ports implied | Registration review | **Requires revision if retained.** Make wildcard/all-port semantics explicit and validate IPv4/CIDR precisely. |
| `connectivity_requirements[].host` | Required non-empty host string in object form | Registration review | **Requires revision if retained.** Use the same destination grammar as string form. |
| `connectivity_requirements[].ports` | Required non-empty array in object form | Registration review | **Requires revision if retained.** Confirm whether empty/all-port access is allowed and whether duplicate ports are rejected. |
| `connectivity_requirements[].ports[].port` | Required integer 1–65535 | Registration/execution policy | **Approved if the parent field is retained.** |
| `connectivity_requirements[].ports[].protocol` | Optional enum `TCP`/`UDP`, default `TCP` | Registration/execution policy | **Requires revision if retained.** Confirm whether other protocols are intentionally unsupported. |
| `spec.inputs` | Required object with `properties`; additional properties currently allowed | Canvas, SDK tooling, step-side validation | **Requires revision.** The shape is appropriate, but it must be meta-validated as Draft-07 and runtime validation must use the same declared contract. |
| input-schema validation profile | `InputParameter` accepts arbitrary object members; it currently does not meta-validate `type`, `items`, `properties`, `oneOf`, `anyOf`, `$ref`, `format`, `patternProperties`, `additionalProperties`, boolean schemas, or other Draft-07 keywords | SDK tooling and step-side validation | **Requires revision.** Choose and publish either complete recursive Draft-07 subschema support or a closed supported-keyword profile. The rows below describe intended semantics, not current enforcement. |
| `spec.inputs.type` | Optional `object` constant; not required | Canvas/schema consumers | **Approved with revision.** Keep only if the descriptor contract treats inputs as a root object; otherwise make the intended requiredness explicit. |
| `spec.inputs.properties` | Required object mapping names to input schemas | Canvas and SDK validator | **Requires revision.** Validate property names and each value against a JSON Schema metaschema. |
| `spec.inputs.required` | Optional unique string array, default `[]` | Canvas and SDK validator | **Requires revision.** Every name must exist in `properties`; decide whether an empty array is emitted or omitted in compiled descriptors. |
| input property `type` | Accepted as an arbitrary member today; not meta-validated | Canvas and step-side validator | **Requires revision.** Confirm Draft-07 type forms, including arrays of primitive type names, and validate them rather than accepting arbitrary objects. |
| input property `description` | Accepted as an arbitrary member today; not constrained by the wrapper | Canvas | **Requires revision.** Define length/format and whether it is required for authoring quality. |
| input property `default` | Optional JSON value; accepted but not applied by the JSON Schema validator/compiler | Canvas/defaulting layer | **Requires revision.** Define whether defaults are author-time only or materialized into invocation payloads, and validate a default against its schema. |
| input property `enum` | Optional array of allowed JSON values; accepted but not meta-validated today | Canvas/author-time validator | **Requires revision.** Define non-empty/unique behavior and validate enum members against the input schema. |
| input property `pattern` | Optional string regex for string values; accepted but not applied to the independent Python model | Canvas and SDK validator | **Requires revision.** The declared pattern must be applied at invocation validation, not merely displayed. |
| input property `items` | Optional nested schema or schema array; accepted without recursive validation | Canvas and SDK validator | **Requires revision.** Validate nested items recursively and define tuple-array support. |
| input property `properties` | Optional nested object for object inputs; accepted without recursive validation | Canvas and SDK validator | **Requires revision.** Validate nested properties recursively, including nested `required`. |
| input property `required` | Optional nested unique string array; accepted without name resolution | Canvas and SDK validator | **Requires revision.** Names must resolve against the containing nested `properties`. |
| input property `oneOf` | Optional array of alternative schemas; accepted without recursive validation | Canvas and SDK validator | **Requires revision.** Validate alternatives recursively and define discriminator/form-rendering behavior. |
| input property `anyOf` | Optional array of non-exclusive alternatives; accepted without recursive validation | Canvas and SDK validator | **Requires revision.** Validate alternatives recursively and define ambiguity behavior in the form and runtime. |
| other Draft-07 input keywords | `$ref`, `format`, `patternProperties`, `additionalProperties`, `minLength`, `maxLength`, numeric bounds, array bounds, `uniqueItems`, `minProperties`, `maxProperties`, `const`, `not`, `allOf`, `if`/`then`/`else`, and related keywords are currently accepted as arbitrary members | SDK tooling, canvas, step-side validation | **Requires revision.** Do not imply partial support is complete; publish the supported profile or validate the full metaschema recursively. |
| input credential-bearing fields | Not structurally prohibited; a fixture accepts an authorization header/token as ordinary input | SDK linting, canvas, execution security | **Requires revision.** Runtime inputs must be distinct from credential requirements. Add authoring lint guidance and platform/SDK checks for known secret-bearing fields while retaining execution-plane scrubbing as the security boundary. |
| `spec.outputs` | Required object, but any object including `{}` currently validates | Canvas, registry, workflow templates | **Requires revision.** Require composition with the immutable `StandardOutputWrapper`; allow step-specific schema only inside `Result`. |
| `spec.credentialSpecification` | Optional object containing `credential_requirements` | Canvas binding and control-plane authorization | **Approved with revision.** It correctly declares named requirements, never credential values or IDs. |
| `credential_requirements` | Optional array, default `[]` | Canvas and control plane | **Requires revision.** Enforce unique requirement names and define whether an omitted list is equivalent to an empty list in descriptors. |
| credential `name` | Required snake_case string, max 64 | Canvas binding key | **Approved with revision.** Add list-level uniqueness and explicitly define stable binding identity. |
| credential `description` | Optional string, max 500 | Canvas | **Approved.** Human-facing purpose. |
| credential `types` | Required unique non-empty string array | Canvas picker and control-plane authorization | **Approved with revision.** Define a controlled type vocabulary or document extension ownership. |
| credential `required` | Optional boolean, default `true` | Control plane and canvas | **Approved.** Requiredness is distinct from input requiredness. |
| credential `mount_type` | Optional enum `env`, `file`, `tmpfs_file`, `header`, default `env` | Execution plane | **Requires revision.** This is a presentation request, not authorization; add conditional rules for all presentation modes. |
| credential `mount_path` | Optional absolute path pattern; currently required only for `tmpfs_file` | Execution plane | **Requires revision.** Require it for file presentation, forbid or ignore it for non-file modes, and confirm safe-path policy. |
| credential `header_name` | Optional header-name pattern | Execution plane | **Requires revision.** Require it for `header`, forbid or ignore it otherwise, and define a safe-header allow-list. |
| `spec.resourceRequirements` | Optional object with required `limits` and `requests` when present | Execution-plane admission/enforcement | **Deferred.** It is operational policy rather than a functional step contract until ownership, override, and dispatch semantics are settled. |
| `resourceRequirements.limits` | Required object with `cpu` and `memory` | Execution plane | **Deferred.** Keep only with explicit author-vs-admin precedence and quantity semantics. |
| `resourceRequirements.requests` | Required object with `cpu` and `memory` | Execution plane | **Deferred.** Define whether requests may exceed limits; current schema does not cross-validate the pair. |
| resource `cpu` | String quantity pattern; defaults depend on limits/requests | Execution plane | **Requires revision if retained.** Use a canonical quantity parser and define whether zero is valid. |
| resource `memory` | String quantity pattern with `Ki`, `Mi`, or `Gi`; defaults depend on limits/requests | Execution plane | **Requires revision if retained.** Define accepted quantity units and cross-field relationship. |
| `spec.executionTimeout` | Optional integer seconds, 1–86400, default 300 | Execution plane | **Deferred.** Clarify whether it covers one attempt or the complete retry budget and how administrator limits override it. |
| `spec.retryPolicy` | Optional object; no required members | Execution plane | **Removed/rehome unless a platform retry protocol is approved.** The architecture assigns retries to the execution plane, no runtime currently consumes this field, and its status-code range conflicts with process-style `StatusCode`. |
| `retryPolicy.max_attempts` | Optional integer 1–10, default 1 | Execution plane | **Removed/rehome.** If retained outside the manifest, define idempotency and attempt accounting. |
| `retryPolicy.initial_interval_seconds` | Optional integer 1–300, default 5 | Execution plane | **Removed/rehome.** Requires durable retry ownership and timeout interaction. |
| `retryPolicy.backoff_coefficient` | Optional number 1.0–10.0, default 2.0 | Execution plane | **Removed/rehome.** |
| `retryPolicy.retryable_status_codes` | Optional integer array, each 100–599 | Execution plane | **Removed/rehome.** The range models HTTP responses while the wrapper uses 0–255 execution status codes; define a transport-independent retry signal first. |

## Shared definitions outside the reachable manifest

These definitions exist in `common-definitions.json` but are not currently
reachable from either public manifest entry point. They are included here so
the review covers their shape and makes their ownership explicit.

| Definition / field | Current shape and validation | Consumer / owner | Disposition and rationale |
|---|---|---|---|
| `DependencyDeclaration` | Object with optional `platformVersion`, `capabilities`, `collections`, and `extensions`; not referenced by `PluginManifest` or `StepTypeManifest` | N/A | **Removed.** It has no consumer in the private SDK contract and should be deleted unless a concrete future consumer is introduced. |
| `DependencyDeclaration.platformVersion` | Optional custom SemVer-like range string | Registration compatibility check | **Requires revision.** Remove the orphan definition unless a concrete registration consumer is introduced. |
| `DependencyDeclaration.capabilities` | Optional unique array using the same capability enum; default `[]` | Registration/security review | **Requires revision.** Avoid two competing locations for capability declarations. |
| `DependencyDeclaration.collections` | Optional array; default `[]` | Image/build or registration owner | **Requires revision.** Define whether collection dependencies are build-time image inputs or registration-time compatibility constraints. |
| `collections[].name` | Required `namespace.collection`-shaped string | SDK packaging | **Requires revision if retained.** |
| `collections[].version` | Required custom version constraint string | SDK packaging | **Requires revision if retained.** Use one version grammar. |
| `DependencyDeclaration.extensions` | Optional array; default `[]` | SDK packaging or registration | **Requires revision.** Define the extension dependency lifecycle and avoid mutable runtime resolution. |
| `extensions[].name` | Required package-like name string | SDK packaging | **Requires revision if retained.** |
| `extensions[].version` | Required custom version constraint string | SDK packaging | **Requires revision if retained.** |
| `StepRegistrationPolicy` | Object with required `sandbox_required`, `egress_policy`, and `worker_pool_selector`; explicitly described as not belonging in authored manifests | Registration owner | **Approved as a separate boundary.** It must remain outside developer-authored manifest data. |
| `StepRegistrationPolicy.sandbox_required` | Required boolean | Registration and execution plane | **Approved as an administrative control.** |
| `StepRegistrationPolicy.egress_policy` | Required enum `none`, `restricted`, `unrestricted` | Registration and execution plane | **Approved as an administrative control.** It is authoritative over developer connectivity declarations. |
| `StepRegistrationPolicy.worker_pool_selector` | Required string-valued label map; values must be non-empty | Registration and execution plane | **Approved as an administrative control.** It is the authoritative pool selector, not `schedulingControls.affinity_labels`. |

## Output contract decision

The stable output envelope remains:

```json
{
  "Result": "step-specific payload",
  "StatusCode": 0,
  "StatusMessage": "concise summary",
  "ErrorMessage": ""
}
```

`Result`, including any step-specific nested object, is the only extensibility
point. Downstream expressions must continue to address the envelope fields
directly. The review approves this compatibility principle but requires the
schema and reference SDK to agree:

| Output field | Current shape | Disposition |
|---|---|---|
| `Result` | Required; object, string, array, or null in JSON Schema; reference SDK accepts arbitrary values | **Requires revision.** Choose the language-neutral JSON value set and make schema/runtime behavior identical. |
| `StatusCode` | Required integer, default `0`, range `0–255` | **Approved with revision.** Keep the numeric status, but document whether it is process status or a platform status and align retry semantics. |
| `StatusMessage` | Required string, default empty, max 500; docs recommend 200 | **Requires revision.** Choose one limit and define success/failure usage. |
| `ErrorMessage` | Required string, default empty, max 10000 | **Requires revision.** Keep diagnostics, but explicitly prohibit credential values and define scrubbing before persistence or display. |
| extra output fields | Rejected by `additionalProperties: false` in the wrapper | **Approved.** Step-specific data belongs in `Result`, not beside the envelope. |

## Mismatch and follow-up register

| ID | Mismatch or disagreement | Owner | Follow-up |
|---|---|---|---|
| M1 | Architecture presents outputs as `StandardOutputWrapper`, but the schema accepts `{}` and arbitrary objects. | SDK maintainers | Make `outputs` compose the wrapper and constrain extension to `Result`. |
| M2 | Architecture requires declared input validation at authoring and invocation, but the schema accepts opaque input objects and the Python base validates an independent model. | SDK maintainers | Add recursive Draft-07 meta-validation and connect invocation validation to the declared descriptor contract. |
| M3 | A current HTTP fixture treats an authorization header/token as ordinary runtime input. | SDK maintainers and canvas/workflow designer | Remove unsafe example behavior and define credential linting/binding guidance. |
| M4 | `DependencyDeclaration` is unreachable from the manifest schema and has no identified consumer. | SDK maintainers and registration owner | Remove the orphan definition unless a concrete registration contract requires it. |
| M6 | Architecture assigns retries to the execution plane, while the manifest exposes an unused retry policy. | Execution-plane owner | Remove/rehome, or publish a platform-wide retry protocol covering idempotency, status signaling, and timeout interaction. |
| M7 | Developer scheduling hints overlap administrator-owned worker-pool and egress controls. | Registration owner and execution-plane owner | Remove/rehome affinity; decide whether connectivity remains an advisory requirement. |
| M8 | Credential conditional rules are incomplete: list uniqueness, header paths, file paths, and mode-specific fields are not fully constrained. | SDK maintainers and execution-plane owner | Tighten schema conditionals and document presentation as non-authorizing. |
| M9 | Resource and timeout fields lack explicit author/admin precedence and cross-field semantics. | Registration owner and execution-plane owner | Decide whether they are SDK declarations or registration controls before stabilizing them. |
| M10 | The wrapper schema and Python implementation disagree on allowed `Result` values; status and retry code systems also differ. | SDK maintainers and execution-plane owner | Select one language-neutral result/status contract and update both schema and runtime in a later change. |
| M11 | Documentation describes a palette icon vocabulary while the schema only checks a pattern. | Canvas owner and SDK maintainers | Publish an icon registry or explicitly bless extension names. |
| M12 | Packaged descriptors retain source-relative schema references, while the package does not include the shared definitions needed to resolve them. | SDK maintainers | Package a self-contained descriptor/schema bundle, or dereference and validate every emitted input/output schema; add an artifact-level resolution test. |
| M13 | The reference path violates the non-disclosure guarantee: arbitrary authorization headers are accepted as inputs and the logger's shallow, case-sensitive redaction does not scrub nested headers. | SDK maintainers and execution-plane owner | Remove credential-bearing HTTP headers from workflow inputs; inject bound credentials out of band; implement recursive, case-insensitive redaction as defense in depth; add tests covering logs, errors, `Result`, and persisted payloads. |
| M14 | The architecture requires every category to expose `StandardOutputWrapper`, but the documented trigger lifecycle creates a workflow rather than yielding a downstream result. | SDK and control-plane owners | Define an explicit trigger envelope/lifecycle contract or record a documented exception before approving trigger descriptors. |
| M15 | Defaults are represented as schema annotations but are not materialized consistently; the HTTP manifest requires `method` while the Python model supplies a default independently. | SDK maintainers and canvas/workflow designer | Define default application ownership and ensure authoring, descriptor compilation, and invocation use the same default semantics. |
| M16 | The plugin runtime image is now a single immutable implementation boundary, but descriptor packaging and runtime-image contents must remain synchronized. | SDK maintainers and runtime-image owner | Add an artifact/runtime consistency check proving every targeted qualified step and required entrypoint is registered in the digest-pinned runtime image. |

## Review conclusion

The contract is fit to continue discovery and authoring work for plugin identity,
explicit targets, one immutable plugin runtime image, required per-step implementation
handles, qualified dispatch, step taxonomy, metadata, named credential requirements,
and the immutable output-envelope principle. It is not
ready to claim that every field is finalized. The release-blocking decisions are
the output-wrapper enforcement, recursive input-schema validation, credential
input separation, dependency ownership, and the ownership of
retry, resource, timeout, and scheduling declarations.
