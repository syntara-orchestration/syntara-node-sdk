# Python SDK

This directory contains the Python implementation of the Syntara Plugin SDK.

- `packages/sdk/` provides Python authoring, compilation, and deterministic offline OCI-artifact assembly APIs.
- `packages/runtime/` provides Python runtime ABI helpers.
- `packages/contracts/` packages the canonical repository-level contracts for Python callers.
- `tests/` contains Python-specific tests.

The three distributions share the `syntara_plugin` namespace. Plugin authors
import the public APIs as `syntara_plugin.sdk`, `syntara_plugin.runtime`, and
`syntara_plugin.contracts`. The runtime's `abi` module contains the workload
and provider ABI helpers; it does not contain the language-neutral contracts.
Each distribution declares its typed public API with a PEP 561 `py.typed`
marker, so strict Python consumers can type-check these imports without local
stub files.

The canonical schemas and conformance fixtures are in [../../contracts](../../contracts). Do not create language-local copies of those files.

The canonical container protobuf source is also in `../../contracts`. The
Python runtime package contains generated protobuf bindings plus a small public
API for registering several action callables in one workload image, serving the
container ABI, and invoking it from a trusted adapter. The API exposes only
structured JSON data, a bounded non-secret runtime context, and mounted
credential-file paths; it neither selects an image nor reads credential
contents.

It also exposes `HttpOperationMapper`, a pure interpreter for an installed
`http.v1` operation. It constructs only a method, origin-less relative path,
and optional JSON body, or projects declared fields from an already parsed
response. Endpoint selection, HTTP I/O, credentials, retry, and logging remain
the responsibility of a Syntara-managed runner.

`load_http_runner_context()` validates the runtime-only `http.v1` context that
Syntara sends after resolving an installed action. It accepts only the driver,
resolved operation, and output-schema digest. A managed runner must obtain its
endpoint and credentials through separate trusted integration and broker paths.

Regenerate the Python bindings from the repository root after changing the
canonical source:

```zsh
make generate-container-protocol
```

The Python contracts package exposes `load_bundle()` for the complete immutable
schema bundle, `load_fixture_bundle()` for the matching pinned conformance
corpus, and `validate_catalog_index()` for the pure replay, expiry,
source-binding, predecessor, and contract-version checks used by catalog
consumers. It also exposes `container_workload_request_digest()` as the
reference implementation for the generic work-item hash: strict canonical JSON
with the two mirrored `requestHash` fields omitted. The catalog fixture bundle
remains data-only: registry resolution, OCI signature verification,
persistence, and installation belong to later Syntara control-plane increments.

After compiling a workspace, an authoring client may call
`syntara_plugin.sdk.build_plugin_artifact(result)`. The resulting
`PluginArtifact` has the immutable OCI manifest digest plus config, canonical
plugin-metadata, and content-bundle blobs ready for a separate signer or
registry client. The builder is offline and performs no signing, publication,
or image resolution. For every `kind: asset` schema or `http.v1` mapping
source, it preserves the exact bounded source bytes in the bundle and records
its typed-source reference plus source-byte and canonical-document digests in
the config inventory. Inline documents remain in the canonical metadata layer.

## Offline authoring command

The `syntara-plugin-sdk` distribution installs the `syntara-plugin` command:

```zsh
syntara-plugin init ./my-plugin --namespace acme
syntara-plugin validate ./my-plugin/plugin.yaml --json
syntara-plugin inspect ./my-plugin/plugin.yaml > descriptor.json
```

It is a thin adapter over `compile_workspace()`: it has no registry, image
engine, signer, network, or credential behavior. It can also be invoked from a
source checkout with `python -m syntara_plugin.sdk.cli`.
