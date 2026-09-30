"""Typed inputs shared by the individual TFE operations.

Attribute maps use TFE's wire names (for example auto-apply). They preserve
omitted fields on PATCH and let deployments use version-specific settings.
"""

from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1)]
Attributes = dict[str, Any]


class Connection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(description="TFE HTTPS origin, optionally ending in /api/v2")
    credential_id: UUID = Field(description="Platform credential reference; never the token")
    timeout_seconds: int = Field(default=30, ge=1, le=300)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") not in ("", "/api/v2")
        ):
            raise ValueError("Expected an HTTPS origin or /api/v2 URL without credentials")
        return value.rstrip("/").removesuffix("/api/v2")


class Pagination(BaseModel):
    page_number: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class Organization(Connection):
    organization: Identifier


class Workspace(Connection):
    workspace_id: Identifier


class CreateWorkspace(Organization):
    name: Identifier
    attributes: Attributes = Field(default_factory=dict)
    project_id: Identifier | None = None


class ListWorkspaces(Organization, Pagination):
    search: str | None = None


class UpdateWorkspace(Workspace):
    attributes: Attributes = Field(min_length=1)


class DeleteWorkspace(Workspace):
    force: bool = False


class FetchState(Workspace, Pagination):
    pass


class AddVariable(Workspace):
    key: str = Field(min_length=1)
    value: str = Field(default="", json_schema_extra={"secret": True})
    category: Literal["terraform", "env"] = "terraform"
    description: str = ""
    hcl: bool = False
    sensitive: bool = True


class ListVariables(Workspace, Pagination):
    pass


class Variable(Workspace):
    variable_id: Identifier


class UpdateVariable(Variable):
    # A map preserves omission versus explicit values; marked secret because
    # it can contain the variable value even if TFE marks it non-sensitive.
    attributes: Attributes = Field(min_length=1, json_schema_extra={"secret": True})

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, value: Attributes) -> Attributes:
        if value.keys() - {"key", "value", "description", "category", "hcl", "sensitive"}:
            raise ValueError("Unknown variable attribute")
        for key in ("key", "value", "description"):
            if key in value and not isinstance(value[key], str):
                raise ValueError("Variable text attributes must be strings")
        for key in ("hcl", "sensitive"):
            if key in value and not isinstance(value[key], bool):
                raise ValueError("Variable flags must be booleans")
        if "category" in value and value["category"] not in ("terraform", "env"):
            raise ValueError("Invalid variable category")
        return value


class UploadConfiguration(Workspace):
    archive_base64: str = Field(
        min_length=1,
        max_length=90_000_000,
        description="Base64-encoded tar.gz configuration archive (maximum decoded size 64 MiB)",
        json_schema_extra={"secret": True},
    )
    auto_queue_runs: bool = False
    speculative: bool = False


class TriggerRun(Workspace):
    configuration_version_id: Identifier | None = None
    attributes: Attributes = Field(default_factory=dict, json_schema_extra={"secret": True})


class Run(Connection):
    run_id: Identifier


class GetRunStatus(Run):
    include_plan: bool = True


class RunAction(Run):
    comment: str | None = None


class ListRuns(Workspace, Pagination):
    pass


class AddRunComment(Run):
    body: str = Field(min_length=1)


class ListInstallations(Connection):
    name: str | None = None
    installation_id: int | None = Field(default=None, ge=1)


class Installation(Connection):
    github_app_installation_id: Identifier


class LinkVCS(Workspace):
    github_app_installation_id: Identifier
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    branch: str | None = None
    ingress_submodules: bool = False


class CreateProject(Organization):
    name: str = Field(min_length=1)
    description: str | None = None


class ListProjects(Organization, Pagination):
    name: str | None = None


class Project(Connection):
    project_id: Identifier


class GetProject(Project, Pagination):
    pass


class UpdateProject(Project):
    attributes: Attributes = Field(min_length=1)


class MoveWorkspace(Workspace):
    project_id: Identifier


class AssignTeam(Project):
    team_id: Identifier
    access: Literal["read", "write", "maintain", "admin", "custom"] = "read"
    project_access: Attributes | None = None
    workspace_access: Attributes | None = None


class TFEResult(BaseModel):
    operation: str
    data: Any = None
    related: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)
    http_status: int
