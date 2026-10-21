"""Schedule CRUD and firing stay inside canonical principal/workspace scope."""

from __future__ import annotations

from typing import Any

import pytest


def _create_workspace(client: Any, name: str) -> str:
    response = client.post(
        "/v1/workspaces",
        json={"name": name, "persona_template_id": "default", "checklist": []},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_schedule(client: Any, workspace_id: str) -> dict[str, Any]:
    response = client.post(
        "/v1/schedules",
        json={
            "name": "scoped schedule",
            "cron_expression": "0 9 * * *",
            "mission_template_id": "missing-template",
            "workspace_id": workspace_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_schedule_crud_is_owner_and_workspace_scoped(admin_client: Any, authed_client: Any) -> None:
    owner_workspace = _create_workspace(admin_client, "schedule owner")
    foreign_workspace = _create_workspace(admin_client, "schedule foreign")
    added = admin_client.post(
        f"/v1/workspaces/{foreign_workspace}/members",
        json={"user_id": "user", "role": "editor"},
    )
    assert added.status_code == 200, added.text

    owned = _create_schedule(admin_client, owner_workspace)
    try:
        # The row's owner/actor is stamped server-side from the authenticated
        # caller; the canonical actor it fires under is that same principal
        # (asserted on the Run in the manual-fire test below).
        assert owned["user_id"] == "admin"
        assert owned["workspace_id"] == owner_workspace
        assert owned["project_id"]

        assert admin_client.get("/v1/schedules").json() == [owned]
        assert authed_client.get("/v1/schedules").json() == []

        # GET is not elevation-gated, so this reaches the schedule route and
        # proves that a foreign id is enumeration-resistant.
        foreign_read = authed_client.get(f"/v1/schedules/{owned['id']}")
        assert foreign_read.status_code == 404, foreign_read.text

        updated = admin_client.put(
            f"/v1/schedules/{owned['id']}",
            json={
                "name": "renamed",
                # Scope fields are not an authority-bearing transfer API.
                "workspace_id": foreign_workspace,
                "project_id": "foreign-project",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["user_id"] == "admin"
        assert updated.json()["workspace_id"] == owner_workspace
        assert updated.json()["project_id"] != "foreign-project"
    finally:
        admin_client.delete(f"/v1/schedules/{owned['id']}")


def test_a_revoked_schedule_is_not_eligible_for_automatic_fire(monkeypatch: Any) -> None:
    import asyncio
    import pathlib
    import sys
    from datetime import UTC, datetime

    backend = pathlib.Path(__file__).resolve().parents[1]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    from services import workspace_authority
    from services.scheduler import _ScheduleRunner

    async def scenario() -> None:
        workspace = await workspace_authority.create_workspace(
            creator_user_id="owner",
            name="revocation",
            persona_template_id="default",
            checklist=[],
            theme_id="default",
            voice_tone_override=None,
        )
        await workspace_authority.set_member(workspace.id, user_id="scheduled-user", role="editor")
        await workspace_authority.remove_member(workspace.id, user_id="scheduled-user")

        class Row:
            id = "revoked-schedule"
            user_id = "scheduled-user"
            actor_principal_id = "scheduled-user"
            workspace_id = workspace.id
            project_id = ""
            enabled = True
            cron_expression = "* * * * *"
            mission_template_id = "template"
            name = "revoked"
            created_at = datetime(2026, 1, 1, tzinfo=UTC)
            last_run = datetime(2026, 1, 1, tzinfo=UTC)

        fired: list[str] = []

        async def capture(self: Any, sid: str, schedule: Any, **kwargs: Any) -> None:
            fired.append(sid)

        monkeypatch.setattr(_ScheduleRunner, "_fire_schedule", capture)
        await _ScheduleRunner()._evaluate_schedule(
            "revoked-schedule", Row(), now=datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
        )
        assert fired == []

    asyncio.run(scenario())


def test_manual_fire_is_owner_scoped_and_stamps_the_requesting_principal(
    admin_client: Any,
    monkeypatch: pytest.MonkeyPatch,
    canonical_graph_spine: Any,
) -> None:
    """Foreign manual fire over HTTP is refused even for an authorized member.

    The second principal here is a real, separately logged-in account that has
    been assigned *and* elevated to ``schedules.write`` through the production
    two-step flow, so the privilege middleware deliberately passes its request
    and the 404 for the owner's schedule is the route's own scope decision —
    the same enumeration-resistant answer a missing id gets. The owner's fire
    really starts a Run carrying the schedule actor, the HTTP requester, and
    the scheduler service identity as three distinguishable provenance facts.
    """
    import asyncio

    import stores
    from adapters.maistro_core import StubAgentPort
    from fastapi.testclient import TestClient
    from services import dag_agents
    from services.dag_agents import get_registry
    from services.engine import get_engine
    from services.scheduler import _ScheduleRunner

    from maistro.scheduling import InMemoryScheduleStore

    # Keep the scheduler on the standalone compatibility path (engine port has
    # no container) while letting registered-DAG execution use the canonical
    # spine, mirroring _explicit_graph_fixture in test_scheduler.py.
    monkeypatch.setattr(get_engine(), "_agent_port", StubAgentPort())
    monkeypatch.setattr(dag_agents, "_container", lambda: canonical_graph_spine)

    async def _noop_validate(graph: Any) -> None:
        return None

    monkeypatch.setattr(
        canonical_graph_spine.run_store, "_validate_graph_scope", _noop_validate
    )

    template_id = "sched-scope-fire"
    get_registry().register(
        {
            "id": template_id,
            "name": template_id,
            "entry_node": "only",
            "nodes": [{"id": "only", "kind": "transform.alias_keys", "config": {"mapping": {}}}],
            "edges": [],
        }
    )
    # No embedded core bridge in this suite: the fire takes the compatibility
    # execution path, with the same in-memory canonical store the route's own
    # scope projection writes through.
    monkeypatch.setattr(
        _ScheduleRunner, "_canonical_store", staticmethod(lambda: InMemoryScheduleStore())
    )

    previous_user = stores.users["user"]
    member = TestClient(app=admin_client.app)
    login = member.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200, login.text
    schedule_id: str | None = None
    try:
        assigned = admin_client.patch(
            "/v1/auth/users/user/permissions",
            json={"permissions": ["schedules.write"]},
        )
        assert assigned.status_code == 200, assigned.text
        elevated = member.post(
            "/v1/auth/elevate",
            json={
                "password": "testpass",
                "permissions": ["schedules.write"],
                "task_id": "schedule-fire-scope-check",
            },
        )
        assert elevated.status_code == 200, elevated.text

        owner_workspace = _create_workspace(admin_client, "manual fire owner")
        created = admin_client.post(
            "/v1/schedules",
            json={
                "name": "manual fire target",
                "cron_expression": "0 9 * * *",
                "mission_template_id": template_id,
                "workspace_id": owner_workspace,
            },
        )
        assert created.status_code == 201, created.text
        schedule_id = created.json()["id"]

        foreign_fire = member.post(f"/v1/schedules/{schedule_id}/run")
        assert foreign_fire.status_code == 404, foreign_fire.text

        fired = admin_client.post(f"/v1/schedules/{schedule_id}/run")
        assert fired.status_code == 200, fired.text
        run_id = fired.json()["last_run_id"]
        assert run_id, "a manual fire returns the Run it started"

        run = asyncio.run(canonical_graph_spine.run_store.get_run(run_id))
        assert run.actor_principal_id == "admin"
        assert run.workspace_id == owner_workspace
        assert run.provenance["manual_requesting_principal_id"] == "admin"
        assert run.provenance["scheduler_service_id"] == "hive-scheduler"
    finally:
        if schedule_id is not None:
            admin_client.delete(f"/v1/schedules/{schedule_id}")
        stores.users["user"] = previous_user
        get_registry().deregister(template_id)
