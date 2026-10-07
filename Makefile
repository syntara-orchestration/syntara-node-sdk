.PHONY: generate-container-protocol

generate-container-protocol:
	uv run --active python -m grpc_tools.protoc \
		--proto_path=contracts/proto \
		--python_out=sdks/python/packages/runtime/src \
		--grpc_python_out=sdks/python/packages/runtime/src \
		contracts/proto/syntara_plugin/runtime/protocol/container.proto
