"""Recovery coverage for multiple HITL nodes in one durable frontier."""

from __future__ import annotations

from pathlib import Path

from maistro.graph.durable_runs import InMemoryDurableRunStore, SqliteDurableRunStore
from maistro.graph.execution_state import GraphExecutionState
from maistro.runs.lifecycle import transition_node_run
from maistro.runs.model import NodeRun, RunStatus

from .._canonical_helpers import durable_record


def _paused_node_run(run_id: str, node_id: str, ordinal: int) -> NodeRun:
    node_run = NodeRun(run_id=run_id, node_id=node_id, ordinal=ordinal)
    node_run = transition_node_run(node_run, RunStatus.QUEUED)
    node_run = transition_node_run(node_run, RunStatus.RUNNING)
    return transition_node_run(node_run, RunStatus.PAUSED)


def _two_pause_record(run_id: str):
    dag = {
        "id": "two-hitl",
        "nodes": [{"id": "left"}, {"id": "right"}],
        "edges": [],
        "entry_node": "left",
    }
    left = _paused_node_run(run_id, "left", 1)
    right = _paused_node_run(run_id, "right", 2)
    record = durable_record(
        dag,
        run_id=run_id,
        status=RunStatus.PAUSED,
        active_node_id="left",
        node_runs=(left, right),
        metadata={
            "initial_inputs": {},
            "hitl_answers": {},
            "pauses": {
                "left": {"kind": "hitl", "metadata": {"question": "Left?"}},
                "right": {"kind": "hitl", "metadata": {"question": "Right?"}},
            },
            "pause": {"kind": "hitl", "metadata": {"question": "Left?"}},
        },
    )
    state_values = record.graph_state.model_dump(mode="json")
    state_values["active_node_ids"] = ["left", "right"]
    state = GraphExecutionState.model_validate(state_values)
    return record.model_copy(update={"graph_state": state})


async def _assert_independent_answers(store, run_id: str) -> None:
    await store.create(_two_pause_record(run_id))

    first = await store.submit_hitl_answer(run_id, "left", {"answer": "L"})
    assert first.status is RunStatus.PAUSED
    assert first.graph_state.active_node_ids == ("left", "right")
    assert [node.status for node in first.node_runs] == [RunStatus.QUEUED, RunStatus.PAUSED]
    assert first.hitl_answers["left"]["answer"] == "L"
    assert tuple(first.graph_state.metadata["pauses"]) == ("right",)
    assert first.graph_state.metadata["pause"]["metadata"]["question"] == "Right?"

    second = await store.submit_hitl_answer(run_id, "right", {"answer": "R"})
    assert second.status is RunStatus.QUEUED
    assert second.graph_state.active_node_ids == ("left", "right")
    assert [node.status for node in second.node_runs] == [RunStatus.QUEUED, RunStatus.QUEUED]
    assert second.hitl_answers["right"]["answer"] == "R"
    assert "pauses" not in second.graph_state.metadata
    assert "pause" not in second.graph_state.metadata


async def test_in_memory_store_answers_multi_node_hitl_frontier_independently() -> None:
    await _assert_independent_answers(InMemoryDurableRunStore(), "multi-hitl-memory")


async def test_sqlite_store_answers_multi_node_hitl_frontier_independently(tmp_path: Path) -> None:
    await _assert_independent_answers(
        SqliteDurableRunStore(tmp_path / "frontier-hitl.db"),
        "multi-hitl-sqlite",
    )
