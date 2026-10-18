"""Canonical HTTP capability policy shared by middleware and the UI contract.

The browser may use this snapshot to hide or explain controls, but every
request still passes through ``required_permission`` in AuthMiddleware.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from maistro.identity import Principal

# One policy table for the HTTP boundary. Keep this importable without routes
# or middleware so the auth snapshot cannot create an alternate enforcement
# path through an import cycle.
PROTECTED_OPS: dict[str, dict[str, str]] = {
    "GET": {
        "/v1/harness": "harness.execute",
        "/v1/rsi": "rsi.execute",
        "/v1/evolution": "rsi.execute",
        "/v1/hitl": "dags.write",
        # Cross-principal RUM aggregate read-back (develop #1420); ingest
        # POST stays authenticated-only by design (ROUTE_EXEMPT in
        # scripts/check_enumerations.py records that reasoning).
        "/v1/rum": "rum.read",
    },
    "DELETE": {
        "/v1/settings": "config.delete",
        "/v1/agents": "agents.delete",
        "/v1/skills": "skills.delete",
        "/v1/mcp": "mcp.delete",
        "/v1/harness": "harness.execute",
        "/v1/containers": "containers.control",
        "/v1/credentials": "credentials.write",
        "/v1/dags": "dags.write",
        "/v1/schedules": "schedules.write",
        "/v1/workspaces": "workspaces.write",
    },
    "POST": {
        "/v1/settings": "config.write",
        "/v1/mcp": "mcp.write",
        "/v1/agents": "agents.write",
        "/v1/skills": "skills.write",
        "/v1/containers": "containers.control",
        "/v1/dags": "dags.write",
        "/v1/optimizer": "dags.write",
        "/v1/hitl": "dags.write",
        "/v1/schedules": "schedules.write",
        "/v1/workspaces": "workspaces.write",
        "/v1/evolution": "rsi.execute",
        # Chat workflow execution creates durable Run history and can invoke
        # mutating nodes through the shared approval capability (develop).
        "/v1/chat/workflows": "dags.write",
        "/v1/audit": "audit.write",
        "/v1/harness": "harness.execute",
        "/v1/rsi": "rsi.execute",
        # Resolution of a capability approval is an authority-bearing
        # decision with its own approver scope (develop); discovery and
        # provider configuration stay config writes. The more specific
        # prefix is listed first because matching is ordered startswith.
        "/v1/capabilities/approvals": "approvals.resolve",
        "/v1/capabilities": "config.write",
        "/v1/providers": "config.write",
    },
    "PUT": {
        "/v1/settings": "config.write",
        "/v1/providers": "config.write",
        "/v1/mcp/servers": "mcp.write",
        "/v1/agents": "agents.write",
        "/v1/skills": "skills.write",
        "/v1/credentials": "credentials.write",
        "/v1/dags": "dags.write",
        "/v1/schedules": "schedules.write",
        "/v1/workspaces": "workspaces.write",
    },
    "PATCH": {
        "/v1/settings": "config.write",
        "/v1/mcp/servers": "mcp.write",
        "/v1/capabilities": "config.write",
        "/v1/skills": "skills.write",
        "/v1/workspaces": "workspaces.write",
    },
}

# These are the controls that have a named product surface. The permission is
# deliberately the same string as the HTTP table, not a frontend-only role.
SURFACE_POLICY: dict[str, dict[str, str | None]] = {
    "settings": {"permission": "config.write", "read_path": "/v1/settings"},
    "credentials": {"permission": "credentials.write", "read_path": "/v1/credentials"},
    "integrations": {"permission": "mcp.write", "read_path": "/v1/mcp/servers"},
    "rsi": {"permission": "rsi.execute", "read_path": "/v1/rsi/status"},
}


def required_permission(method: str, path: str) -> str | None:
    """Return the permission enforced for an HTTP method/path pair."""
    method = method.upper()
    if method == "POST" and path.rstrip("/") == "/v1/workspaces":
        return None
    # No URL-suffix carve-outs (#403): the former endswith("/invoke")
    # exemption granted any future route with that suffix a silent elevation
    # bypass decided purely by URL naming. Elevation binds only to the
    # capability identifiers registered above plus the named, reviewed
    # exceptions below; a path's spelling grants no authority.
    if path.endswith("/feedback"):
        return None
    if method == "GET" and (path == "/v1/dag-runs" or path.startswith("/v1/dag-runs/")):
        return None
    if method == "GET" and (path == "/v1/eval-judge" or path.startswith("/v1/eval-judge/")):
        return None
    for prefix, permission in PROTECTED_OPS.get(method, {}).items():
        if path.startswith(prefix):
            return permission
    return None


def principal_has_permission(
    user: Principal | Mapping[str, Any], permission: str
) -> bool:
    """Mirror the middleware's effective grant check for contract responses."""
    if isinstance(user, Principal):
        return user.has_permission(permission)
    if user.get("role") == "admin":
        return True
    assigned = user.get("permissions", [])
    elevated = user.get("elevated_permissions", [])
    return permission in assigned and permission in elevated


def capability_snapshot(user: dict[str, Any]) -> dict[str, Any]:
    """Build a no-store, explainable snapshot for the authenticated principal."""
    assigned = sorted({str(value) for value in user.get("permissions", [])})
    elevated = sorted({str(value) for value in user.get("elevated_permissions", [])})
    is_admin = user.get("role") == "admin"
    permissions = sorted(set(assigned) | set(elevated))
    known = sorted(
        set(permissions)
        | {value for method in PROTECTED_OPS.values() for value in method.values()}
        | {
            value
            for surface in SURFACE_POLICY.values()
            if (value := surface.get("permission")) is not None
        }
    )
    capabilities = {
        permission: {
            "assigned": is_admin or permission in assigned,
            "elevated": is_admin or (permission in elevated and permission in assigned),
            "effective": is_admin or principal_has_permission(user, permission),
            "can_elevate": not is_admin and permission in assigned and permission not in elevated,
            "reason": (
                "admin role"
                if is_admin
                else "active elevation"
                if permission in elevated and permission in assigned
                else "assigned; self-elevation required"
                if permission in assigned
                else "permission not assigned"
            ),
        }
        for permission in known
    }
    surfaces = {
        name: {
            **definition,
            "effective": is_admin
            or (
                definition["permission"] is not None
                and principal_has_permission(user, str(definition["permission"]))
            ),
            "can_elevate": not is_admin
            and definition["permission"] in assigned
            and definition["permission"] not in elevated,
        }
        for name, definition in SURFACE_POLICY.items()
    }
    return {
        "version": "hive-http-capabilities-v1",
        "role": user.get("role", "user"),
        "assigned_permissions": assigned,
        "elevated_permissions": elevated,
        "effective_permissions": known if is_admin else sorted(set(assigned) & set(elevated)),
        "elevated_tasks": list(user.get("elevated_tasks", [])),
        "elevated_task_expiries": dict(user.get("elevated_task_expiries", {})),
        "capabilities": capabilities,
        "surfaces": surfaces,
    }
