"""One catalog entry per independently registerable step."""

from dataclasses import dataclass

from . import models as m


@dataclass(frozen=True)
class Operation:
    title: str
    domain: str
    model: type[m.Connection]
    method: str
    path: str
    resource_type: str | None = None
    id_field: str | None = None


OPERATIONS = {
    "create_workspace": Operation(
        "Create Workspace",
        "workspace",
        m.CreateWorkspace,
        "POST",
        "/organizations/{organization}/workspaces",
        "workspaces",
    ),
    "list_workspaces": Operation(
        "List Workspaces",
        "workspace",
        m.ListWorkspaces,
        "GET",
        "/organizations/{organization}/workspaces",
    ),
    "update_workspace_settings": Operation(
        "Update Workspace Settings",
        "workspace",
        m.UpdateWorkspace,
        "PATCH",
        "/workspaces/{workspace_id}",
        "workspaces",
        "workspace_id",
    ),
    "delete_workspace": Operation(
        "Delete Workspace",
        "workspace",
        m.DeleteWorkspace,
        "POST",
        "/workspaces/{workspace_id}/actions/safe-delete",
    ),
    "fetch_state_and_outputs": Operation(
        "Fetch State and Outputs",
        "workspace",
        m.FetchState,
        "GET",
        "/workspaces/{workspace_id}/current-state-version",
    ),
    "add_variable": Operation(
        "Add Variable",
        "variables",
        m.AddVariable,
        "POST",
        "/workspaces/{workspace_id}/vars",
        "vars",
    ),
    "list_variables": Operation(
        "List Variables", "variables", m.ListVariables, "GET", "/workspaces/{workspace_id}/vars"
    ),
    "update_variable": Operation(
        "Update Variable",
        "variables",
        m.UpdateVariable,
        "PATCH",
        "/workspaces/{workspace_id}/vars/{variable_id}",
        "vars",
        "variable_id",
    ),
    "delete_variable": Operation(
        "Delete Variable",
        "variables",
        m.Variable,
        "DELETE",
        "/workspaces/{workspace_id}/vars/{variable_id}",
    ),
    "upload_configuration_version": Operation(
        "Upload Configuration Version",
        "configuration",
        m.UploadConfiguration,
        "POST",
        "/workspaces/{workspace_id}/configuration-versions",
        "configuration-versions",
    ),
    "trigger_run": Operation("Trigger Run", "run", m.TriggerRun, "POST", "/runs", "runs"),
    "get_run_status": Operation("Get Run Status", "run", m.GetRunStatus, "GET", "/runs/{run_id}"),
    "apply_run": Operation("Apply Run", "run", m.RunAction, "POST", "/runs/{run_id}/actions/apply"),
    "discard_run": Operation(
        "Discard Run", "run", m.RunAction, "POST", "/runs/{run_id}/actions/discard"
    ),
    "cancel_run": Operation(
        "Cancel Run", "run", m.RunAction, "POST", "/runs/{run_id}/actions/cancel"
    ),
    "force_cancel_run": Operation(
        "Force Cancel Run", "run", m.RunAction, "POST", "/runs/{run_id}/actions/force-cancel"
    ),
    "list_runs_for_workspace": Operation(
        "List Runs for Workspace", "run", m.ListRuns, "GET", "/workspaces/{workspace_id}/runs"
    ),
    "add_run_comment": Operation(
        "Add Run Comment", "run", m.AddRunComment, "POST", "/runs/{run_id}/comments", "comments"
    ),
    "list_github_installations": Operation(
        "List GitHub Installations", "vcs", m.ListInstallations, "GET", "/github-app/installations"
    ),
    "get_installation_details": Operation(
        "Get Installation Details",
        "vcs",
        m.Installation,
        "GET",
        "/github-app/installation/{github_app_installation_id}",
    ),
    "link_vcs_to_workspace": Operation(
        "Link VCS to Workspace",
        "vcs",
        m.LinkVCS,
        "PATCH",
        "/workspaces/{workspace_id}",
        "workspaces",
        "workspace_id",
    ),
    "create_project": Operation(
        "Create Project",
        "project",
        m.CreateProject,
        "POST",
        "/organizations/{organization}/projects",
        "projects",
    ),
    "list_projects": Operation(
        "List Projects", "project", m.ListProjects, "GET", "/organizations/{organization}/projects"
    ),
    "get_project_details": Operation(
        "Get Project Details", "project", m.GetProject, "GET", "/projects/{project_id}"
    ),
    "update_project_settings": Operation(
        "Update Project Settings",
        "project",
        m.UpdateProject,
        "PATCH",
        "/projects/{project_id}",
        "projects",
        "project_id",
    ),
    "delete_project": Operation(
        "Delete Project", "project", m.Project, "DELETE", "/projects/{project_id}"
    ),
    "move_workspace_to_project": Operation(
        "Move Workspace to Project",
        "project",
        m.MoveWorkspace,
        "PATCH",
        "/workspaces/{workspace_id}",
        "workspaces",
        "workspace_id",
    ),
    "assign_team_permissions": Operation(
        "Assign Team Permissions",
        "project",
        m.AssignTeam,
        "POST",
        "/team-projects",
        "team-projects",
    ),
}
