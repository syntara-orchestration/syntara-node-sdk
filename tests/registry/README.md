# Node Registry API Tests

These tests verify the **platform's Node Registry REST API** (`/api/v1/node-types`).

## What They Test

These are **platform-level tests**, not node-specific tests. They verify:

- **Manifest validation** - YAML schema validation against `schemas/common-definitions.json`
- **Compilation pipeline** - `manifest.yaml` → `node-definition.json`
- **PostgreSQL storage** - JSONB column, DDL CHECK constraints, GIN indexing
- **REST API contract** - `{data, meta}` envelope, pagination, filtering (`GET /api/v1/node-types`)
- **Registration endpoint** - Publishing nodes (`POST /api/v1/node-types`)
- **Canvas integration** - `?view=palette` and `/descriptor` endpoints for UI
- **Upsert behavior** - Re-publishing same (name, version) updates in place
- **Name-addressable lookups** - Fetching by UUID or node name
- **DDL constraints** - Container nodes must have `image_ref`, in_process must not

## Test Files

- **`test_postgres_registry.py`** (770 lines) - Complete registry prototype with 9 test cases
- **`test_register.py`** - Registration validation tests  
- **`test_integration.py`** - End-to-end integration tests

## Example Node Used

These tests use **`nodes/http-request/manifest.yaml`** as an example node, but they're testing the **registry/platform layer**, not the HTTP request node itself.

Any valid node manifest could be used - the tests verify the platform correctly:
1. Validates the manifest against the schema
2. Compiles it to a descriptor
3. Stores it in PostgreSQL
4. Advertises it via REST API

## Run Tests

```bash
cd tests/registry
uv run test_postgres_registry.py

# Expected output:
# ✓ test_register_http_request_succeeds
# ✓ test_palette_summary_matches_ui_contract
# ✓ test_list_envelope_matches_documented_contract
# ✓ test_fetch_record_by_id_and_by_name
# ✓ test_canvas_descriptor_exposes_inputs_and_output_envelope
# ✓ test_check_constraint_rejects_container_without_image_ref
# ✓ test_register_same_version_is_idempotent_upsert
# ✓ test_get_unknown_node_returns_404
# ✓ test_register_rejects_invalid_manifest
#
# 9 passed, 0 skipped, 0 failed
```

## PostgreSQL Testing

By default, tests use SQLite in-memory. To test against real PostgreSQL:

```bash
export SYNTARA_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/syntara_test
uv run test_postgres_registry.py
```

This tests the real JSONB column type and DDL constraints.

## Contrast with Node Tests

| Registry Tests (here) | Node Tests (`nodes/*/tests/`) |
|----------------------|-----------------------------------|
| Test the **platform** | Test the **node implementation** |
| API endpoints, storage | Business logic, I/O handling |
| Use example manifests | Use real inputs/outputs |
| Platform developers | Node authors |

## See Also

- [../../schemas/common-definitions.json](../../schemas/common-definitions.json) - Platform meta-schema
- [../../nodes/http-request/](../../nodes/http-request/) - Example node used in tests
- [../../docs/architecture.md](../../docs/architecture.md) - Registry architecture documentation
