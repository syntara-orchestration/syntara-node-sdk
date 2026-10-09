.PHONY: install test lint check generate-container-protocol

install:
	uv sync --locked --all-groups

test:
	uv run --no-sync pytest sdks/python/tests -q

lint:
	uv run --no-sync pre-commit run ruff --all-files

check:
	uv run --no-sync pre-commit run --all-files

generate-container-protocol:
	uv run --no-sync python -m grpc_tools.protoc \
		--proto_path=contracts/proto \
		--python_out=sdks/python/packages/runtime/src \
		--grpc_python_out=sdks/python/packages/runtime/src \
		contracts/proto/syntara_plugin/runtime/protocol/container.proto
