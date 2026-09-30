# Terraform Enterprise SDK nodes

28 independently registerable Syntara `action` nodes, sharing one Python
implementation and one container image. Each node subclasses the SDK's
`ActionNode`, validates typed inputs, and returns `StandardOutputWrapper`.

## Layout

- `manifests/`: one validated `NodeType` descriptor per operation.
- `tfe_nodes/models.py`: input validation and result model.
- `tfe_nodes/catalog.py`: operation names, paths, and resource types.
- `tfe_nodes/nodes.py`: JSON:API bodies, composite operations, SDK classes.
- `tfe_nodes/client.py`: authenticated API calls, uploads, safe diagnostics.
- `tfe_nodes/runner.py`: optional JSON stdin/stdout container adapter.
- `tests/`: offline HTTP contract tests using `httpx.MockTransport`.

## Operations

Node names are `tfe_` followed by the operation below. Each manifest selects
its operation through `spec.execution.entrypoint`. All paths below are relative
to the TFE origin's `/api/v2` prefix.

| Domain | Operation | Requests |
| --- | --- | --- |
| Workspace | `create_workspace` | POST `/organizations/{organization}/workspaces` |
| Workspace | `list_workspaces` | GET `/organizations/{organization}/workspaces` |
| Workspace | `update_workspace_settings` | PATCH `/workspaces/{workspace_id}` |
| Workspace | `delete_workspace` | POST `/workspaces/{workspace_id}/actions/safe-delete`; DELETE `/workspaces/{workspace_id}` only with `force: true` |
| Workspace | `fetch_state_and_outputs` | GET `/workspaces/{workspace_id}/current-state-version`, then GET `/state-versions/{id}/outputs` |
| Variables | `add_variable` | POST `/workspaces/{workspace_id}/vars` |
| Variables | `list_variables` | GET `/workspaces/{workspace_id}/vars` |
| Variables | `update_variable` | PATCH `/workspaces/{workspace_id}/vars/{variable_id}` |
| Variables | `delete_variable` | DELETE `/workspaces/{workspace_id}/vars/{variable_id}` |
| Configuration | `upload_configuration_version` | POST `/workspaces/{workspace_id}/configuration-versions`, then PUT the returned upload URL |
| Run | `trigger_run` | POST `/runs` |
| Run | `get_run_status` | GET `/runs/{run_id}`, optionally GET `/runs/{run_id}/plan` |
| Run | `apply_run` | POST `/runs/{run_id}/actions/apply` |
| Run | `discard_run` | POST `/runs/{run_id}/actions/discard` |
| Run | `cancel_run` | POST `/runs/{run_id}/actions/cancel` |
| Run | `force_cancel_run` | POST `/runs/{run_id}/actions/force-cancel` |
| Run | `list_runs_for_workspace` | GET `/workspaces/{workspace_id}/runs` |
| Run | `add_run_comment` | POST `/runs/{run_id}/comments` |
| VCS | `list_github_installations` | GET `/github-app/installations` |
| VCS | `get_installation_details` | GET `/github-app/installation/{github_app_installation_id}` |
| VCS | `link_vcs_to_workspace` | GET installation details, then PATCH `/workspaces/{workspace_id}` |
| Project | `create_project` | POST `/organizations/{organization}/projects` |
| Project | `list_projects` | GET `/organizations/{organization}/projects` |
| Project | `get_project_details` | GET `/projects/{project_id}`, then GET `/team-projects?filter[project][id]={project_id}` |
| Project | `update_project_settings` | PATCH `/projects/{project_id}` |
| Project | `delete_project` | DELETE `/projects/{project_id}` |
| Project | `move_workspace_to_project` | PATCH `/workspaces/{workspace_id}` with a project relationship |
| Project | `assign_team_permissions` | POST `/team-projects` with project and team relationships |

