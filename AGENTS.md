# AGENTS.md

Use `uv` for dependency management. Before completing a change, run `uv sync --locked --all-extras`,
`uv run --no-sync --no-build pytest`, and `uv run --no-sync --no-build pre-commit run --all-files`.
