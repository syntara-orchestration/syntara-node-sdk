# ADR 0003: Keep catalog-index publication bounded and registry-origin pinned

- Status: Accepted
- Date: 2026-10-07

## Context

The SDK can assemble a deterministic OCI catalog-index artifact offline. A
developer and local CI need to publish that artifact to a selected catalog
repository, including registries such as local Quay that use the OCI Bearer
challenge flow. That convenience must not turn the SDK into a general registry
client, image builder, credential store, or signing system.

## Decision

`CatalogIndexPublisher` accepts an already-validated `CatalogIndexArtifact`,
one `CatalogIndexPublicationTarget`, and optional invocation-scoped registry
credentials. It may:

- upload only the artifact's existing config and catalog-index blobs;
- advance only the explicitly selected repository/channel after both blobs are
  present;
- use HTTPS by default, allowing HTTP only for an explicitly enabled loopback
  development target; and
- exchange Basic credentials for an OCI Bearer token only after a `401`
  challenge whose token realm has the exact configured registry origin.

Credentials and exchanged Bearer values remain in memory and are not logged,
stored, returned, or included in `CatalogIndexPublication`.

## Consequences

- Local Quay can host a real SDK-produced catalog index without relaxing the
  control plane's production HTTPS/signature policy.
- Publication refuses off-origin upload locations and token realms, malformed
  token responses, non-canonical artifact bytes, and arbitrary HTTP registries.
- The publisher does not publish workload images, resolve floating tags, sign
  content, list registries, or edit an index from concurrent publisher state.
  Bounded publication of an already-built plugin metadata artifact is a
  separate capability defined in ADR 0004.
- The catalog document's `metadata.sourceId` remains bound to the Syntara
  source configuration. A channel cannot be shared across unrelated source
  identities without publishing a matching immutable catalog artifact.
