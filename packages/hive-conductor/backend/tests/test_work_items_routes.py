"""routes/work_items.py -- the PM gate resolves a workspace, and only a workspace.

The gate is capability-based (does this workspace's own materialized agent
roster include Jira-capable agents -- real for pm_fleet since its spawns are
named intake/program_manager/etc, not because its persona_template_id is
literally "pm_fleet"), not identity-based.

Since #129 an omitted, unknown or non-member `workspace_id` is a refusal rather
than a fall-through to the global `is_pm_poc_mode()` flag. Those three cases
used to answer 200 for every caller in a deployment with `HIVE_POC_MODE=pm`
set, and drafted against no workspace's roster at all -- which is the whole
reason the flag had to go rather than be renamed.
"""

from __future__ import annotations

import pytest
import stores


@pytest.fixture(autouse=True)
def _clear_state():
    stores_to_clear = (
        stores.workspaces,
        stores.work_item_drafts,
        stores.program_contexts,
        stores.agents,
    )
    for store in stores_to_clear:
        for key in list(store.keys()):
            store.pop(key, None)
    yield
    for store in stores_to_clear:
        for key in list(store.keys()):
            store.pop(key, None)


def _create_workspace(admin_client, persona_template_id: str) -> str:
    r = admin_client.post(
        "/v1/workspaces",
        json={"persona_template_id": persona_template_id, "name": "Test WS"},
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_omitted_workspace_id_is_refused(admin_client) -> None:
    """Work items are drafted within a workspace. There is no global roster to
    draft against any more, so naming none is a 404 rather than a 200."""
    r = admin_client.get("/v1/work-items")
    assert r.status_code == 404


def test_pm_fleet_workspace_id_is_authorized(admin_client) -> None:
    ws_id = _create_workspace(admin_client, "pm_fleet")
    r = admin_client.get(f"/v1/work-items?workspace_id={ws_id}")
    assert r.status_code == 200


def test_a_workspace_without_jira_capable_agents_is_refused(admin_client) -> None:
    """Jira work items need agents that can draft them -- unlike the onboarding
    interview, a content_creator workspace must NOT unlock this surface just
    because it resolves to a real, member workspace."""
    ws_id = _create_workspace(admin_client, "content_creator")
    r = admin_client.get(f"/v1/work-items?workspace_id={ws_id}")
    assert r.status_code == 404


def test_a_differently_named_persona_with_pm_fleet_shaped_agents_also_qualifies(
    admin_client,
) -> None:
    """No identity special-casing: the gate is "does this workspace's own
    materialized roster include Jira-capable agents", not "is
    persona_template_id literally pm_fleet". A wizard-authored persona
    whose spawns happen to be named the same way qualifies identically."""
    r = admin_client.post(
        "/v1/workspaces/persona-templates",
        json={
            "id": "field_ops",
            "display_name": "Field Ops",
            "agents": [
                {"agent": "intake", "role": "Takes requests", "tools": ["create_epic"]},
            ],
        },
    )
    assert r.status_code == 201
    ws_id = _create_workspace(admin_client, "field_ops")
    r = admin_client.get(f"/v1/work-items?workspace_id={ws_id}")
    assert r.status_code == 200


def test_unknown_workspace_id_is_refused(admin_client) -> None:
    r = admin_client.get("/v1/work-items?workspace_id=does-not-exist")
    assert r.status_code == 404


def test_non_member_workspace_id_is_refused(admin_client, authed_client) -> None:
    """And refused with the same 404 an unknown workspace gets, so a caller
    cannot tell a workspace they are not in from one that does not exist."""
    ws_id = _create_workspace(admin_client, "pm_fleet")
    r = authed_client.get(f"/v1/work-items?workspace_id={ws_id}")
    assert r.status_code == 404


def test_suggest_records_the_workspaces_project_id_on_the_draft(admin_client) -> None:
    ws_id = _create_workspace(admin_client, "pm_fleet")
    r = admin_client.post(
        f"/v1/work-items/suggest?workspace_id={ws_id}",
        json={"work_type": "epic", "reason": "test"},
    )
    assert r.status_code == 200
    assert r.json()["draft"]["project_id"] == ws_id


def test_suggest_without_workspace_id_is_refused(admin_client) -> None:
    """The draft would have nothing to resolve its agent against on confirm."""
    r = admin_client.post(
        "/v1/work-items/suggest",
        json={"work_type": "epic", "reason": "test"},
    )
    assert r.status_code == 404


def test_confirm_reads_back_the_drafts_own_project_id(admin_client, monkeypatch) -> None:
    """POST .../interview/answer (default project) sets program_name; the
    suggested draft's own project (a different workspace) must NOT see it in
    its queued task's program context -- proves confirm reads draft.project_id,
    not always the global default."""
    import routes.work_items as work_items_routes

    captured: dict = {}

    class _FakeTaskRecord:
        id = "task-1"

    class _FakeEngine:
        async def submit_task(self, *args, **kwargs):
            captured["program_context"] = kwargs.get("program_context")
            return _FakeTaskRecord()

    monkeypatch.setattr(work_items_routes, "get_engine", lambda: _FakeEngine())

    admin_client.post("/v1/program/interview/answer", json={"answer": "Global Default Program"})
    ws_id = _create_workspace(admin_client, "pm_fleet")
    r = admin_client.post(
        f"/v1/work-items/suggest?workspace_id={ws_id}",
        json={"work_type": "epic", "reason": "test"},
    )
    draft_id = r.json()["draft"]["id"]
    admin_client.post(
        f"/v1/work-items/{draft_id}/clarify",
        json={
            "answers": {
                "summary": "Do the thing",
                "description": "Because reasons",
                "parent_key": "X-1",
            }
        },
    )
    r = admin_client.post(f"/v1/work-items/{draft_id}/confirm")
    assert r.status_code == 200
    assert captured["program_context"]["project_id"] == ws_id
    assert captured["program_context"]["program_name"] == ""


def test_confirm_refuses_before_posting_when_the_persona_lacks_the_agent(
    admin_client,
) -> None:
    """Codex P1 on #216: a 500 that left the draft permanently posted.

    A persona can pass the capability gate on one PM-shaped agent — the
    `field_ops` case above qualifies on `intake` alone — while an `epic` draft
    targets `program_manager`. Resolving that agent *after* `_save_draft`
    marked the draft posted turned the mismatch into a 500 with the draft
    posted and no task ever queued: unrecoverable, because a posted draft
    cannot be confirmed again.

    Resolution now happens before the side effect, so the refusal is a 409 and
    the draft is still there.
    """
    r = admin_client.post(
        "/v1/workspaces/persona-templates",
        json={
            "id": "intake_only",
            "display_name": "Intake Only",
            "agents": [{"agent": "intake", "role": "Takes requests", "tools": ["create_epic"]}],
        },
    )
    assert r.status_code == 201
    ws_id = _create_workspace(admin_client, "intake_only")

    r = admin_client.post(
        f"/v1/work-items/suggest?workspace_id={ws_id}",
        json={"work_type": "epic", "reason": "test"},
    )
    assert r.status_code == 200
    draft_id = r.json()["draft"]["id"]
    admin_client.post(
        f"/v1/work-items/{draft_id}/clarify",
        json={
            "answers": {
                "summary": "Do the thing",
                "description": "Because reasons",
                "parent_key": "X-1",
            }
        },
    )

    r = admin_client.post(f"/v1/work-items/{draft_id}/confirm")

    assert r.status_code == 409
    # Still confirmable once the persona gains the agent — which a 500 after
    # `_save_draft` would have made impossible.
    still_there = admin_client.get(f"/v1/work-items/{draft_id}?workspace_id={ws_id}")
    assert still_there.status_code == 200
    assert still_there.json()["draft"]["status"] != "posted"
