# Syntara Plugin SDK

This repository is the workspace for the public Syntara plugin authoring toolchain.

## Packages

```text
contracts/                    # Language-neutral schemas, fixtures, and ABI source

sdks/
└── python/
    ├── packages/
    │   ├── sdk/       # syntara-plugin-sdk -> syntara_plugin.sdk
    │   ├── runtime/   # syntara-plugin-runtime -> syntara_plugin.runtime
    │   └── contracts/ # syntara-plugin-contracts -> syntara_plugin.contracts
    └── tests/
```

- `syntara-plugin-contracts` owns versioned JSON Schema/OpenAPI contracts, deterministic contract bundles, the normative generic-container request-hash rule, and the language-neutral `ContainerService` protobuf source.
- `syntara-plugin-runtime` owns the minimal runtime-facing interfaces and generated bindings for its language. Its generic container runtime dispatches a selected immutable step revision to one action callable inside a plugin image.
- `syntara-plugin-sdk` owns typed/YAML authoring, deterministic compilation, offline assembly of metadata-only OCI plugin artifacts and catalog indexes, bounded publication of already-built plugin and catalog-index artifacts, and a small offline authoring CLI. Image building, signing, and catalog-index coordination remain later increments.

The repository groups implementation by language so future SDKs can live beside Python under `sdks/typescript/`, `sdks/go/`, and similar directories. Python distributions retain the published `syntara-plugin-*` names, while their clean-break public imports share the `syntara_plugin` namespace: `.sdk`, `.runtime`, and `.contracts`.

`contracts/` is the source of truth for versioned schemas, conformance fixtures, and the container ABI protobuf source. Language SDKs package or generate from those files; they do not own copies of them. [ADR 0001](.sdlc/adrs/0001-language-sdk-layout.md) records this repository-layout decision.

The initial contract is `syntara.io/v1alpha1`. A plugin root names explicit action and trigger target files. Action and trigger targets are separate contracts, and all schema references resolve from the packaged local bundle.

## Action runtime choice

An action makes one clear runtime choice:

- A Syntara-managed action uses `runtime.kind: platform-runner` and declares a versioned driver such as `http.v1`. It must not name an image or ABI. `http.v1` additionally requires a bounded declarative operation: an HTTP method, an origin-less relative path template, and optional field-to-JSON-Pointer-or-literal request/response maps. During installation, Syntara maps the driver to an administrator-approved, immutable runner profile.
- A publisher-supplied action uses `runtime.kind: custom-workload`. It must not declare a driver; its one plugin-level workload binding supplies the executable image and ABI through the signed artifact.

This lets an author describe a GitHub request without choosing Syntara's container image, while retaining an explicit image boundary for code that the publisher actually owns.

`syntara_plugin.runtime.HttpOperationMapper` is the shared, pure interpreter
for that operation shape. It builds a relative request path and JSON body or
projects a parsed response; it never selects an endpoint, reads a credential,
or performs HTTP. Author-supplied path templates cannot contain a percent
escape. Trusted string input is interpolated as one percent-encoded path
segment after rejecting separators, pre-encoded values, query/fragment
characters, and dot segments.

## Offline OCI artifact assembly

`syntara_plugin.sdk.build_plugin_artifact()` turns successful compiler output
into a byte-for-byte deterministic, metadata-only OCI artifact. It produces a
canonical plugin-metadata layer, a fixed-metadata gzip/tar content bundle for
externalized schema and `http.v1` mapping assets plus optional UTF-8 Markdown documentation, and a
config blob that records every bundled asset's normalized path, typed-source
reference, media type, exact source-byte digest, byte size, and canonical
parsed-document digest. It performs no registry, signing, image
build, credential, or network operation.

An author includes one plugin-level document with an ordinary workspace path:

```yaml
spec:
  documentation:
    path: docs/README.md
```

The compiler accepts only contained regular UTF-8 `.md` files without NUL
bytes. It records the exact SHA-256 digest in the canonical descriptor and the
asset index; the same bytes enter the deterministic content bundle. The future
catalog reader must verify that binding before it offers the document to users.

This is intentionally an in-process API first. The CLI, later local service,
IDE, signer, and registry adapters must call this same API rather than
reimplementing artifact layout or digest calculation.

## Offline authoring CLI

The Python SDK package provides a deliberately small `syntara-plugin` command.
It creates one safe, reviewable YAML workspace, delegates all source
interpretation to the public compiler API, and provides explicit OCI artifact
build and publication operations:

```sh
syntara-plugin init ./my-plugin --namespace acme
syntara-plugin validate ./my-plugin/plugin.yaml
syntara-plugin inspect ./my-plugin/plugin.yaml > descriptor.json
syntara-plugin build ./my-plugin/plugin.yaml --json
printf '%s' "$REGISTRY_PASSWORD" | syntara-plugin publish ./my-plugin/plugin.yaml \
  --registry-origin https://registry.example.test \
  --repository acme/plugins/my-plugin --channel 0.1.0 \
  --username publisher --password-stdin
```

