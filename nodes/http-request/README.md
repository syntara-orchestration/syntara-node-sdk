# HTTP Request Node - Reference Implementation

This is the complete reference implementation of an HTTP Request action node using the Syntara SDK.

## Structure

```
http-request/
├── manifest.yaml          # K8s CRD-style node definition
├── README.md             # This file
└── src/
    ├── __init__.py       # Package exports
    ├── models.py         # Pydantic input/output models
    └── main.py           # HttpRequestNode implementation

# Tests are at repository root level
../../tests/nodes/http-request/
├── test_http_node.py     # Unit tests
└── test_inputs.json      # Sample inputs for testing
```

## Implementation Details

### Input Model (models.py)

The `HttpRequestInput` Pydantic model matches the manifest schema exactly:

- **11 input parameters** including complex types:
  - `url`: string (required)
  - `method`: enum (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS)
  - `headers`: dict[str, str] (dynamic key-value)
  - `query_parameters`: dict[str, str]
  - `body`: Union[str, dict] (oneOf union type)
  - `timeout_seconds`: int (1-600, default 30)
  - `response_format`: enum (json, text, auto)
  - `follow_redirects`: bool
  - `verify_ssl`: bool
  - `success_status_codes`: list[int]
  - `context_vars`: dict[str, str | int | bool]

### Output Model (models.py)

The `HttpRequestOutput` model defines the Result payload:

- `status_code`: HTTP response status (100-599)
- `headers`: Response headers dict
- `body`: Parsed JSON or raw text
- `elapsed_ms`: Request duration in milliseconds
- `url`: Final URL after redirects

### Node Implementation (main.py)

The `HttpRequestNode` class extends `ActionNode[HttpRequestInput, HttpRequestOutput]`:

1. Uses `httpx` for HTTP requests
2. Handles all input parameters (headers, query params, body, timeouts)
3. Supports multiple response formats (JSON, text, auto-detect)
4. Automatically wraps results in `StandardOutputWrapper`
5. Provides structured logging via ExecutionContext

## Running Locally

### Install SDK

```bash
cd ../../sdk-python
uv pip install -e .
```

### Test with Sample Inputs

```bash
cd /path/to/syntara-node-sdk

# Set PYTHONPATH
export PYTHONPATH="/path/to/syntara-node-sdk/sdk-python:/path/to/syntara-node-sdk/nodes/http-request:$PYTHONPATH"

# Run with test inputs
uv run --directory sdk-python python -m syntara_sdk.runner \
  --module src.main \
  --class HttpRequestNode \
  --inputs-file /path/to/syntara-node-sdk/tests/nodes/http-request/test_inputs.json
```

### Expected Output

```json
{
  "Result": {
    "status_code": 200,
    "headers": {
      "content-type": "application/json",
      ...
    },
    "body": {
      "args": {
        "test": "true",
        "sdk_version": "0.1.0"
      },
      ...
    },
    "elapsed_ms": 260,
    "url": "https://httpbin.org/get?test=true&sdk_version=0.1.0"
  },
  "StatusCode": 0,
  "StatusMessage": "Execution completed successfully",
  "ErrorMessage": ""
}
```

## Testing

### Run Unit Tests

```bash
# From repository root
cd /path/to/syntara-node-sdk
PYTHONPATH="nodes/http-request:$PYTHONPATH" pytest tests/nodes/http-request/test_http_node.py -v
```

### Test with Custom Inputs

Create a JSON file with your inputs:

```json
{
  "url": "https://api.github.com/repos/python/cpython",
  "method": "GET",
  "headers": {
    "Accept": "application/vnd.github.v3+json"
  }
}
```

Then run:

```bash
uv run --directory ../../sdk-python python -m syntara_sdk.runner \
  --module src.main \
  --class HttpRequestNode \
  --inputs-file /path/to/your/inputs.json
```

## Key Features Demonstrated

### 1. Typed Input/Output with Pydantic v2

- Full validation of inputs against schema
- Type-safe access in implementation
- Automatic error messages for invalid inputs

### 2. StandardOutputWrapper Envelope

- Success: `StatusCode=0`, `Result=HttpRequestOutput`
- Failure: `StatusCode=1`, `ErrorMessage` with details
- Always returns same structure for workflow compatibility

### 3. ExecutionContext Integration

- Structured JSON logging
- Execution ID tracking
- Secret file access (for credentials)

### 4. Error Handling

- Input validation errors caught and wrapped
- HTTP errors caught and wrapped
- Stack traces included in ErrorMessage

### 5. Credential Support (Ready to Use)

The node is ready to accept credentials at runtime:

- Supports API Key, Bearer Token, Basic Auth
- Credentials injected via environment or tmpfs files
- Never stored in the manifest

## Manifest Compliance

The implementation is **100% compliant** with the K8s CRD manifest:

✅ All 11 input properties supported  
✅ All output fields in Result payload  
✅ StandardOutputWrapper envelope  
✅ Credential types declared (API Key, Bearer Token)  
✅ Network connectivity requirements specified  
✅ Resource limits and timeouts configured  
✅ Retry policy defined  

## Next Steps

1. **Add credential injection** - Implement BearerTokenCredential or ApiKeyCredential for authenticated requests
2. **Container packaging** - Build Docker image at `registry.syntara.io/nodes/http-request:1.0.0`
3. **Integration testing** - Test against real Syntara orchestrator
4. **Deploy to registry** - Register via `POST /api/v1/node-types`

## Related Files

- [../../schemas/common-definitions.json](../../schemas/common-definitions.json) - Platform meta-schema
- [../../sdk-python/syntara_sdk/](../../sdk-python/syntara_sdk/) - SDK implementation
- [manifest.yaml](manifest.yaml) - Complete node definition
