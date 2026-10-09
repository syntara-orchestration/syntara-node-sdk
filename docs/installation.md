# Installation

The released Python distribution installs the `syntara-plugin` command and its
contract dependencies together.

## Install a released SDK

Use one of these commands after the package is published:

```sh
uv tool install syntara-plugin-sdk
# or
python -m pip install syntara-plugin-sdk
```

Verify the installation:

```sh
syntara-plugin --help
```

Use `uv tool upgrade syntara-plugin-sdk` or your normal Python dependency
management process to update the SDK. The installed package is for authors;
you do not need a Syntara server, Podman, or registry to validate and package a
credentialless plugin.

## Work from the repository

For an unreleased SDK checkout or a contribution, create the development
environment from the repository root:

```sh
uv venv
source .venv/bin/activate
uv sync --all-groups --active --inexact
syntara-plugin --help
```

Run the focused test suite before changing SDK behavior:

```sh
python -m pytest sdks/python/tests -q
```

Continue with [getting started](getting-started.md) to create a plugin, or use
the [developer guide](developer-guide.md) for contract and contribution work.
