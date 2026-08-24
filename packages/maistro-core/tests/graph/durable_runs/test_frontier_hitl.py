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


async def _assert_the_answer_carries_the_pause_it_settles(store, run_id: str) -> None:
    """The node's own pause payload survives into the answer it resumes on.

    `_pause_metadata_after_answer` deletes the answered node's pause entry, so a
    node that paused carrying state had no way to read it back and could only
    trust what the responder submitted. `agent.delegate_remote` paused holding
    the canonical child Run id; on resume that id either vanished or was
    whatever the answering party claimed it was.
    """
    await store.create(_two_pause_record(run_id))

    answered = await store.submit_hitl_answer(run_id, "left", {"answer": "L"})

    stamped = answered.hitl_answers["left"]["_pause"]
    assert stamped["metadata"]["question"] == "Left?"
    assert "left" not in answered.graph_state.metadata["pauses"], (
        "the pause entry is still consumed; the copy on the answer is what survives"
    )


async def _assert_a_submitted_pause_cannot_displace_the_real_one(store, run_id: str) -> None:
    """The stamp goes on after the caller's keys, on purpose.

    A responder that could set `_pause` itself would be naming the execution
    state of the node it is answering — which is exactly the thing a node must
    not learn from the party it was waiting on.
    """
    await store.create(_two_pause_record(run_id))

    answered = await store.submit_hitl_answer(
        run_id,
        "left",
        {"answer": "L", "_pause": {"metadata": {"question": "Forged?"}, "run_id": "attacker"}},
    )

    stamped = answered.hitl_answers["left"]["_pause"]
    assert stamped["metadata"]["question"] == "Left?"
    assert "run_id" not in stamped


async def test_in_memory_answer_carries_its_pause() -> None:
    await _assert_the_answer_carries_the_pause_it_settles(
        InMemoryDurableRunStore(), "run-pause-stamp"
    )


async def test_in_memory_answer_rejects_a_forged_pause() -> None:
    await _assert_a_submitted_pause_cannot_displace_the_real_one(
        InMemoryDurableRunStore(), "run-pause-forge"
    )


async def test_sqlite_answer_carries_its_pause(tmp_path: Path) -> None:
    await _assert_the_answer_carries_the_pause_it_settles(
        SqliteDurableRunStore(tmp_path / "stamp.db"), "run-pause-stamp"
    )


async def test_sqlite_answer_rejects_a_forged_pause(tmp_path: Path) -> None:
    await _assert_a_submitted_pause_cannot_displace_the_real_one(
        SqliteDurableRunStore(tmp_path / "forge.db"), "run-pause-forge"
    )
