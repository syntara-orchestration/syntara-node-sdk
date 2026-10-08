# AGENTS.md

## Python SDK maintenance

- Treat the root `pyproject.toml` and `uv.lock` as the source of truth for supported Python
  versions, dependencies, linting, typing, and tests. Regenerate the lockfile whenever dependency
  metadata changes.
- Use `uv` for dependency management and Python tooling. Keep runtime dependencies limited to
  packages required by the shipped SDK or CLI.
- Add type annotations to new or changed production code and keep it clean under the configured
  strict mypy checks. Validate untrusted data at system boundaries.
- Add deterministic pytest coverage for behavior changes. Mock HTTP with `respx`, use temporary
  paths for filesystem tests, and clearly identify any test needing PostgreSQL, a network service,
  or a cluster as an integration test.
- Use `make install` to prepare dependencies. Before completing a change, run the relevant test
  target and `make check`.
