"""Result-state taxonomy classification (epic M4-I)."""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph.nodes.base import BaseNode, NodeContext, NodeResult, pause_until
from maistro.graph.verification import ResultState, classify_result_state


def _result(**metadata: object) -> NodeResult:
    return NodeResult(success=True, output={"ok": True}, metadata=dict(metadata))


def test_failed_results_have_no_post_state_to_classify() -> None:
    assert classify_result_state(NodeResult(success=False, status="failed")) is None


def test_explicit_override_wins() -> None:
    assert (
        classify_result_state(_result(result_state="terminal", goal_satisfied=False))
        is ResultState.TERMINAL
    )
    assert classify_result_state(_result(result_state="actionable")) is ResultState.ACTIONABLE
    assert classify_result_state(_result(result_state="transitional")) is ResultState.TRANSITIONAL


def test_unknown_override_raises_instead_of_degrading() -> None:
    with pytest.raises(ValueError, match="result_state"):
        classify_result_state(_result(result_state="finshed"))


def test_goal_satisfied_is_terminal() -> None:
    assert classify_result_state(_result(goal_satisfied=True)) is ResultState.TERMINAL


def test_requires_actor_action_is_actionable() -> None:
    assert classify_result_state(_result(requires_actor_action=True)) is ResultState.ACTIONABLE


def test_human_gated_pause_is_actionable() -> None:
    result = NodeResult(
        success=True, status="paused", metadata={"paused_reason": "awaiting_human_answer"}
    )
    assert classify_result_state(result) is ResultState.ACTIONABLE


def test_system_gated_pause_is_not_actionable() -> None:
    result = NodeResult(
        success=True, status="paused", metadata={"paused_reason": "awaiting_harness"}
    )
    assert classify_result_state(result) is ResultState.TRANSITIONAL


def test_unadorned_success_is_transitional() -> None:
    assert classify_result_state(_result()) is ResultState.TRANSITIONAL


class _In(BaseModel):
    pass


class _Out(BaseModel):
    answer: str = "ok"


class _HumanPauseNode(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.taxonomy_pause"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        pause_until("awaiting_human_answer")


async def test_pause_signal_through_base_run_classifies_actionable() -> None:
    node = _HumanPauseNode()
    result = await node.run(_In(), NodeContext(run_id="r", dag_id="d", node_id="n"))
    assert result.status == "paused"
    assert classify_result_state(result) is ResultState.ACTIONABLE
