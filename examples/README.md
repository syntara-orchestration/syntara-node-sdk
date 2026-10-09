# SDK examples

Examples are small complete plugin workspaces. They are intentionally safe to
validate and package without a registry, a container engine, or credentials.

| Example | What it demonstrates |
| --- | --- |
| [Hello World](hello-world) | One credentialless `platform-runner` action, an asset-backed input schema, documentation, and build settings. |

Start with [Hello World](hello-world). Its directory is also the command
working directory:

```sh
cd examples/hello-world
syntara-plugin validate --settings syntara-plugin.yaml
syntara-plugin build --settings syntara-plugin.yaml
syntara-plugin inspect dist/hello-world.oci.tar
```
