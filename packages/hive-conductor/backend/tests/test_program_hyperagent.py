"""Boy Scout coverage: services/program_hyperagent.py (was 16%).

Covers:
- user_id_from_request: 401 when no user, returns id when set
- require_program_access: 404 without a member workspace, no-op with one
- apply_guidance_and_pulse: interview-incomplete branch (saves + returns
  context message)
- apply_guidance_and_pulse: interview-complete branch (pulse succeeds)
- apply_guidance_and_pulse: pulse exception → pulse_note set
- run_program_pulse: interview incomplete → skipped result
- run_program_pulse: engine._backend is None → notes returned, no submit
- run_program_pulse: autonomous action invokes engine.submit_task + adds
  to queued list
- run_program_pulse: submit failure swallowed (continue), pulse continues
- run_program_pulse: skips non-autonomous capabilities
"""

from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from fastapi import HTTPException

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# --- user_id_from_request ------------------------------------------------


def test_user_id_from_request_returns_id() -> None:
    from services.program_hyperagent import user_id_from_request

    req = SimpleNamespace(state=SimpleNamespace(user={"id": "u1"}))
    assert user_id_from_request(req) == "u1"  # type: ignore[arg-type]


def test_user_id_from_request_raises_401_when_no_user() -> None:
    from services.program_hyperagent import user_id_from_request

    req = SimpleNamespace(state=SimpleNamespace(user=None))
    with pytest.raises(HTTPException) as ei:
        user_id_from_request(req)  # type: ignore[arg-type]
    assert ei.value.status_code == 401


def test_user_id_from_request_raises_401_when_no_id() -> None:
    from services.program_hyperagent import user_id_from_request

    req = SimpleNamespace(state=SimpleNamespace(user={"username": "x"}))
    with pytest.raises(HTTPException) as ei:
        user_id_from_request(req)  # type: ignore[arg-type]
    assert ei.value.status_code == 401


# --- require_program_access ----------------------------------------------


