"""Offline HTTP contract tests. No TFE account or running Syntara required."""

import base64
import io
import json
import logging
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

import httpx
import yaml
from syntara_sdk.compiler import compile_manifest
from syntara_sdk.context import ExecutionContext
from syntara_sdk.runner import load_node_class
from tfe_nodes.catalog import OPERATIONS
from tfe_nodes.generate_manifests import MANIFEST_ROOT, manifest_for
from tfe_nodes.nodes import NODE_CLASSES
from tfe_nodes.runner import invoke

BASE = {
    "base_url": "https://tfe.example.test",
    "credential_id": "550e8400-e29b-41d4-a716-446655440000",
}
WS = {"workspace_id": "ws-123"}
ORG = {"organization": "example"}
RUN = {"run_id": "run-123"}
PROJECT = {"project_id": "prj-123"}
INSTALLATION = {"github_app_installation_id": "ghain-123"}
TOKEN = "test-token-never-persist"


def archive():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as handle:
        content = b'terraform { required_version = ">= 1.0" }'
        info = tarfile.TarInfo("main.tf")
        info.size = len(content)
        handle.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


# Independent endpoint expectations for every user-requested operation.
CASES = {
    "create_workspace": (
        {**ORG, "name": "demo"},
        "POST",
        "/organizations/example/workspaces",
        "workspaces",
    ),
    "list_workspaces": (ORG, "GET", "/organizations/example/workspaces", None),
    "update_workspace_settings": (
        {**WS, "attributes": {"auto-apply": False}},
        "PATCH",
        "/workspaces/ws-123",
        "workspaces",
    ),
    "delete_workspace": (WS, "POST", "/workspaces/ws-123/actions/safe-delete", None),
    "fetch_state_and_outputs": (WS, "GET", "/workspaces/ws-123/current-state-version", None),
    "add_variable": (
        {**WS, "key": "region", "value": "us-east-1"},
        "POST",
        "/workspaces/ws-123/vars",
        "vars",
    ),
    "list_variables": (WS, "GET", "/workspaces/ws-123/vars", None),
    "update_variable": (
        {**WS, "variable_id": "var-123", "attributes": {"value": "new"}},
        "PATCH",
        "/workspaces/ws-123/vars/var-123",
        "vars",
    ),
    "delete_variable": (
        {**WS, "variable_id": "var-123"},
        "DELETE",
        "/workspaces/ws-123/vars/var-123",
        None,
    ),
    "upload_configuration_version": (
        {**WS, "archive_base64": base64.b64encode(archive()).decode()},
        "POST",
        "/workspaces/ws-123/configuration-versions",
        "configuration-versions",
    ),
    "trigger_run": (WS, "POST", "/runs", "runs"),
    "get_run_status": (RUN, "GET", "/runs/run-123", None),
    "apply_run": (RUN, "POST", "/runs/run-123/actions/apply", None),
    "discard_run": (RUN, "POST", "/runs/run-123/actions/discard", None),
    "cancel_run": (RUN, "POST", "/runs/run-123/actions/cancel", None),
    "force_cancel_run": (RUN, "POST", "/runs/run-123/actions/force-cancel", None),
    "list_runs_for_workspace": (WS, "GET", "/workspaces/ws-123/runs", None),
    "add_run_comment": ({**RUN, "body": "approved"}, "POST", "/runs/run-123/comments", "comments"),
    "list_github_installations": ({}, "GET", "/github-app/installations", None),
    "get_installation_details": (INSTALLATION, "GET", "/github-app/installation/ghain-123", None),
    "link_vcs_to_workspace": (
        {**WS, **INSTALLATION, "repository": "example/repo"},
        "PATCH",
        "/workspaces/ws-123",
        "workspaces",
    ),
    "create_project": (
        {**ORG, "name": "demo"},
        "POST",
        "/organizations/example/projects",
        "projects",
    ),
    "list_projects": (ORG, "GET", "/organizations/example/projects", None),
    "get_project_details": (PROJECT, "GET", "/projects/prj-123", None),
    "update_project_settings": (
        {**PROJECT, "attributes": {"name": "renamed"}},
        "PATCH",
        "/projects/prj-123",
        "projects",
    ),
    "delete_project": (PROJECT, "DELETE", "/projects/prj-123", None),
    "move_workspace_to_project": ({**WS, **PROJECT}, "PATCH", "/workspaces/ws-123", "workspaces"),
    "assign_team_permissions": (
        {**PROJECT, "team_id": "team-123"},
        "POST",
        "/team-projects",
        "team-projects",
    ),
}


