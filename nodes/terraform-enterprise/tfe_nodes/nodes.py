"""SDK ActionNode implementations generated from the operation catalog."""

import base64
import binascii
import io
import tarfile
from typing import Any

from pydantic import SecretStr, ValidationError
from syntara_sdk import ActionNode, ExecutionContext

from . import models as m
from .catalog import OPERATIONS
from .client import TFEClient, TFEError, resource_id, scrub


class QuietContext(ExecutionContext):
    """Do not let the SDK's shallow input logger persist TFE payloads."""

    def log_execution_start(self, inputs):
        self.logger.info("TFE action started")

    def log_execution_error(self, error):
        self.logger.error("TFE action failed (%s)", type(error).__name__)


def relationship(resource_type: str, identifier: str) -> dict[str, Any]:
    return {"data": {"type": resource_type, "id": identifier}}


def archive_bytes(encoded: str) -> bytes:
    try:
        content = base64.b64decode(encoded, validate=True)
        if len(content) > 64 * 1024 * 1024:
            raise TFEError("Configuration archive exceeds 64 MiB")
        # Validate gzip/tar without extracting anything onto the worker.
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
            if archive.next() is None:
                raise TFEError("Configuration archive is empty")
        return content
    except (binascii.Error, tarfile.TarError, OSError, EOFError):
        raise TFEError("Configuration must be a base64-encoded tar.gz archive") from None