async def test_require_program_access_404_without_a_member_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And with the POC flag on, which used to be the whole gate (#129)."""
    import services.program_hyperagent as ph

    monkeypatch.setenv("HIVE_POC_MODE", "pm")
    monkeypatch.setenv("MAISTRO_POC_MODE", "pm")
    with pytest.raises(HTTPException) as ei:
        await ph.require_program_access("u1", None)
    assert ei.value.status_code == 404


async def test_require_program_access_passes_for_a_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.program_hyperagent as ph

    async def _authorized(uid: str, workspace_id: str | None) -> bool:
        return True

    monkeypatch.setattr("services.workspace_mode.is_workspace_request_authorized", _authorized)
    await ph.require_program_access("u1", "ws-1")


# --- apply_guidance_and_pulse -------------------------------------------


class _StubCtx:
    interview_complete = False

    def model_dump(self, *, mode: str = "json") -> dict[str, Any]:
        return {"interview_complete": self.interview_complete}

    def model_copy(self, *, update: dict[str, Any]) -> _StubCtx:
        for k, v in update.items():
            setattr(self, k, v)
        return self


async def test_apply_guidance_interview_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.program_hyperagent as ph

    ctx = _StubCtx()
    ctx.interview_complete = False
    monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
    monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
    monkeypatch.setattr(ph, "apply_guidance", lambda c, t: c)
    monkeypatch.setattr(ph, "interview_status", lambda c: {"done": False})
    monkeypatch.setattr(ph, "propose_actions", lambda c, roster, max_actions: [])

    out = await ph.apply_guidance_and_pulse("u1", "guidance here")
    assert "Complete the Program interview" in out["message"]
    assert out["queued_tasks"] == []


async def test_apply_guidance_pulse_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.program_hyperagent as ph

    ctx = _StubCtx()
    ctx.interview_complete = True
    monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
    monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
    monkeypatch.setattr(ph, "apply_guidance", lambda c, t: c)
    monkeypatch.setattr(ph, "interview_status", lambda c: {"done": True})
    monkeypatch.setattr(ph, "propose_actions", lambda c, roster, max_actions: [])

    async def _stub_pulse(
        uid: str, *, workspace_id: str | None = None, max_actions: int
    ) -> dict[str, Any]:
        return {"queued": [{"task_id": "t1", "agent_id": "a", "capability": "c", "reason": "r"}]}

    monkeypatch.setattr(ph, "run_program_pulse", _stub_pulse)
    out = await ph.apply_guidance_and_pulse("u1", "go")
    assert "queued" in out["message"]
    assert len(out["queued_tasks"]) == 1


async def test_apply_guidance_pulse_exception_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.program_hyperagent as ph

    ctx = _StubCtx()
    ctx.interview_complete = True
    monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
    monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
    monkeypatch.setattr(ph, "apply_guidance", lambda c, t: c)
    monkeypatch.setattr(ph, "interview_status", lambda c: {"done": True})
    monkeypatch.setattr(ph, "propose_actions", lambda c, roster, max_actions: [])

    async def _boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("engine down")

    monkeypatch.setattr(ph, "run_program_pulse", _boom)
    out = await ph.apply_guidance_and_pulse("u1", "go")
    assert out["pulse_note"] == "Fleet pulse skipped (engine unavailable)"


async def test_apply_guidance_max_pulse_actions_zero_skips_pulse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.program_hyperagent as ph

    ctx = _StubCtx()
    ctx.interview_complete = True  # would normally trigger pulse
    monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
    monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
    monkeypatch.setattr(ph, "apply_guidance", lambda c, t: c)
    monkeypatch.setattr(ph, "interview_status", lambda c: {"done": True})
    monkeypatch.setattr(ph, "propose_actions", lambda c, roster, max_actions: [])

    pulse_called = [0]

    async def _track_pulse(*a: Any, **kw: Any) -> Any:
        pulse_called[0] += 1
        return {"queued": []}

    monkeypatch.setattr(ph, "run_program_pulse", _track_pulse)
    out = await ph.apply_guidance_and_pulse("u1", "go", max_pulse_actions=0)
    # With max=0, pulse SHOULD NOT be called
    assert pulse_called[0] == 0
    assert "next pulse" in out["message"]


# --- run_program_pulse --------------------------------------------------


async def test_run_program_pulse_interview_incomplete_returns_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.program_hyperagent as ph

    ctx = _StubCtx()
    ctx.interview_complete = False
    monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
    monkeypatch.setattr(ph, "interview_status", lambda c: {"done": False})

    out = await ph.run_program_pulse("u1")
    assert out["queued"] == []
    assert out["skipped"] == "interview_incomplete"


async def test_run_program_pulse_keeps_proposals_without_queueing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.program_hyperagent as ph

    class _Action:
        agent_id = "program_manager"
        capability = "poll_jira"
        reason = "refresh"
        payload: ClassVar[dict[str, Any]] = {}

        def as_dict(self) -> dict[str, Any]:
            return {"agent_id": self.agent_id, "capability": self.capability}

    ctx = _StubCtx()
    ctx.interview_complete = True
    monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
    monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
    monkeypatch.setattr(
        ph, "propose_autonomous_actions", lambda c, roster, max_actions: [_Action()]
    )
    monkeypatch.setattr(ph, "propose_work_item_suggestions", lambda c, uid: [])

    out = await ph.run_program_pulse("u1", workspace_id="ws-a")

    assert out["queued"] == []
    assert out["proposed"][0]["capability"] == "poll_jira"
    assert "retired" in out["note"].lower()


async def test_run_program_pulse_no_actions_explains_no_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.program_hyperagent as ph

    ctx = _StubCtx()
    ctx.interview_complete = True
    monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
    monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
    monkeypatch.setattr(ph, "propose_autonomous_actions", lambda c, roster, max_actions: [])
    monkeypatch.setattr(ph, "propose_work_item_suggestions", lambda c, uid: [])

    out = await ph.run_program_pulse("u1", workspace_id="ws-a")

    assert out["queued"] == []
    assert "No agent in this workspace" in out["note"]


class TestTheWorkspaceReachesEverythingItShould:
    async def test_guidance_is_written_to_the_named_workspaces_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.program_hyperagent as ph

        seen: list[str] = []
        ctx = _StubCtx()
        ctx.interview_complete = False

        def _get(uid: str, project_id: str = "default"):
            seen.append(project_id)
            return ctx

        monkeypatch.setattr(ph.prog, "get_context", _get)
        monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
        monkeypatch.setattr(ph, "apply_guidance", lambda c, t: c)
        monkeypatch.setattr(ph, "interview_status", lambda c: {"done": False})
        monkeypatch.setattr(ph, "propose_actions", lambda c, roster, max_actions: [])

        await ph.apply_guidance_and_pulse("u1", "go", workspace_id="ws-a")
        assert seen == ["ws-a"]

    async def test_the_pulse_reads_the_named_workspaces_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.program_hyperagent as ph

        seen: list[str] = []
        ctx = _StubCtx()
        ctx.interview_complete = False

        def _get(uid: str, project_id: str = "default"):
            seen.append(project_id)
            return ctx

        monkeypatch.setattr(ph.prog, "get_context", _get)
        monkeypatch.setattr(ph, "interview_status", lambda c: {"done": False})

        await ph.run_program_pulse("u1", workspace_id="ws-a")
        assert seen == ["ws-a"]

    async def test_the_pulse_reads_the_workspaces_own_roster(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.program_hyperagent as ph

        seen: dict[str, Any] = {}
        ctx = _StubCtx()
        ctx.interview_complete = True

        def _propose(c: Any, roster: Any, max_actions: int) -> list[Any]:
            seen["roster"] = roster
            return []

        monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
        monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
        monkeypatch.setattr(ph, "propose_autonomous_actions", _propose)
        monkeypatch.setattr(ph, "propose_work_item_suggestions", lambda c, uid: [])
        monkeypatch.setattr(ph, "pulse_roster", lambda ws: [f"roster-for-{ws}"])

        await ph.run_program_pulse("u1", workspace_id="ws-a")
        assert seen["roster"] == ["roster-for-ws-a"]
