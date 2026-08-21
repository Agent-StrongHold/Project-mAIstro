"""Every newly-scoped surface must refuse the zero-permission daily account.

This is the ratchet-clearing counterpart of the enumeration gate: the gate
proved these routes carried no scope; these tests prove the scopes now carried
actually fire. `authed_client` is role="user" with permissions=[] — the
weakest account the app can mint, and until this change it could start
containers, rewrite DAGs, forge audit entries, and execute PM tools.
"""

from __future__ import annotations

import pytest

CASES = [
    ("post", "/v1/containers/build", "containers.control"),
    ("post", "/v1/containers/abc/stop", "containers.control"),
    ("delete", "/v1/containers/abc", "containers.control"),
    ("post", "/v1/dags", "dags.write"),
    ("post", "/v1/dags/some-dag/run", "dags.write"),
    ("put", "/v1/dags/some-dag", "dags.write"),
    ("delete", "/v1/dags/some-dag", "dags.write"),
    ("post", "/v1/optimizer/some-dag/run", "dags.write"),
    ("post", "/v1/schedules", "schedules.write"),
    ("post", "/v1/workspaces/persona-templates", "workspaces.write"),
    ("post", "/v1/workspaces/ws1/members", "workspaces.write"),
    ("delete", "/v1/workspaces/ws1/members/u1", "workspaces.write"),
    ("patch", "/v1/workspaces/ws1", "workspaces.write"),
    ("delete", "/v1/workspaces/ws1", "workspaces.write"),
    ("put", "/v1/workspaces/ws1/tool-bindings", "workspaces.write"),
    ("put", "/v1/schedules/s1", "schedules.write"),
    ("delete", "/v1/schedules/s1", "schedules.write"),
    ("put", "/v1/credentials/jira", "credentials.write"),
    ("delete", "/v1/credentials/jira", "credentials.write"),
    ("post", "/v1/evolution/cycle", "rsi.execute"),
    ("post", "/v1/pm-fleet/tools/execute", "pm.execute"),
    ("post", "/v1/audit", "audit.write"),
    ("post", "/v1/mcp/discover", "mcp.write"),
    ("patch", "/v1/skills/some-skill/toggle", "skills.write"),
]


@pytest.mark.parametrize(("method", "path", "scope"), CASES)
def test_zero_permission_user_is_refused(authed_client, method, path, scope):
    kwargs = {} if method == "delete" else {"json": {}}
    response = getattr(authed_client, method)(path, **kwargs)
    assert response.status_code == 403, (
        f"{method.upper()} {path} answered {response.status_code} for a "
        f"permissions=[] user; expected 403 requiring {scope!r}"
    )
    assert scope in response.json()["detail"]


def test_product_surface_is_not_gated(authed_client):
    """The exemptions are load-bearing in the other direction: the daily
    account's ordinary flow must NOT 403 at the middleware. 404/422 are fine —
    they prove the request reached the handler."""
    for method, path in [
        ("post", "/v1/tasks"),
        ("post", "/v1/memory/entries"),
        ("post", "/v1/chat/sessions"),
        ("put", "/v1/dashboard/layout"),
        ("post", "/v1/workspaces"),
    ]:
        response = getattr(authed_client, method)(path, json={})
        assert response.status_code != 403, (
            f"{method.upper()} {path} 403'd — product surface must stay "
            "reachable for the daily account"
        )
