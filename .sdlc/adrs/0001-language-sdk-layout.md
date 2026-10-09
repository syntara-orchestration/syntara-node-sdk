# ADR 0001: Separate language SDKs from shared contracts

- Status: Accepted
- Date: 2026-10-06

## Decision

Store the canonical plugin contracts in the repository-level `contracts/` directory. Store each language implementation under `sdks/<language>/`.

The current Python implementation uses `sdks/python/`. A future TypeScript implementation uses `sdks/typescript/`. The retired `sdk-python/` directory is not restored or reused.

`contracts/` contains the versioned schemas, conformance fixtures, and
language-neutral container ABI protobuf source. Language SDKs consume those
files and may package schemas/fixtures or generate their own protocol bindings,
but must not own copied or modified contract definitions.

## Context

The Plugin SDK is intended to support Python, TypeScript, and potentially other languages. Versioned manifest, runtime, and provider contracts must retain identical meaning in every language. Placing them beneath one language SDK makes that language appear to own a shared platform boundary and encourages contract drift.

## Consequences

- A language SDK owns its implementation code, build configuration, package metadata, tests, and language-specific documentation.
- Shared schemas and fixtures have one canonical source, reviewed independently of any SDK implementation.
- The Python `syntara-plugin-contracts` distribution packages the canonical schemas and pinned fixture corpus so Python callers can load them locally; its wheel remains self-contained for consumer conformance checks.
- A future TypeScript SDK consumes the same `contracts/` source and supplies its own package tooling and tests.
- The Python runtime generated bindings are implementation output beneath
  `sdks/python`; a future language SDK generates equivalent bindings from the
  canonical protobuf source rather than consuming Python files.
- Python distributions retain the published `syntara-plugin-*` names. Their clean-break import API is the shared `syntara_plugin` namespace: `syntara_plugin.sdk`, `syntara_plugin.runtime`, and `syntara_plugin.contracts`. This preserves distribution ownership while making the author-facing API concise.

## Layout

```text
contracts/
├── schemas/
├── fixtures/
└── proto/

sdks/
├── python/
│   ├── packages/
│   ├── tests/
│   └── README.md
└── typescript/
    └── README.md
```
