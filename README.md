# Syntara Plugin SDK

Build, validate, package, and publish Syntara plugins. A plugin is a
versioned declaration of workflow actions, triggers, integration types,
credential recipes, documentation, and—when needed—one custom workload image.

The SDK gives plugin authors one public command: `syntara-plugin`.

## Start here

```sh
# When the SDK is published:
python -m pip install syntara-plugin-sdk

# Create, validate, inspect, and package a plugin without contacting a registry.
syntara-plugin init ./my-plugin --namespace acme
cd ./my-plugin
syntara-plugin validate --settings syntara-plugin.yaml
syntara-plugin inspect --settings syntara-plugin.yaml
syntara-plugin build --settings syntara-plugin.yaml
syntara-plugin inspect ./dist/my-plugin.oci.tar
```

`init` creates a small plugin workspace and a non-secret
`syntara-plugin.yaml` settings file. The default build is deterministic and
offline: it writes a portable OCI metadata archive but does not build an image,
publish, install, or execute anything.

For a ready-to-read workspace, see [Hello World](examples/hello-world/).
Run it directly from a source checkout:

```sh
syntara-plugin validate examples/hello-world/plugin.yaml \
  --settings examples/hello-world/syntara-plugin.yaml
```

## Documentation

- [Installation](docs/installation.md) — install a released SDK or prepare a source checkout.
- [Getting started](docs/getting-started.md) — first plugin and the four core commands.
- [User guide](docs/user-guide.md) — settings, custom workloads, artifact publication, and catalog release.
- [Plugin language reference](docs/plugin-language.md) — each manifest kind and field, with links to its normative schema.
- [Build settings reference](docs/build-settings.md) — every `syntara-plugin.yaml` key and its behavior.
- [Developer guide](docs/developer-guide.md) — local setup, tests, contract changes, and contribution expectations.
- [Runtime and OCI model](docs/runtime-and-oci.md) — container ABI, artifact boundaries, and ownership.
- [Documentation index](docs/README.md) — the complete map, including design records and language-specific notes.

The normative `syntara.io/v1alpha1` schemas and conformance fixtures live in
[contracts/](contracts/). Every SDK must package and honor those contracts;
language implementations do not maintain private schema copies.

## Contributing

The repository contains language-neutral contracts plus the Python SDK,
runtime, and contract packages:

```text
contracts/                    # normative JSON Schema, fixtures, and protobuf ABI
examples/                     # small author-facing plugin workspaces
docs/                         # guides and language reference
sdks/python/packages/sdk/     # syntara-plugin-sdk and CLI
sdks/python/packages/runtime/ # workload runtime helpers
sdks/python/packages/contracts/ # packaged contract bundle
sdks/python/tests/            # Python tests
```

To work from a checkout, follow the [developer guide](docs/developer-guide.md).
In short: create the workspace environment, run `python -m pytest`, keep
schemas and fixtures synchronized, and add a runnable example when a user
facing workflow changes.

## Current scope

The SDK supports offline plugin packaging, bounded OCI publication, explicit
catalog updates, and a developer-preview Podman workload build. Artifact
signing, catalog refresh/recovery automation, and end-to-end Execution Plane
delivery of credentials to custom workloads remain follow-on work. See
[ADR 0006](.sdlc/adrs/0006-deferred-custom-workload-build-ux.md) for the
custom-workload preview boundary.
