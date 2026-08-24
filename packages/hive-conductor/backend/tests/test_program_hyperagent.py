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


def test_require_program_access_404_without_a_member_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And with the POC flag on, which used to be the whole gate (#129)."""
    import services.program_hyperagent as ph

    monkeypatch.setenv("HIVE_POC_MODE", "pm")
    monkeypatch.setenv("MAISTRO_POC_MODE", "pm")
    with pytest.raises(HTTPException) as ei:
        ph.require_program_access("u1", None)
    assert ei.value.status_code == 404


def test_require_program_access_passes_for_a_member(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.program_hyperagent as ph

    monkeypatch.setattr(
        "services.workspace_mode.is_workspace_request_authorized", lambda uid, ws: True
    )
    ph.require_program_access("u1", "ws-1")  # no raise


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
    monkeypatch.setattr(ph, "propose_actions", lambda c, max_actions: [])

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
    monkeypatch.setattr(ph, "propose_actions", lambda c, max_actions: [])

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
    monkeypatch.setattr(ph, "propose_actions", lambda c, max_actions: [])

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
    monkeypatch.setattr(ph, "propose_actions", lambda c, max_actions: [])

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


async def test_run_program_pulse_no_queue_returns_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.program_hyperagent as ph

    ctx = _StubCtx()
    ctx.interview_complete = True
    monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
    monkeypatch.setattr(ph, "propose_autonomous_actions", lambda c, max_actions: [])
    monkeypatch.setattr(ph, "propose_work_item_suggestions", lambda c, uid: [])

    class _Engine:
        _backend = None  # not running

    monkeypatch.setattr(ph, "get_engine", lambda: _Engine())
    out = await ph.run_program_pulse("u1")
    assert out["queued"] == []
    assert out["note"] == "Task engine not running"


async def test_run_program_pulse_submits_autonomous_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.program_hyperagent as ph

    ctx = _StubCtx()
    ctx.interview_complete = True
    monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
    monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
    monkeypatch.setattr(ph.prog, "context_dict", lambda uid, project_id="default": {})

    class _Action:
        agent_id = "agent-1"
        capability = "auto_capability"
        reason = "because"
        payload: ClassVar[dict[str, Any]] = {}

        def as_dict(self) -> dict[str, Any]:
            return {"agent_id": self.agent_id, "capability": self.capability}

    class _Sugg:
        def as_dict(self) -> dict[str, Any]:
            return {"s": True}

    monkeypatch.setattr(ph, "propose_autonomous_actions", lambda c, max_actions: [_Action()])
    monkeypatch.setattr(ph, "propose_work_item_suggestions", lambda c, uid: [_Sugg()])
    monkeypatch.setattr(ph, "is_autonomous", lambda cap: True)
    monkeypatch.setattr(
        ph,
        "resolve_agent_task",
        lambda a, c, p, workspace_id=None: ("tt", "desc", "agent-1"),
    )
    monkeypatch.setattr("maistro.agents.program_context.context_for_task", lambda c: {})

    submitted: list[Any] = []

    class _Rec:
        id = "task-1"

    class _Engine:
        _backend = object()

        async def submit_task(self, *a: Any, **kw: Any) -> Any:
            submitted.append((a, kw))
            return _Rec()

    monkeypatch.setattr(ph, "get_engine", lambda: _Engine())
    out = await ph.run_program_pulse("u1")
    assert len(submitted) == 1
    assert out["queued"][0]["task_id"] == "task-1"


async def test_run_program_pulse_submit_failure_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.program_hyperagent as ph

    ctx = _StubCtx()
    ctx.interview_complete = True
    monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
    monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
    monkeypatch.setattr(ph.prog, "context_dict", lambda uid, project_id="default": {})

    class _Action:
        agent_id = "a"
        capability = "c"
        reason = "r"
        payload: ClassVar[dict[str, Any]] = {}

        def as_dict(self) -> dict[str, Any]:
            return {"a": "x"}

    monkeypatch.setattr(ph, "propose_autonomous_actions", lambda c, max_actions: [_Action()])
    monkeypatch.setattr(ph, "propose_work_item_suggestions", lambda c, uid: [])
    monkeypatch.setattr(ph, "is_autonomous", lambda cap: True)
    monkeypatch.setattr(
        ph, "resolve_agent_task", lambda a, c, p, workspace_id=None: ("tt", "desc", "agent")
    )
    monkeypatch.setattr("maistro.agents.program_context.context_for_task", lambda c: {})

    class _Engine:
        _backend = object()

        async def submit_task(self, *a: Any, **kw: Any) -> Any:
            raise RuntimeError("queue rejected")

    monkeypatch.setattr(ph, "get_engine", lambda: _Engine())
    out = await ph.run_program_pulse("u1")
    # Submission failed → queued is empty but no exception bubbled
    assert out["queued"] == []


async def test_run_program_pulse_skips_non_autonomous_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.program_hyperagent as ph

    ctx = _StubCtx()
    ctx.interview_complete = True
    monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
    monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
    monkeypatch.setattr(ph.prog, "context_dict", lambda uid, project_id="default": {})

    class _Action:
        agent_id = "a"
        capability = "needs_human"
        reason = "r"
        payload: ClassVar[dict[str, Any]] = {}

        def as_dict(self) -> dict[str, Any]:
            return {}

    monkeypatch.setattr(ph, "propose_autonomous_actions", lambda c, max_actions: [_Action()])
    monkeypatch.setattr(ph, "propose_work_item_suggestions", lambda c, uid: [])
    monkeypatch.setattr(ph, "is_autonomous", lambda cap: False)

    submitted = [0]

    class _Engine:
        _backend = object()

        async def submit_task(self, *a: Any, **kw: Any) -> Any:
            submitted[0] += 1

    monkeypatch.setattr(ph, "get_engine", lambda: _Engine())
    out = await ph.run_program_pulse("u1")
    assert submitted[0] == 0  # non-autonomous → never submitted
    assert out["queued"] == []


# --- workspace scoping (Codex P1 x3 on #216) --------------------------------


class TestTheWorkspaceReachesEverythingItShould:
    """`workspace_id` arrived for agent resolution and stopped there.

    Three consequences, each its own P1: guidance was written to the default
    program context while the caller named a workspace; the pulse read that
    same default context, so a completed `ws-a` interview could report as
    incomplete; and `submit_task` omitted the workspace, which
    `EngineService.submit_task` reads as the deployment's default — filing
    autonomous work in another Project while carrying a `ws-a` agent.
    """

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
        monkeypatch.setattr(ph, "propose_actions", lambda c, max_actions: [])

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

    async def test_a_queued_pulse_task_names_the_workspace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.program_hyperagent as ph

        captured: dict[str, object] = {}

        class _Rec:
            id = "t1"

        class _Engine:
            _backend = object()

            async def submit_task(self, *args, **kwargs):
                captured.update(kwargs)
                return _Rec()

        class _Action:
            agent_id = "delivery"
            capability = "poll_jira"
            reason = "r"
            payload: ClassVar[dict[str, Any]] = {}

            def as_dict(self) -> dict[str, Any]:
                return {}

        ctx = _StubCtx()
        ctx.interview_complete = True
        monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
        monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
        monkeypatch.setattr(ph.prog, "context_dict", lambda uid, project_id="default": {})
        monkeypatch.setattr(ph, "interview_status", lambda c: {"done": True})
        monkeypatch.setattr(ph, "propose_autonomous_actions", lambda c, max_actions: [_Action()])
        monkeypatch.setattr(ph, "propose_work_item_suggestions", lambda c, uid: [])
        monkeypatch.setattr(ph, "is_autonomous", lambda cap: True)
        monkeypatch.setattr(ph, "get_engine", lambda: _Engine())
        monkeypatch.setattr(
            ph,
            "resolve_agent_task",
            lambda a, c, p, workspace_id=None: ("delivery", "d", "delivery"),
        )
        monkeypatch.setattr(ph, "_get_atlassian_pats", lambda uid: {})
        # Imported inside the loop body, so patched at its source rather than
        # on `ph`. The stub context is not a real ProgramContext and this test
        # is about the workspace reaching `submit_task`, not about projection.
        monkeypatch.setattr("maistro.agents.program_context.context_for_task", lambda c: {})

        await ph.run_program_pulse("u1", workspace_id="ws-a")

        assert captured.get("workspace_id") == "ws-a"

    async def test_a_persona_without_the_proposed_agents_is_told_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`propose_autonomous_actions` names PM Fleet's roster, so a
        `content_creator` workspace produces actions none of its agents can
        serve. Returning an empty `queued` beside a full `proposed` read as
        "the pulse ran and found nothing to do"."""
        import services.program_hyperagent as ph

        class _Engine:
            _backend = object()

        class _Action:
            agent_id = "program_manager"
            capability = "fetch_program_state"
            reason = "r"
            payload: ClassVar[dict[str, Any]] = {}

            def as_dict(self) -> dict[str, Any]:
                return {}

        ctx = _StubCtx()
        ctx.interview_complete = True
        monkeypatch.setattr(ph.prog, "get_context", lambda uid, project_id="default": ctx)
        monkeypatch.setattr(ph.prog, "save_context", lambda c: c)
        monkeypatch.setattr(ph.prog, "context_dict", lambda uid, project_id="default": {})
        monkeypatch.setattr(ph, "interview_status", lambda c: {"done": True})
        monkeypatch.setattr(ph, "propose_autonomous_actions", lambda c, max_actions: [_Action()])
        monkeypatch.setattr(ph, "propose_work_item_suggestions", lambda c, uid: [])
        monkeypatch.setattr(ph, "is_autonomous", lambda cap: True)
        monkeypatch.setattr(ph, "get_engine", lambda: _Engine())

        def _unavailable(a, c, p, workspace_id=None):
            raise ValueError(f"Unknown agent: {a}")

        monkeypatch.setattr(ph, "resolve_agent_task", _unavailable)

        out = await ph.run_program_pulse("u1", workspace_id="ws-a")

        assert out["queued"] == []
        assert "program_manager" in out["note"]