`init` never overwrites an existing path. `validate` reports the compiler's
stable diagnostics, while `inspect` writes the exact canonical descriptor that
the artifact builder would use. `build` performs no network operation and
reports the config, descriptor, and content-bundle digests of the resulting
OCI plugin artifact. `publish` requires every destination coordinate
explicitly, reads a password only through standard input, retains it only for
that process, and prints the immutable result reference. It never resolves an
image tag, builds a workload image, signs an artifact, discovers repositories,
or stores credentials. HTTP publication requires the explicit
`--allow-insecure-loopback-http` switch and is restricted by the SDK to local
loopback addresses.

## Bounded OCI publication

`PluginArtifactPublisher` and `CatalogIndexPublisher` are intentionally narrow
registry adapters for already-built artifacts. The plugin publisher uploads the
plugin config, canonical descriptor, and content bundle. The catalog publisher
uploads the catalog config and catalog-index content. Each advances only one
explicitly selected channel after all immutable blobs are present.

They do not compile source, build a workload image, sign an artifact, discover
repositories, read a catalog's current channel, or store a registry credential.
That separation makes an artifact digest reviewable before the next operation
uses it.

The target uses HTTPS by default. The only HTTP exception requires the explicit
`allow_insecure_loopback_http=True` option and one of the local development
origins (`localhost` or `127.0.0.1`). A registry Bearer challenge is followed
only when its token endpoint has the same origin as the selected registry; the
publisher keeps the supplied Basic credential and exchanged Bearer value in
memory for the one invocation.

```python
from syntara_plugin.sdk import (
    PluginArtifactPublicationTarget,
    PluginArtifactPublisher,
    CatalogIndexPublicationTarget,
    CatalogIndexPublisher,
    RegistryCredentials,
)

plugin_publication = PluginArtifactPublisher(
    PluginArtifactPublicationTarget(
        registry_origin="https://registry.example.test",
        repository="acme/plugins/github",
        channel="0.1.0",
    ),
    credentials=RegistryCredentials("publisher", password),
).publish(plugin_artifact)

publication = CatalogIndexPublisher(
    CatalogIndexPublicationTarget(
        registry_origin="https://registry.example.test",
        repository="acme/catalog-index",
        channel="stable",
    ),
    credentials=RegistryCredentials("publisher", password),
).publish(catalog_artifact)

print(publication.immutable_reference)
```

The catalog entry uses `plugin_publication.manifest_digest`, never its mutable
channel. On an index update, the authoring or CI workflow must also build the
next catalog document with the accepted predecessor digest in
`metadata.previousIndexDigest`; the publisher intentionally does not read or
guess it.

The `metadata.sourceId` within `catalog_artifact` is the stable source identity
that the Syntara control plane will configure. They must be equal:
Syntara rejects an artifact published for a different source rather than
allowing one catalog channel to be replayed by another source. Local Quay is a
development-only unsigned exception; it proves catalog discovery and safe
documentation hydration, never plugin installation or execution, and never
changes production signing or HTTPS requirements.

## Development

Use the shared project environment:

```zsh
source /Users/gnalawad/Documents/projects/ao/github/.venv/bin/activate
uv sync --all-groups --active --inexact
python -m pytest
```

Each repository retains its own `pyproject.toml` and `uv.lock`; `--inexact` keeps shared-environment dependencies from sibling repositories intact.

## Installation

When the SDK is released, a plugin author installs one public Python package.
The contracts and Python runtime are normal transitive dependencies; authors do
not install or select them individually:

```zsh
uv tool install syntara-plugin-sdk
# or, inside an existing Python environment:
python -m pip install syntara-plugin-sdk
```

For a contributor working from this repository, one workspace command installs
the editable distributions and exposes the same CLI:

```zsh
uv sync --all-packages --active --inexact
syntara-plugin --help
```

## Container runtime protocol

The container ABI is the application-data channel between the Execution Plane
and an isolated plugin workload. One plugin image can register more than one
immutable step revision. For example, `github.create-issue.v1` and
`github.close-issue.v1` may share a GitHub plugin image, while each workflow
step invocation selects exactly one of those revisions.

The request contains the selected step revision, a bounded JSON input object,
an optional bounded non-secret runtime context, the timeout, and paths to
credential files already mounted by the Execution Plane. It never contains a
command, image reference, endpoint, or plaintext secret. For example, the
`http.v1` runner context contains its resolved operation and output-schema
digest, not an HTTP origin or authorization header. The protocol reserves
bounded progress and requires exactly one structured result or failure. The
current Python dispatcher implements safe terminal results, failures, health,
and cancellation; progress-producing action interfaces are a follow-on
addition. The control plane and Execution Plane retain image routing,
credential issuance, transport security, and workload-network policy.

The canonical protobuf source is
`contracts/proto/syntara_plugin/runtime/protocol/container.proto`. Regenerate
the Python binding after changing it:

```zsh
make generate-container-protocol
python -m pytest sdks/python/tests/runtime/test_container_protocol.py
```

Generated bindings belong under the language runtime package. A future
TypeScript SDK generates its own binding from the same canonical proto rather
than copying Python output.