class TFETests(unittest.TestCase):
    def execute(self, operation, inputs, responder=None):
        requests = []

        def handler(request):
            requests.append(request)
            if responder:
                return responder(request)
            if (
                request.method == "PUT"
                or request.method == "DELETE"
                or "/actions/" in request.url.path
            ):
                return httpx.Response(204)
            if "github-app/installation/" in request.url.path:
                return httpx.Response(200, json={"data": {"id": "ghain-123"}})
            if request.url.path.endswith("/current-state-version"):
                return httpx.Response(200, json={"data": {"id": "sv-123"}})
            if request.url.path.endswith("/configuration-versions"):
                return httpx.Response(
                    201,
                    json={
                        "data": {
                            "id": "cv-123",
                            "attributes": {
                                "upload-url": "https://storage.example.test/upload?signature=secret"
                            },
                        }
                    },
                )
            return httpx.Response(200, json={"data": {"id": "resource-123"}})

        node = NODE_CLASSES[operation](token=TOKEN, transport=httpx.MockTransport(handler))
        result = node.execute_raw({**BASE, **inputs})
        return result, requests

    def test_all_28_operations_use_expected_endpoints(self):
        self.assertEqual(set(CASES), set(OPERATIONS))
        self.assertEqual(len(CASES), 28)
        for operation, (inputs, method, endpoint, resource_type) in CASES.items():
            with self.subTest(operation=operation):
                result, requests = self.execute(operation, inputs)
                self.assertEqual(result.StatusCode, 0, result.ErrorMessage)
                primary = requests[1] if operation == "link_vcs_to_workspace" else requests[0]
                self.assertEqual((primary.method, primary.url.path), (method, "/api/v2" + endpoint))
                for request in requests:
                    if request.url.host == "tfe.example.test":
                        self.assertEqual(request.headers["authorization"], "Bearer " + TOKEN)
                        self.assertEqual(
                            request.headers["content-type"], "application/vnd.api+json"
                        )
                if resource_type:
                    self.assertEqual(json.loads(primary.content)["data"]["type"], resource_type)
                if method == "GET":
                    self.assertEqual(primary.content, b"")

    def test_jsonapi_relationships_and_patch_omission(self):
        cases = [
            (
                "create_workspace",
                {**ORG, "name": "demo", **PROJECT},
                {"project": {"data": {"type": "projects", "id": "prj-123"}}},
            ),
            (
                "trigger_run",
                {**WS, "configuration_version_id": "cv-123"},
                {
                    "workspace": {"data": {"type": "workspaces", "id": "ws-123"}},
                    "configuration-version": {
                        "data": {"type": "configuration-versions", "id": "cv-123"}
                    },
                },
            ),
            (
                "move_workspace_to_project",
                {**WS, **PROJECT},
                {"project": {"data": {"type": "projects", "id": "prj-123"}}},
            ),
            (
                "assign_team_permissions",
                {**PROJECT, "team_id": "team-123", "access": "write"},
                {
                    "project": {"data": {"type": "projects", "id": "prj-123"}},
                    "team": {"data": {"type": "teams", "id": "team-123"}},
                },
            ),
        ]
        for name, inputs, expected in cases:
            with self.subTest(name=name):
                result, requests = self.execute(name, inputs)
                self.assertEqual(result.StatusCode, 0)
                self.assertEqual(json.loads(requests[0].content)["data"]["relationships"], expected)
        _, requests = self.execute(
            "update_workspace_settings",
            {**WS, "attributes": {"auto-apply": False, "description": ""}},
        )
        self.assertEqual(
            json.loads(requests[0].content)["data"],
            {
                "type": "workspaces",
                "id": "ws-123",
                "attributes": {"auto-apply": False, "description": ""},
            },
        )

    def test_variable_and_comment_bodies(self):
        _, requests = self.execute("add_variable", {**WS, "key": "test", "value": "secret"})
        self.assertEqual(
            json.loads(requests[0].content)["data"]["attributes"],
            {
                "key": "test",
                "value": "secret",
                "category": "terraform",
                "description": "",
                "sensitive": True,
                "hcl": False,
            },
        )
        _, requests = self.execute(
            "update_variable", {**WS, "variable_id": "var-123", "attributes": {"value": ""}}
        )
        self.assertEqual(
            json.loads(requests[0].content)["data"],
            {"type": "vars", "id": "var-123", "attributes": {"value": ""}},
        )
        _, requests = self.execute("add_run_comment", {**RUN, "body": "approved"})
        self.assertEqual(
            json.loads(requests[0].content)["data"]["attributes"], {"body": "approved"}
        )
        for name in ("apply_run", "discard_run", "cancel_run", "force_cancel_run"):
            _, requests = self.execute(name, {**RUN, "comment": "reason"})
            self.assertEqual(json.loads(requests[0].content), {"comment": "reason"})

    def test_safe_and_forced_deletion(self):
        for force, method, path in [
            (False, "POST", "/api/v2/workspaces/ws-123/actions/safe-delete"),
            (True, "DELETE", "/api/v2/workspaces/ws-123"),
        ]:
            result, requests = self.execute("delete_workspace", {**WS, "force": force})
            self.assertEqual(result.StatusCode, 0)
            self.assertEqual(len(requests), 1)
            self.assertEqual((requests[0].method, requests[0].url.path), (method, path))

    def test_composite_reads_and_pagination(self):
        cases = [
            ("fetch_state_and_outputs", WS, "/api/v2/state-versions/sv-123/outputs", "outputs"),
            ("get_run_status", RUN, "/api/v2/runs/run-123/plan", "plan"),
            ("get_project_details", PROJECT, "/api/v2/team-projects", "team_permissions"),
        ]
        for name, inputs, path, key in cases:
            result, requests = self.execute(name, inputs)
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[1].url.path, path)
            self.assertIn(key, result.Result["related"])
            if name == "get_project_details":
                self.assertEqual(requests[1].url.params["filter[project][id]"], "prj-123")
        _, requests = self.execute("get_run_status", {**RUN, "include_plan": False})
        self.assertEqual(len(requests), 1)
        for name, fields, query in [
            ("list_workspaces", {**ORG, "search": "hello world"}, {"search[name]": "hello world"}),
            ("list_projects", {**ORG, "name": "demo"}, {"filter[names]": "demo"}),
            ("list_variables", WS, {}),
            ("list_runs_for_workspace", WS, {}),
        ]:
            _, requests = self.execute(name, {**fields, "page_number": 2, "page_size": 50})
            self.assertEqual(
                dict(requests[0].url.params), {**query, "page[number]": "2", "page[size]": "50"}
            )

    def test_vcs_lookup_before_patch_and_filters(self):
        result, requests = self.execute(
            "link_vcs_to_workspace",
            {**WS, **INSTALLATION, "repository": "owner/repo", "branch": "main"},
        )
        self.assertEqual(result.StatusCode, 0)
        self.assertEqual(requests[0].url.path, "/api/v2/github-app/installation/ghain-123")
        self.assertEqual(
            json.loads(requests[1].content)["data"]["attributes"],
            {
                "vcs-repo": {
                    "identifier": "owner/repo",
                    "github-app-installation-id": "ghain-123",
                    "branch": "main",
                    "ingress-submodules": False,
                }
            },
        )
        result, requests = self.execute(
            "link_vcs_to_workspace",
            {**WS, **INSTALLATION, "repository": "owner/repo"},
            lambda r: httpx.Response(404),
        )
        self.assertEqual(result.StatusCode, 1)
        self.assertEqual(len(requests), 1)
        _, requests = self.execute(
            "list_github_installations", {"name": "owner", "installation_id": 123}
        )
        self.assertEqual(
            dict(requests[0].url.params),
            {"filter[name]": "owner", "filter[installation_id]": "123"},
        )

    def test_upload_bytes_without_bearer_and_without_url_in_result(self):
        content = archive()
        result, requests = self.execute(
            "upload_configuration_version",
            {**WS, "archive_base64": base64.b64encode(content).decode()},
        )
        self.assertEqual(result.StatusCode, 0, result.ErrorMessage)
        self.assertEqual(
            json.loads(requests[0].content)["data"]["attributes"],
            {"auto-queue-runs": False, "speculative": False},
        )
        self.assertEqual(requests[1].content, content)
        self.assertEqual(requests[1].method, "PUT")
        self.assertNotIn("authorization", requests[1].headers)
        self.assertNotIn("signature", result.model_dump_json())

    def test_partial_upload_failure_reports_created_id_without_secret(self):
        def responder(request):
            if request.method == "POST":
                return httpx.Response(
                    201,
                    json={
                        "data": {
                            "id": "cv-123",
                            "attributes": {
                                "upload-url": "https://storage.test/upload?signature=SECRET"
                            },
                        }
                    },
                )
            return httpx.Response(500, text="SECRET")

        result, requests = self.execute(
            "upload_configuration_version", CASES["upload_configuration_version"][0], responder
        )
        self.assertEqual(result.StatusCode, 1)
        self.assertIn("cv-123 created", result.ErrorMessage)
        self.assertNotIn("SECRET", result.model_dump_json())
        self.assertEqual(len(requests), 2)

    def test_invalid_inputs_do_not_call_tfe(self):
        invalid = [
            ("create_workspace", ORG),
            ("delete_workspace", {"workspace_id": "../other"}),
            ("list_workspaces", {**ORG, "page_size": 101}),
            ("list_workspaces", {**ORG, "base_url": "http://tfe.test"}),
            ("list_workspaces", {**ORG, "base_url": "https://user:pass@tfe.test"}),
            ("list_workspaces", {**ORG, "base_url": "https://tfe.test/other"}),
            ("list_workspaces", {**ORG, "credential_id": "literal-token"}),
            ("update_variable", {**WS, "variable_id": "var-123", "attributes": {"value": 123}}),
            ("update_workspace_settings", {**WS, "attributes": {}}),
            ("upload_configuration_version", {**WS, "archive_base64": "not-base64"}),
        ]
        for name, inputs in invalid:
            with self.subTest(name=name, inputs=inputs):
                result, requests = self.execute(name, inputs)
                self.assertEqual(result.StatusCode, 1)
                self.assertEqual(requests, [])

    def test_errors_are_sanitized_and_never_retried(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger("syntara")
        logger.addHandler(handler)
        try:
            for status in (301, 401, 403, 404, 409, 422, 429, 500, 503):
                result, requests = self.execute(
                    "add_variable",
                    {**WS, "key": "key", "value": "SECRET"},
                    lambda r, status=status: httpx.Response(
                        status, text=TOKEN + " SECRET", headers={"location": "https://other.test"}
                    ),
                )
                self.assertEqual(result.StatusCode, 1)
                self.assertIn(str(status), result.ErrorMessage)
                self.assertEqual(len(requests), 1)
                self.assertNotIn(TOKEN, result.model_dump_json())
                self.assertNotIn("SECRET", result.model_dump_json())
        finally:
            logger.removeHandler(handler)
        self.assertNotIn("SECRET", stream.getvalue())
        self.assertNotIn(TOKEN, stream.getvalue())

    def test_transport_failure_and_malformed_responses(self):
        def timeout(request):
            raise httpx.ReadTimeout("SECRET", request=request)

        result, requests = self.execute("create_project", {**ORG, "name": "demo"}, timeout)
        self.assertEqual(len(requests), 1)
        self.assertIn("remote outcome unknown", result.ErrorMessage)
        for response in (
            httpx.Response(200),
            httpx.Response(200, text="SECRET"),
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"errors": []}),
        ):
            result, _ = self.execute("list_workspaces", ORG, lambda r, response=response: response)
            self.assertEqual(result.StatusCode, 1)
            self.assertNotIn("SECRET", result.model_dump_json())

    def test_sensitive_variables_and_outputs_are_redacted(self):
        body = {
            "data": [
                {"type": "vars", "attributes": {"sensitive": False, "value": "SECRET"}},
                {
                    "type": "state-version-outputs",
                    "attributes": {"sensitive": True, "value": "SECRET"},
                },
                {
                    "type": "state-version-outputs",
                    "attributes": {"sensitive": False, "value": "public"},
                },
            ],
            "meta": {"pagination": {"next-page": 2}},
        }
        result, _ = self.execute("list_variables", WS, lambda r: httpx.Response(200, json=body))
        self.assertNotIn("SECRET", result.model_dump_json())
        self.assertIn("public", result.model_dump_json())
        self.assertEqual(result.Result["meta"]["pagination"]["next-page"], 2)

    def test_run_variable_response_is_redacted(self):
        result, _ = self.execute(
            "trigger_run",
            WS,
            lambda r: httpx.Response(
                201,
                json={
                    "data": {
                        "type": "runs",
                        "attributes": {"variables": [{"key": "password", "value": "SECRET"}]},
                    }
                },
            ),
        )
        self.assertEqual(result.StatusCode, 0)
        self.assertNotIn("SECRET", result.model_dump_json())

    def test_mounted_token_and_api_prefix(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"data": []})

        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "tfe_token").write_text(TOKEN)
            context = ExecutionContext(secret_mount_path=directory)
            node = NODE_CLASSES["list_workspaces"](transport=httpx.MockTransport(handler))
            result = node.execute_raw(
                {**BASE, **ORG, "base_url": "https://tfe.example.test/api/v2/"}, context
            )
        self.assertEqual(result.StatusCode, 0)
        self.assertEqual(requests[0].url.path, "/api/v2/organizations/example/workspaces")
        self.assertEqual(requests[0].headers["authorization"], "Bearer " + TOKEN)

    def test_invocation_adapter_splits_secrets_and_validates_envelope(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(
                201, json={"data": {"type": "vars", "attributes": {"value": "SECRET"}}}
            )

        payload = {
            "inputs": {**BASE, **WS, "key": "example"},
            "credentials": {"token": TOKEN, "value": "SECRET"},
        }
        result = invoke("add_variable", payload, transport=httpx.MockTransport(handler))
        self.assertEqual(result.StatusCode, 0)
        self.assertEqual(json.loads(requests[0].content)["data"]["attributes"]["value"], "SECRET")
        self.assertNotIn("SECRET", result.model_dump_json())
        for invalid in (
            [],
            {"inputs": []},
            {**payload, "credentials": {"token": []}},
            {**payload, "inputs": {**payload["inputs"], "value": "SECRET"}},
        ):
            self.assertEqual(invoke("add_variable", invalid).StatusCode, 1)

    def test_manifests_validate_match_models_and_load_sdk_classes(self):
        self.assertEqual(len(list(MANIFEST_ROOT.glob("*.yaml"))), 28)
        for name, cls in NODE_CLASSES.items():
            with self.subTest(name=name):
                path = MANIFEST_ROOT / (name + ".yaml")
                self.assertEqual(compile_manifest(path), manifest_for(name))
                self.assertEqual(
                    yaml.safe_load(path.read_text())["spec"]["inputs"],
                    cls().input_model.model_json_schema(),
                )
                self.assertIs(load_node_class("tfe_nodes.nodes", cls.__name__), cls)

    def test_container_adapter_emits_standard_error_and_nonzero_exit(self):
        result = subprocess.run(
            [sys.executable, "-m", "tfe_nodes.runner", "list_workspaces"],
            input="invalid JSON SECRET",
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["StatusCode"], 1)
        self.assertNotIn("SECRET", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
