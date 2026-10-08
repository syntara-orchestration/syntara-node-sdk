# ADR 0006: Defer combined custom-workload image builds until catalog flow is proven

- Status: Accepted — deferred implementation
- Date: 2026-10-07

## Context

The current SDK has a safe separation of responsibilities. `syntara-plugin
build` compiles a plugin workspace and writes a reviewable metadata OCI archive.
`syntara-plugin publish` uploads that exact archive. Neither command builds or
pushes executable workload images.

That separation is deliberate, but a custom-workload author eventually needs a
short developer command that builds the author-owned container image, obtains
its immutable registry digest, and produces metadata pinned to that digest.
The same author should be able to put stable non-secret defaults in a settings
file instead of repeating them on every command line.

The local GitHub proof is a declarative `platform-runner` plugin, so it does
not exercise an author-owned workload image. The catalog source, browse,
documentation, installation, and workflow-builder path must be proven before
the SDK gains a container-build orchestration feature.

## Decision

Do not implement combined workload-image construction before all of these are
proven:

- the local catalog UI can configure a source, reconcile a catalog index,
  browse a plugin, render its documentation, and install a selected immutable
  version; and
- a minimal `custom-workload` plugin can run through the Execution Plane from
  one pinned image, using the shared container ABI.

After those gates, add an opt-in convenience path to the existing CLI. A
custom-workload author can use one command such as:

```bash
syntara-plugin build plugin.yaml --with-workload --verbose
```

The command must visibly perform these separate operations:

1. Validate the plugin source and its custom-workload requirements.
2. Build the author-owned OCI workload image through an explicitly selected
   local container engine; the first adapter is Podman.
3. Push that image to the configured repository and read the registry-returned
   immutable digest.
4. Build the normal plugin metadata OCI archive with the workload image bound
   to that exact `repository@sha256:...` reference.
5. Report the runtime-image digest, metadata-artifact digest, archive path,
   selected platform, and output repository. `--verbose` streams the delegated
   container-engine output; default output remains a short phase/result summary.

The feature must use one versioned, language-neutral settings model. Semantic
CLI options map one-to-one to that model and override selected settings. The
settings-file search order is:

1. the explicit `--settings` path;
2. `.syntara-plugin.yaml` in the current working directory;
3. `.syntara-plugin.yaml` beside the selected plugin manifest; then
4. safe SDK defaults.

The first matching settings file wins; settings files are not merged. Runtime
flags such as `--verbose`, `--json`, and `--dry-run`, plus secret transport
such as `--password-stdin`, remain invocation-only. Settings files must reject
passwords, access tokens, private keys, registry auth-file paths, and any other
secret value. The image platform must be explicit or sourced from an approved
settings value; a laptop's default operating system or architecture is never a
safe Execution Plane target.

The existing metadata-only `build` command remains offline and unchanged unless
`--with-workload` is selected. `publish` remains a separate explicit operation
for the metadata archive. The convenience path does not sign artifacts, create
or update a catalog index, install a plugin, or execute a workload.

## Consequences

- Custom-workload authors will eventually use a concise command without losing
  visibility of the two distinct OCI outputs.
- The explicit current `--image-binding` path remains available for CI and
  advanced integrations. It is not removed merely because the convenience path
  exists.
- The first implementation supports Podman only. Additional container engines
  require a separate adapter, compatibility tests, and a documented security
  review.
- The settings schema, CLI, Python API, future gRPC service, LSP, and VS Code
  extension must share the same typed validation and precedence rules.
- Local loopback HTTP remains an explicit development-only setting. Production
  settings require HTTPS and do not gain an insecure default.

## Implementation and cleanup gate

Before enabling the feature, add unit, integration, and manual tests covering
settings discovery/precedence, schema validation, no-secret enforcement,
Podman command construction, target-platform validation, image-push digest
capture, metadata image binding, verbose/redacted output, cancellation, and
failure cleanup. Prove an end-to-end custom-workload run through the Execution
Plane and an installed catalog version.

When that path is accepted, remove any temporary demo wrapper or duplicate
manual build/push instruction that it supersedes. Do not remove the explicit
metadata-only or explicit-image-binding paths until the combined path has
equivalent CI, offline, error, and security coverage.
