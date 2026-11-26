"""The Conductor's single HTTP/UI permission policy.

The middleware, setup bootstrap, and the UI elevation affordance all consume
this inventory.  Keeping the operation labels here makes a newly advertised
mutation impossible to add without also choosing its permission and role
posture.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class ProtectedOperation:
    """One prefix policy enforced by ``AuthMiddleware``."""

    method: str
    path: str
    permission: str
    action: str


# This is the API half of the policy matrix.  More-specific paths must precede
# their parent when they carry a different permission; middleware uses the
# same order when resolving a request.
PROTECTED_OPERATIONS: tuple[ProtectedOperation, ...] = (
    ProtectedOperation("GET", "/v1/harness", "harness.execute", "inspect harness sessions"),
    ProtectedOperation("GET", "/v1/rsi", "rsi.execute", "inspect RSI sessions"),
    ProtectedOperation("GET", "/v1/evolution", "rsi.execute", "inspect evolution sessions"),
    ProtectedOperation("GET", "/v1/hitl", "dags.write", "inspect pending graph approvals"),
    # The RUM ring aggregates every principal's navigation telemetry
    # (route templates, session ids, timings) into one instance-wide
    # read-back — a cross-principal aggregate, so it takes an operator-only
    # posture. Ingest (POST) is deliberately NOT protected: every session's
    # reporter beacons its own bounded, schema-projected timings on the
    # session it already holds, and gating the beacon would starve the ring
    # of exactly the ordinary traffic it exists to measure (#1420).
    ProtectedOperation("GET", "/v1/rum", "rum.read", "read navigation telemetry"),
    ProtectedOperation("DELETE", "/v1/settings", "config.delete", "delete settings"),
    ProtectedOperation("DELETE", "/v1/agents", "agents.delete", "delete agents"),
    ProtectedOperation("DELETE", "/v1/skills", "skills.delete", "delete skills"),
    ProtectedOperation("DELETE", "/v1/mcp", "mcp.delete", "remove MCP servers"),
    ProtectedOperation("DELETE", "/v1/harness", "harness.execute", "stop harness sessions"),
    ProtectedOperation("DELETE", "/v1/containers", "containers.control", "delete containers"),
    ProtectedOperation("DELETE", "/v1/credentials", "credentials.write", "remove credentials"),
    ProtectedOperation("DELETE", "/v1/dags", "dags.write", "delete DAGs"),
    ProtectedOperation("DELETE", "/v1/schedules", "schedules.write", "delete schedules"),
    ProtectedOperation("DELETE", "/v1/workspaces", "workspaces.write", "delete workspaces"),
    ProtectedOperation("POST", "/v1/settings", "config.write", "change settings"),
    ProtectedOperation("POST", "/v1/mcp", "mcp.write", "change MCP configuration"),
    ProtectedOperation("POST", "/v1/agents", "agents.write", "change agents"),
    ProtectedOperation("POST", "/v1/skills", "skills.write", "change skills"),
    ProtectedOperation("POST", "/v1/containers", "containers.control", "control containers"),
    ProtectedOperation("POST", "/v1/dags", "dags.write", "change or run DAGs"),
    ProtectedOperation("POST", "/v1/optimizer", "dags.write", "accept DAG optimization"),
    ProtectedOperation("POST", "/v1/hitl", "dags.write", "answer graph approvals"),
    ProtectedOperation("POST", "/v1/schedules", "schedules.write", "change schedules"),
    ProtectedOperation("POST", "/v1/workspaces", "workspaces.write", "change workspaces"),
    ProtectedOperation("POST", "/v1/evolution", "rsi.execute", "run evolution"),
    # Chat workflow execution creates durable Run history and can invoke
    # mutating nodes. It uses the shared approval capability before the
    # existing chat dispatch path, so authentication alone is not enough.
    ProtectedOperation("POST", "/v1/chat/workflows", "dags.write", "run a chat workflow"),
    ProtectedOperation("POST", "/v1/audit", "audit.write", "write audit entries"),
    # A credential test can send a draft API key to an operator-supplied
    # endpoint, so it is the same trust decision as saving the credential;
    # otherwise an ordinary session would gain an SSRF/probe primitive.
    # Kept in sync with the inline policy on develop during the merge.
    ProtectedOperation("POST", "/v1/credentials", "credentials.write", "test a credential"),
    ProtectedOperation("POST", "/v1/harness", "harness.execute", "run harness sessions"),
    ProtectedOperation("POST", "/v1/rsi", "rsi.execute", "run RSI"),
    # Resolving an approval is an authority-bearing decision, not a
    # generic configuration write. Require the dedicated approver scope;
    # the route applies the action-specific policy on top of this.
    # More-specific path: must stay ahead of /v1/capabilities below.
    ProtectedOperation(
        "POST", "/v1/capabilities/approvals", "approvals.resolve", "resolve an approval"
    ),
    ProtectedOperation("POST", "/v1/capabilities", "config.write", "change capabilities"),
    ProtectedOperation("POST", "/v1/providers", "config.write", "activate providers"),
    ProtectedOperation("PUT", "/v1/settings", "config.write", "change settings"),
    ProtectedOperation("PUT", "/v1/providers", "config.write", "store provider keys"),
    ProtectedOperation("PUT", "/v1/mcp/servers", "mcp.write", "change MCP servers"),
    ProtectedOperation("PUT", "/v1/agents", "agents.write", "change agents"),
    ProtectedOperation("PUT", "/v1/skills", "skills.write", "change skills"),
    ProtectedOperation("PUT", "/v1/credentials", "credentials.write", "store credentials"),
    ProtectedOperation("PUT", "/v1/dags", "dags.write", "change DAGs"),
    ProtectedOperation("PUT", "/v1/schedules", "schedules.write", "change schedules"),
    ProtectedOperation("PUT", "/v1/workspaces", "workspaces.write", "change workspace settings"),
    ProtectedOperation("PATCH", "/v1/settings", "config.write", "change settings"),
    ProtectedOperation("PATCH", "/v1/mcp/servers", "mcp.write", "change MCP servers"),
    ProtectedOperation("PATCH", "/v1/capabilities", "config.write", "change capabilities"),
    ProtectedOperation("PATCH", "/v1/skills", "skills.write", "change skills"),
    ProtectedOperation("PATCH", "/v1/workspaces", "workspaces.write", "change workspaces"),
)

# Mutations exposed by the ordinary product UI.  These are intentionally more
# specific than the API prefixes: they are the contract the frontend uses when
# it asks for task-scoped elevation after a 403.
UI_MUTATIONS: tuple[ProtectedOperation, ...] = (
    ProtectedOperation(
        "POST", "/v1/workspaces/persona-templates", "workspaces.write", "author a persona"
    ),
    ProtectedOperation("POST", "/v1/agents", "agents.write", "create an agent"),
    ProtectedOperation("POST", "/v1/agents/forge", "agents.write", "forge an agent"),
    ProtectedOperation("PUT", "/v1/agents/{agent_id}", "agents.write", "edit an agent"),
    ProtectedOperation("POST", "/v1/agents/{agent_id}/scan", "agents.write", "scan an agent"),
    ProtectedOperation("DELETE", "/v1/agents/{agent_id}", "agents.delete", "delete an agent"),
    ProtectedOperation("POST", "/v1/schedules", "schedules.write", "create a schedule"),
    ProtectedOperation("PUT", "/v1/schedules/{schedule_id}", "schedules.write", "edit a schedule"),
    ProtectedOperation(
        "DELETE", "/v1/schedules/{schedule_id}", "schedules.write", "delete a schedule"
    ),
    ProtectedOperation("POST", "/v1/dags", "dags.write", "create a DAG"),
    ProtectedOperation("PUT", "/v1/dags/{dag_id}", "dags.write", "edit a DAG"),
    ProtectedOperation("DELETE", "/v1/dags/{dag_id}", "dags.write", "delete a DAG"),
    ProtectedOperation("POST", "/v1/dags/{dag_id}/nodes", "dags.write", "add a DAG node"),
    ProtectedOperation(
        "DELETE", "/v1/dags/{dag_id}/nodes/{node_id}", "dags.write", "remove a DAG node"
    ),
    ProtectedOperation("POST", "/v1/dags/{dag_id}/edges", "dags.write", "connect DAG nodes"),
    ProtectedOperation("POST", "/v1/dags/{dag_id}/activate", "dags.write", "activate a DAG"),
    ProtectedOperation(
        "POST",
        "/v1/optimizer/proposals/{proposal_id}/accept",
        "dags.write",
        "accept an optimization",
    ),
    ProtectedOperation(
        "POST",
        "/v1/optimizer/proposals/{proposal_id}/reject",
        "dags.write",
        "reject an optimization",
    ),
    ProtectedOperation(
        "POST", "/v1/schedules/{schedule_id}/run", "schedules.write", "run a schedule"
    ),
    ProtectedOperation("PATCH", "/v1/skills/{skill_id}/toggle", "skills.write", "toggle a skill"),
    ProtectedOperation("POST", "/v1/mcp/servers", "mcp.write", "add an MCP server"),
    ProtectedOperation("POST", "/v1/mcp/test", "mcp.write", "test MCP connections"),
    ProtectedOperation(
        "DELETE", "/v1/mcp/servers/{server_id}", "mcp.delete", "remove an MCP server"
    ),
    ProtectedOperation(
        "PUT", "/v1/credentials/{provider_id}", "credentials.write", "store a credential"
    ),
    ProtectedOperation(
        "PUT",
        "/v1/credentials/{provider_id}/config",
        "credentials.write",
        "change credential configuration",
    ),
    ProtectedOperation(
        "DELETE", "/v1/credentials/{provider_id}", "credentials.write", "remove a credential"
    ),
    ProtectedOperation(
        "PUT",
        "/v1/workspaces/{workspace_id}/tool-bindings",
        "workspaces.write",
        "change tool bindings",
    ),
    ProtectedOperation(
        "POST", "/v1/workspaces/{workspace_id}/members", "workspaces.write", "invite a member"
    ),
    ProtectedOperation(
        "DELETE",
        "/v1/workspaces/{workspace_id}/members/{user_id}",
        "workspaces.write",
        "remove a member",
    ),
    ProtectedOperation(
        "PATCH", "/v1/workspaces/{workspace_id}", "workspaces.write", "archive a workspace"
    ),
    ProtectedOperation(
        "PATCH", "/v1/workspaces/{workspace_id}", "workspaces.write", "restore a workspace"
    ),
    ProtectedOperation(
        "DELETE", "/v1/workspaces/{workspace_id}", "workspaces.write", "delete a workspace"
    ),
)

# The bootstrap account is a daily driver, not a second administrator.  It is
# assigned the permissions needed for every ordinary UI mutation and must still
# prove its password through /auth/elevate for each task.
DAILY_USER_PERMISSIONS: tuple[str, ...] = tuple(
    sorted({operation.permission for operation in UI_MUTATIONS})
)

ROLE_PERMISSIONS = MappingProxyType(
    {
        "user": DAILY_USER_PERMISSIONS,
        "admin": ("*",),
    }
)


def protected_ops_by_method() -> dict[str, dict[str, str]]:
    """Return the middleware shape without creating a second policy table."""
    result: dict[str, dict[str, str]] = {}
    for operation in PROTECTED_OPERATIONS:
        result.setdefault(operation.method, {})[operation.path] = operation.permission
    return result


def permission_for_ui_action(action: str) -> str:
    """Resolve a UI action name, failing closed for unknown actions."""
    for operation in UI_MUTATIONS:
        if operation.action == action:
            return operation.permission
    raise KeyError(f"unknown UI action: {action}")