The GitHub routes deliberately use the paths in HashiCorp's
[GitHub App installations reference](https://developer.hashicorp.com/terraform/cloud-docs/api-docs/github-app-installations):
the JSON:API resource type is `github-app-installations`, but that is not its URL.
Other payload references:
[workspaces](https://developer.hashicorp.com/terraform/cloud-docs/api-docs/workspaces),
[variables](https://developer.hashicorp.com/terraform/cloud-docs/api-docs/workspace-variables),
[configuration versions](https://developer.hashicorp.com/terraform/cloud-docs/api-docs/configuration-versions),
[runs](https://developer.hashicorp.com/terraform/cloud-docs/api-docs/run),
[comments](https://developer.hashicorp.com/terraform/cloud-docs/api-docs/comments),
[projects](https://developer.hashicorp.com/terraform/cloud-docs/api-docs/projects),
and [project team access](https://developer.hashicorp.com/terraform/cloud-docs/api-docs/project-team-access).

## Inputs and credentials

Every node requires `base_url` (HTTPS origin or origin plus `/api/v2`) and
`credential_id` (UUID reference). `timeout_seconds` defaults to 30 per request.
The execution plane must resolve that credential and supply its token through
the transient `credentials.token` field or mount it at `/run/secrets/tfe_token`.
The node cannot resolve a Syntara credential UUID itself. Integration lookup,
workflow defaults, authorization, and endpoint/egress policy remain platform
responsibilities. TLS verification stays enabled; an enterprise CA can be
provided using the HTTP client's standard `SSL_CERT_FILE` environment setting.

Container invocation example, with an already mounted token:

```json
{
  "inputs": {
    "base_url": "https://tfe.example.com",
    "credential_id": "550e8400-e29b-41d4-a716-446655440000",
    "organization": "example",
    "name": "application-prod",
    "attributes": {
      "execution-mode": "remote",
      "auto-apply": false
    }
  },
  "credentials": {},
  "workflow_context": {}
}
```

The manifest is the full input reference for each operation. Attribute maps
use TFE's hyphenated field names. Workspace creation combines `name`, optional
`project_id`, and `attributes`. Workspace/project updates send only the supplied
`attributes`, preserving omitted fields. TFE validates version-specific settings.
Run creation accepts optional `configuration_version_id` and run `attributes`.
Team access accepts `access` and optional `project_access`/`workspace_access`
maps for custom permissions.

The schema marks these inputs `secret: true`: variable `value`, variable-update
`attributes`, run-creation `attributes`, and configuration `archive_base64`.
The stdin adapter requires those fields in `credentials`, not `inputs`. For
example, an Add Variable invocation contains ordinary `workspace_id`, `key`,
and `category` inputs plus transient `credentials.value`. `credentials.token`
is the resolved TFE token and is never part of a saved manifest. The direct
Python SDK method accepts the complete runtime input dictionary; it must not
be used to persist secrets in workflow definitions.

## Behavior and outputs

- Lists return one page. Set `page_number`/`page_size`; continuation metadata
  is retained in `Result.meta.pagination`. There is no hidden unbounded scan.
  GitHub installation discovery supports `name` and numeric `installation_id`
  filters as documented by TFE.
- Fetch State and Outputs returns state-version metadata and output resources,
  not a download of the complete state file. Output pagination is under
  `Result.related.outputs.meta`.
- Get Run Status includes plan details by default. Set `include_plan: false`
  to query status alone. A failed secondary request fails the composite step.
- Upload accepts a base64-encoded tar.gz archive, maximum decoded size 64 MiB.
  The archive is not extracted on the worker. `auto_queue_runs` defaults to false
  so creating a run can remain a separate step. A successful upload means the
  PUT completed; it does not claim TFE finished processing or applying it.
- Uploaded archives go to the returned HTTPS URL with no TFE bearer header.
  Redirects are not followed. Upload failures identify the created configuration
  version for reconciliation without exposing its signed URL.
- Run actions return when TFE accepts the request. They do not wait for the
  run to reach a final state. Use explicit status steps and workflow waits.
- No operation is automatically retried. In particular, transport failures
  during mutations may have an unknown remote outcome.
- Variable values are redacted from responses, including non-sensitive TFE
  variables. State output values marked sensitive and signed upload/download
  URLs are removed or redacted. Inputs and remote error bodies are not logged
  by the node. The execution plane still owns transport logging and persistence.

Successful results use the SDK envelope:

```json
{
  "Result": {
    "operation": "create_workspace",
    "data": {"id": "ws-example", "type": "workspaces", "attributes": {"name": "application-prod"}},
    "related": {},
    "meta": {},
    "http_status": 201
  },
  "StatusCode": 0,
  "StatusMessage": "Execution completed successfully",
  "ErrorMessage": ""
}
```

Subsequent steps can consume `Result.data.id`. Composite reads add JSON:API
documents under `Result.related.outputs`, `.plan`, or `.team_permissions`.
Empty successful action responses use `Result.data: null`. Failures use a
nonzero `StatusCode`; the container adapter also exits nonzero.

## Local validation and execution

Run these commands from the SDK repository root after installing the SDK's
dependencies (`pip install -e ./sdk-python`):

```bash
PYTHONPATH=sdk-python:nodes/terraform-enterprise \
  python -m unittest discover -s nodes/terraform-enterprise/tests -v

PYTHONPATH=sdk-python:nodes/terraform-enterprise \
  python -m tfe_nodes.generate_manifests \
  --image localhost:5000/syntara/tfe-executor:0.1.0

# invocation.json uses the transient envelope described above.
PYTHONPATH=sdk-python:nodes/terraform-enterprise \
  python -m tfe_nodes.runner create_workspace < invocation.json
```

Each operation also has an importable SDK class, for example
`tfe_nodes.nodes.CreateWorkspaceNode` or `tfe_nodes.nodes.GetRunStatusNode`.
The SDK local runner can load these with `--module tfe_nodes.nodes --class
CreateWorkspaceNode`; its input file contains plain runtime inputs and its
token must be mounted. Unit tests inject a token and mock transport in memory.

## Container and Syntara integration

Build the runtime image separately, from the SDK repository root:

```bash
podman build -f nodes/terraform-enterprise/Containerfile \
  -t localhost:5000/syntara/tfe-executor:0.1.0 .

podman run --rm -i localhost:5000/syntara/tfe-executor:0.1.0 \
  list_workspaces < invocation.json
```

The runtime invocation must contain the resolved token or mount the token file.
The sample image reference is a local build target, not a published image.
Regenerate manifests with your actual runtime image before deployment.

These files implement the SDK side. The adjacent Syntara checkout still needs
the catalog registration API, descriptor-driven builder integration, and
execution-plane dispatch adapter. No integration or credential is created by
this package, and these nodes have not been registered or deployed.

The current `syntara-cli build` produces metadata-only OCI artifacts, not
runnable images. Its `push` also replaces `spec.execution.image` with the
metadata destination. Do not publish that artifact over the runtime image tag.
Publishing needs to preserve the runtime image reference and each node's
operation entrypoint when the platform registration path is wired up.
