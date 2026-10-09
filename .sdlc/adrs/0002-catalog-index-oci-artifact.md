# ADR 0002: Publish catalog indexes as OCI artifacts

- Status: Accepted
- Date: 2026-10-06

## Context

An administrator configures Syntara with one catalog-index repository and a
movable channel, such as `stable`. The channel must resolve to an immutable,
signed catalog index before Syntara can discover plugin artifacts. The SDK
therefore needs a portable, deterministic catalog-index representation before
adding registry transport, signing, or catalog reconciliation.

## Decision

The SDK represents one validated `CatalogIndex` as an OCI image-manifest
artifact with these versioned media types:

- artifact type: `application/vnd.syntara.catalog-index.v1`
- config: `application/vnd.syntara.catalog-index.config.v1+json`
- content layer: `application/vnd.syntara.catalog-index.content.v1+json`

The catalog content layer is canonical JSON. The config records its digest,
the shared contract-bundle digest, source identifier, generation, and entry
count. The OCI manifest is the immutable subject that a publication adapter
signs. The SDK's bounded catalog-index publisher uploads the blobs by digest
and advances a selected channel only after the immutable artifact is present.
Signing remains a separate explicit operation.

## Consequences

- SDK callers can produce the same catalog artifact from the same document on
  every supported platform without registry access.
- The control plane can verify the exact artifact type and descriptor layout
  before parsing catalog content.
- Registry upload, signature issuance and verification, repository-scope
  checks, channel updates, and persisted replay checks remain separate mutable
  concerns. The bounded publisher owns only catalog-index upload/channel
  advancement; it is deliberately not hidden in the artifact builder.
- Changing an artifact, config, or content media type requires a new versioned
  type rather than a silent interpretation change.
