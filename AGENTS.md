# AGENTS.md

Use `uv sync --locked --group dev` to prepare dependencies. Before completing a change, run
`PYTHONPATH=sdk-python:tools uv run --no-sync --no-build pytest` and
`uv run --no-sync --no-build pre-commit run --all-files`.
