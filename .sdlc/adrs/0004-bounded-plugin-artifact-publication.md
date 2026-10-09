# ADR 0004: Publish already-built plugin metadata as a bounded OCI artifact

- Status: Accepted
- Date: 2026-10-07

## Context

A plugin author needs a small, deterministic path from an SDK-built
`PluginArtifact` to a selected OCI repository so a catalog index can reference
the returned immutable digest. The path must work with a local Quay proof of
concept without silently becoming an image builder, general registry browser,
credential store, signing service, or catalog coordinator.

## Decision

`PluginArtifactPublisher` accepts only:

- one already-validated `PluginArtifact`;
- one `PluginArtifactPublicationTarget` with an explicit repository and
  channel; and
- optional invocation-scoped registry credentials.

It verifies the artifact's OCI manifest and every referenced descriptor before
uploading exactly the config, plugin-manifest, and content-bundle blobs. Only
after those payloads are present may it advance the selected channel to the
already-verified manifest. It inherits the same origin-pinned Bearer challenge
handling and loopback-only HTTP exception as `CatalogIndexPublisher`.

The successful result contains the repository, channel, immutable manifest
digest, and immutable repository reference. A caller that publishes a catalog
index must explicitly add that immutable digest to the index and provide the
correct predecessor digest; this publisher never reads or updates a catalog
index itself.

## Consequences

- A local Quay registry can hold a real, deterministic plugin metadata
  artifact that a catalog index references by digest.
- The catalog publisher and plugin publisher remain small, independently
  testable boundary adapters instead of a registry-management framework.
- The capability does not build or publish workload images, resolve tags,
  search/list repositories, sign artifacts, persist credentials, select trust
  policy, or install/execute a plugin.
- Signature verification and production publication policy remain control-plane
  concerns. The loopback HTTP allowance is only for an explicit local
  development target and does not weaken production source policy.
