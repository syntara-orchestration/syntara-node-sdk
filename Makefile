.PHONY: install test lint typecheck check

install:
	uv sync --locked --all-extras

test:
	uv run --no-sync --no-build pytest

lint:
	uv run --no-sync --no-build pre-commit run ruff --all-files

typecheck:
	uv run --no-sync --no-build pre-commit run mypy --all-files

check:
	uv run --no-sync --no-build pre-commit run --all-files
