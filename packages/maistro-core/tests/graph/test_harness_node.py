"""Outbound foreign-harness graph node (SPEC-208 §5).

Covers three layers: the ``NodeExecutor`` seam in ``graph.node``, the
``HarnessStrategy`` prompt/output shaper, and the ``HarnessNodeExecutor`` bridge
onto ``HarnessSessionManager``. The helpers are exercised as algorithm-only
fixtures; canonical physical Graph execution remains in ``durable_runs``.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.capabilities.types import Unavailable
from maistro.graph.harness_executor import (
    HarnessExecutionError,
    HarnessNodeExecutor,
    _extract_actions,
    _extract_summary,
    _spec_role,
)
from maistro.graph.strategy import HarnessStrategy
from maistro.graph.types import AgentRole, GraphBlackboard, HarnessOutput

# --- HarnessStrategy ----------------------------------------------------------


class TestHarnessStrategy:
    def test_score_rewards_actions_and_summary(self) -> None:
        s = HarnessStrategy()
        assert s.score_output(HarnessOutput(summary="x", actions=[{"a": 1}, {"b": 2}])) == 3.0
        assert s.score_output(HarnessOutput(summary="", actions=[])) == 0.0
        assert s.score_output(HarnessOutput(summary="x", actions=[])) == 1.0

    def test_score_ignores_wrong_type(self) -> None:
        from maistro.graph.types import CodeOutput

        assert HarnessStrategy().score_output(CodeOutput(description="x")) == 0.0

    def test_update_blackboard_records_summary_annotation(self) -> None:
        bb = GraphBlackboard(task_objective="obj", workspace="/w")
        out = HarnessStrategy().update_blackboard(HarnessOutput(summary="ran tests"), bb)
        assert out.node_annotations[AgentRole.HARNESS.value] == "ran tests"

    def test_update_blackboard_noop_without_summary(self) -> None:
        bb = GraphBlackboard(task_objective="obj", workspace="/w")
        out = HarnessStrategy().update_blackboard(HarnessOutput(summary=""), bb)
        assert out.node_annotations == bb.node_annotations

    def test_build_user_prompt_with_and_without_constraints(self) -> None:
        from maistro.graph.types import GraphTask

        bb = GraphBlackboard(task_objective="obj", workspace="/w")
        s = HarnessStrategy()
        with_c = s.build_user_prompt(
            GraphTask(description="d", workspace="/w", constraints=["no net"]),
            bb,
            None,
            None,
            None,
        )
        assert "no net" in with_c and "Task: d" in with_c
        without_c = s.build_user_prompt(
            GraphTask(description="d", workspace="/w"), bb, None, None, None
        )
        assert "Constraints:\nNone" in without_c


# --- HarnessNodeExecutor bridge ----------------------------------------------


class _FakeManager:
    """Duck-typed HarnessSessionManager for the bridge tests."""

    def __init__(self, *, start: Any = "sess-1", envelope: Any = None) -> None:
        self._start = start
        self._envelope = envelope if envelope is not None else {"content": "hi", "actions": []}
        self.stopped: list[str] = []
        self.sent: list[Any] = []

    async def start(self, spec: Any, *, workdir: str) -> Any:
        self._last_spec = spec
        self._last_workdir = workdir
        return self._start

    async def send(self, session_id: str, messages: list[dict[str, Any]]) -> Any:
        self.sent.append(messages)
        return self._envelope

    async def stop(self, session_id: str) -> None:
        self.stopped.append(session_id)


async def _run_bridge(manager: Any, **kw: object) -> HarnessOutput:
    executor = HarnessNodeExecutor(manager, workdir="/repo")
    result = await executor.run(
        role=AgentRole.CODER,
        system_prompt="sys",
        user_prompt="ship it",
        blackboard=None,
        output_type=HarnessOutput,
        **kw,
    )
    assert isinstance(result, HarnessOutput)
    return result


class TestHarnessNodeExecutor:
    async def test_maps_flat_envelope(self) -> None:
        mgr = _FakeManager(envelope={"content": "done", "actions": [{"tool": "rm"}]})
        out = await _run_bridge(mgr)
        assert out.summary == "done"
        assert out.actions == [{"tool": "rm"}]
        assert mgr.stopped == ["sess-1"]  # session always stopped

    async def test_maps_openai_choices_envelope(self) -> None:
        env = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "built"}}],
            "actions": [{"tool": "ls"}],
        }
        out = await _run_bridge(_FakeManager(envelope=env))
        assert out.summary == "built"
        assert out.actions == [{"tool": "ls"}]
        assert out.raw == env

    async def test_start_unavailable_raises_and_does_not_send(self) -> None:
        mgr = _FakeManager(start=Unavailable(slot="harness_runner", reason="no provider"))
        with pytest.raises(HarnessExecutionError, match="unavailable"):
            await _run_bridge(mgr)
        assert mgr.sent == []
        assert mgr.stopped == []  # nothing to stop — never started

    async def test_send_unavailable_raises_but_stops_session(self) -> None:
        mgr = _FakeManager(envelope=Unavailable(slot="harness_runner", reason="session lost"))
        with pytest.raises(HarnessExecutionError, match="session lost"):
            await _run_bridge(mgr)
        assert mgr.stopped == ["sess-1"]  # finally-block stop still runs

    async def test_builds_spec_from_role(self) -> None:
        mgr = _FakeManager()
        await _run_bridge(mgr)
        assert mgr._last_workdir == "/repo"
        assert mgr._last_spec.description == "ship it"


# --- envelope helpers ---------------------------------------------------------


class TestEnvelopeHelpers:
    def test_extract_summary_prefers_content(self) -> None:
        assert _extract_summary({"content": "a", "choices": []}) == "a"

    def test_extract_summary_falls_back_to_choices(self) -> None:
        env = {"choices": [{"message": {"content": "b"}}]}
        assert _extract_summary(env) == "b"

    def test_extract_summary_empty_when_absent(self) -> None:
        assert _extract_summary({}) == ""
        assert _extract_summary({"choices": "notalist"}) == ""

    def test_extract_summary_handles_malformed_choices(self) -> None:
        # choices[0] not a dict → message is None
        assert _extract_summary({"choices": ["nope"]}) == ""
        # message present but content is not a string
        assert _extract_summary({"choices": [{"message": {"content": 123}}]}) == ""
        # message key absent
        assert _extract_summary({"choices": [{}]}) == ""

    def test_extract_actions_filters_non_dicts(self) -> None:
        assert _extract_actions({"actions": [{"a": 1}, "bad", 3]}) == [{"a": 1}]
        assert _extract_actions({}) == []

    def test_spec_role_maps_known_and_falls_back(self) -> None:
        from maistro.agents.spec.agent_spec import AgentRole as SpecAgentRole

        assert _spec_role(AgentRole.CODER) == SpecAgentRole.CODER
        # HARNESS has no spec counterpart → CODER fallback
        assert _spec_role(AgentRole.HARNESS) == SpecAgentRole.CODER