class TFENode(ActionNode[m.Connection, m.TFEResult]):
    operation: str

    def __init__(self, *, token: str | None = None, transport=None):
        super().__init__(OPERATIONS[self.operation].model, m.TFEResult)
        self.token = SecretStr(token) if token else None
        self.transport = transport

    def execute_raw(self, raw_inputs, context=None):
        safe_context = QuietContext(
            execution_id=context.execution_id if context else None,
            workflow_id=context.workflow_id if context else None,
            node_name="tfe_" + self.operation,
            secret_mount_path=context.secret_mount_path if context else "/run/secrets",
        )
        return super().execute_raw(raw_inputs, safe_context)

    def _format_exception(self, error: Exception) -> str:
        return (
            str(error)
            if isinstance(error, TFEError)
            else "TFE action failed; no request or response content retained"
        )

    def _format_validation_error(self, error: ValidationError) -> str:
        # Validation errors can include input values in messages/context.
        return "Invalid TFE inputs (check the step input schema)"

    def run(self, inputs: m.Connection, context: ExecutionContext) -> m.TFEResult:
        token = self.token.get_secret_value() if self.token else context.read_secret("tfe_token")
        if not token.strip() or "\n" in token or "\r" in token:
            raise TFEError("Missing or invalid resolved TFE token")
        client = TFEClient(inputs.base_url, token.strip(), inputs.timeout_seconds, self.transport)
        try:
            return self._execute(inputs, client)
        finally:
            client.close()

    def _execute(self, inputs: m.Connection, client: TFEClient) -> m.TFEResult:
        op = OPERATIONS[self.operation]
        values = inputs.model_dump(mode="json")
        path = op.path.format(**values)
        method = op.method
        attributes = dict(values.get("attributes", {}))
        relationships = {}
        params = {}
        related = {}
        archive = None
        if isinstance(inputs, m.Pagination):
            params = {"page[number]": inputs.page_number, "page[size]": inputs.page_size}
        if isinstance(inputs, m.CreateWorkspace):
            attributes["name"] = inputs.name
            if inputs.project_id:
                relationships["project"] = relationship("projects", inputs.project_id)
        elif isinstance(inputs, m.ListWorkspaces) and inputs.search is not None:
            params["search[name]"] = inputs.search
        elif isinstance(inputs, m.DeleteWorkspace) and inputs.force:
            method, path = "DELETE", f"/workspaces/{inputs.workspace_id}"
        elif isinstance(inputs, m.AddVariable):
            attributes = {
                key: values[key]
                for key in ("key", "value", "category", "description", "hcl", "sensitive")
            }
        elif isinstance(inputs, m.UploadConfiguration):
            archive = archive_bytes(inputs.archive_base64)
            attributes = {
                "auto-queue-runs": inputs.auto_queue_runs,
                "speculative": inputs.speculative,
            }
        elif isinstance(inputs, m.TriggerRun):
            relationships["workspace"] = relationship("workspaces", inputs.workspace_id)
            if inputs.configuration_version_id:
                relationships["configuration-version"] = relationship(
                    "configuration-versions", inputs.configuration_version_id
                )
        elif isinstance(inputs, m.AddRunComment):
            attributes = {"body": inputs.body}
        elif isinstance(inputs, m.ListInstallations):
            if inputs.name is not None:
                params["filter[name]"] = inputs.name
            if inputs.installation_id is not None:
                params["filter[installation_id]"] = inputs.installation_id
        elif isinstance(inputs, m.LinkVCS):
            installation, _ = client.request(
                "GET", f"/github-app/installation/{inputs.github_app_installation_id}"
            )
            installation_id = resource_id(installation)
            if installation_id != inputs.github_app_installation_id:
                raise TFEError("TFE installation response did not match the requested installation")
            vcs = {
                "identifier": inputs.repository,
                "github-app-installation-id": installation_id,
                "ingress-submodules": inputs.ingress_submodules,
            }
            if inputs.branch is not None:
                vcs["branch"] = inputs.branch
            attributes = {"vcs-repo": vcs}
        elif isinstance(inputs, m.CreateProject):
            attributes = {"name": inputs.name}
            if inputs.description is not None:
                attributes["description"] = inputs.description
        elif isinstance(inputs, m.ListProjects) and inputs.name is not None:
            params["filter[names]"] = inputs.name
        elif isinstance(inputs, m.MoveWorkspace):
            relationships["project"] = relationship("projects", inputs.project_id)
        elif isinstance(inputs, m.AssignTeam):
            attributes = {"access": inputs.access}
            if inputs.project_access is not None:
                attributes["project-access"] = inputs.project_access
            if inputs.workspace_access is not None:
                attributes["workspace-access"] = inputs.workspace_access
            relationships = {
                "project": relationship("projects", inputs.project_id),
                "team": relationship("teams", inputs.team_id),
            }

        body = None
        if op.resource_type:
            data = {"type": op.resource_type, "attributes": attributes}
            if op.id_field:
                data["id"] = values[op.id_field]
            if relationships:
                data["relationships"] = relationships
            body = {"data": data}
        elif isinstance(inputs, m.RunAction) and inputs.comment is not None:
            body = {"comment": inputs.comment}

        # Pagination belongs on the secondary collection for these operations.
        primary_params = {} if isinstance(inputs, (m.FetchState, m.GetProject)) else params
        document, status = client.request(method, path, body=body, params=primary_params)
        if isinstance(inputs, m.FetchState):
            state_id = resource_id(document)
            outputs, _ = client.request("GET", f"/state-versions/{state_id}/outputs", params=params)
            related["outputs"] = outputs
        elif isinstance(inputs, m.GetRunStatus) and inputs.include_plan:
            plan, _ = client.request("GET", f"/runs/{inputs.run_id}/plan")
            related["plan"] = plan
        elif isinstance(inputs, m.GetProject):
            teams, _ = client.request(
                "GET", "/team-projects", params={**params, "filter[project][id]": inputs.project_id}
            )
            related["team_permissions"] = teams
        elif isinstance(inputs, m.UploadConfiguration):
            identifier = resource_id(document)
            try:
                upload_url = document["data"]["attributes"]["upload-url"]
                if not isinstance(upload_url, str):
                    raise TFEError("Invalid upload URL")
                client.upload(upload_url, archive)
            except (KeyError, TypeError, ValueError, TFEError):
                raise TFEError(
                    f"Configuration version {identifier} created, but upload did not complete successfully; inspect it before retrying"
                ) from None
            related["upload"] = {"completed": True, "configuration_version_id": identifier}

        return m.TFEResult(
            operation=self.operation,
            data=scrub(document.get("data"), client.token),
            related=scrub(related, client.token),
            meta=scrub(document.get("meta", {}), client.token),
            http_status=status,
        )


NODE_CLASSES = {}
for _operation in OPERATIONS:
    _name = "".join(word.title() for word in _operation.split("_")) + "Node"
    _class = type(_name, (TFENode,), {"operation": _operation, "__module__": __name__})
    NODE_CLASSES[_operation] = _class
    globals()[_name] = _class
