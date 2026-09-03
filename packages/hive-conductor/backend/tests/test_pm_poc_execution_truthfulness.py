"""Fail-closed acceptance tests for retiring PM-Fleet execution authority (#129)."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
import stores


@pytest.fixture
def clear_pm_state():
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


async def test_direct_pm_capability_submission_is_refused_before_backend() -> None:
    from services.engine import EngineService

    class _Backend:
        called = False

        async def submit(self, *args: Any, **kwargs: Any) -> Any:
            self.called = True
            raise AssertionError("retired PM capability reached generic task backend")

    backend = _Backend()
    svc = EngineService()
    svc._backend = backend

    with pytest.raises(ValueError, match="retired"):
        await svc.submit_task(
            "program_manager",
            "poll Jira",
            agent_id="program_manager",
            capability="poll_jira",
        )

    assert backend.called is False


async def test_program_pulse_keeps_proposals_but_never_queues_pm_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.program_hyperagent as ph

    class _Ctx:
        interview_complete = True

        def model_dump(self, *, mode: str = "json") -> dict[str, Any]:
            return {"interview_complete": True}

        def model_copy(self, *, update: dict[str, Any]) -> _Ctx:
            return self

    class _Action:
        agent_id = "program_manager"
        capability = "poll_jira"
        reason = "refresh state"
        payload: ClassVar[dict[str, Any]] = {}

        def as_dict(self) -> dict[str, Any]:
            return {
                "agent_id": self.agent_id,
                "capability": self.capability,
                "reason": self.reason,
            }

    ctx = _Ctx()
    monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
    monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
    monkeypatch.setattr(
        ph, "propose_autonomous_actions", lambda c, roster, max_actions: [_Action()]
    )
    monkeypatch.setattr(ph, "propose_work_item_suggestions", lambda c, uid: [])
    monkeypatch.setattr(ph, "pulse_roster", lambda workspace_id: [])

    out = await ph.run_program_pulse("u1", workspace_id="ws-1")

    assert out["queued"] == []
    assert out["proposed"][0]["capability"] == "poll_jira"
    assert "retired" in out["note"].lower()


def test_work_item_confirm_posts_stub_without_launching_retired_pm_task(
    admin_client,
    monkeypatch: pytest.MonkeyPatch,
    clear_pm_state,
) -> None:
    ws = admin_client.post(
        "/v1/workspaces",
        json={"persona_template_id": "pm_fleet", "name": "Truthful PM WS"},
    )
    assert ws.status_code == 201
    workspace_id = ws.json()["id"]

    suggested = admin_client.post(
        f"/v1/work-items/suggest?workspace_id={workspace_id}",
        json={"work_type": "epic", "reason": "test truthful retirement"},
    )
    assert suggested.status_code == 200
    draft_id = suggested.json()["draft"]["id"]

    clarified = admin_client.post(
        f"/v1/work-items/{draft_id}/clarify",
        json={
            "answers": {
                "summary": "Do the thing",
                "description": "Because reasons",
                "parent_key": "X-1",
            }
        },
    )
    assert clarified.status_code == 200

    confirmed = admin_client.post(f"/v1/work-items/{draft_id}/confirm")

    assert confirmed.status_code == 200
    assert confirmed.json()["task_id"] is None
    assert "retired" in confirmed.json()["execution_note"].lower()
    assert confirmed.json()["jira"]["issue_key"]
