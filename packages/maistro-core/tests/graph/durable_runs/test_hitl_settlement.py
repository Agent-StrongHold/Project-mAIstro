"""Durable timeout/cancel semantics for human-paused graph work (#737)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
    run_durable_graph,
)
from maistro.graph.durable_runs.hitl import (
    HitlDeadlineElapsed,
    HitlDeadlinePending,
    HitlSettlementError,
    expire_hitl_pauses,
    hitl_deadline,
    settlement_time,
)
from maistro.graph.durable_runs.stores import (
    InMemoryDurableRunStore,
    SqliteDurableRunStore,
)
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import BaseNode, NodeContext, pause_until
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.lifecycle import transition_attempt, transition_node_run
from maistro.runs.model import Attempt, AttemptStatus, NodeRun, RunStatus

from .._canonical_helpers import durable_record

pytestmark = [pytest.mark.contract("behavioral")]

_DEADLINE = datetime(2026, 8, 30, 20, 0, tzinfo=UTC)
_BEFORE = _DEADLINE - timedelta(seconds=1)
_AFTER = _DEADLINE + timedelta(seconds=1)


class _Empty(BaseModel):
    pass


class _CanonicalAsk(BaseNode[_Empty, _Empty]):
    kind: ClassVar[str] = "test.hitl_settlement.canonical_ask"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Empty

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Empty:
        pause_until(
            "awaiting_human_answer",
            resume_at=_DEADLINE,
            metadata={"question": "Ship it?", "timeout_seconds": 1},
        )
        return _Empty()


class _LosingTimeoutStore(InMemoryDurableRunStore):
    async def timeout_hitl(
        self,
        run_id: str,
        node_id: str,
        *,
        at: datetime | None = None,
    ) -> DurableRunRecord:
        raise ValueError("another decision won")


def _paused_node_run(run_id: str, node_id: str = "ask", ordinal: int = 1) -> NodeRun:
    node_run = NodeRun(run_id=run_id, node_id=node_id, ordinal=ordinal)
    node_run = transition_node_run(node_run, RunStatus.QUEUED, at=_BEFORE)
    node_run = transition_node_run(node_run, RunStatus.RUNNING, at=_BEFORE)
    return transition_node_run(node_run, RunStatus.PAUSED, at=_BEFORE)


def _yielded_attempt(node_run: NodeRun) -> Attempt:
    attempt = Attempt(node_run_id=node_run.node_run_id, ordinal=1)
    attempt = transition_attempt(attempt, AttemptStatus.RUNNING, at=_BEFORE)
    return transition_attempt(
        attempt,
        AttemptStatus.YIELDED,
        at=_BEFORE,
        result={
            "status": "paused",
            "paused_reason": "awaiting_human_answer",
            "resume_at": _DEADLINE.isoformat(),
            "metadata": {"question": "Ship it?", "timeout_seconds": 1},
        },
    )


def _paused_record(run_id: str) -> DurableRunRecord:
    node_run = _paused_node_run(run_id)
    attempt = _yielded_attempt(node_run)
    record = durable_record(
        {
            "id": "hitl-timeout",
            "nodes": [{"id": "ask", "kind": "human.ask_question"}],
            "edges": [],
        },
        run_id=run_id,
        status=RunStatus.PAUSED,
        active_node_id="ask",
        node_runs=(node_run,),
        metadata={
            "initial_inputs": {},
            "hitl_answers": {},
            "pauses": {
                "ask": {
                    "kind": "hitl",
                    "metadata": {"question": "Ship it?", "timeout_seconds": 1},
                    "paused_at": _BEFORE.isoformat(),
                    "resume_at": _DEADLINE.isoformat(),
                }
            },
            "pause": {
                "kind": "hitl",
                "metadata": {"question": "Ship it?", "timeout_seconds": 1},
                "paused_at": _BEFORE.isoformat(),
                "resume_at": _DEADLINE.isoformat(),
            },
        },
        resume_at=_DEADLINE,
    )
    return DurableRunRecord.model_validate(
        {**record.model_dump(mode="python"), "attempts": (attempt,)}
    )


def _with_pause_entry(
    record: DurableRunRecord,
    entry: dict[str, object] | None,
) -> DurableRunRecord:
    state_values = record.graph_state.model_dump(mode="json")
    metadata = dict(state_values["metadata"])
    if entry is None:
        metadata.pop("pauses", None)
        metadata.pop("pause", None)
    else:
        metadata["pauses"] = {"ask": entry}
        metadata["pause"] = entry
    state_values["metadata"] = metadata
    values = record.model_dump(mode="python")
    values["graph_state"] = GraphExecutionState.model_validate(state_values)
    return DurableRunRecord.model_validate(values)


def _paused_frontier_record(run_id: str) -> DurableRunRecord:
    ask = _paused_node_run(run_id)
    review = _paused_node_run(run_id, "review", 2)
    pause = {
        "kind": "hitl",
        "metadata": {"question": "Ship it?", "timeout_seconds": 1},
        "resume_at": _DEADLINE.isoformat(),
    }
    record = durable_record(
        {
            "id": "hitl-frontier",
            "nodes": [
                {"id": "ask", "kind": "human.ask_question"},
                {"id": "review", "kind": "human.approve_plan"},
            ],
            "edges": [],
        },
        run_id=run_id,
        status=RunStatus.PAUSED,
        active_node_id="ask",
        node_runs=(ask, review),
        metadata={
            "initial_inputs": {},
            "hitl_answers": {},
            "pauses": {"ask": pause, "review": pause},
            "pause": pause,
        },
        resume_at=_DEADLINE,
    )
    state_values = record.graph_state.model_dump(mode="json")
    state_values["active_node_ids"] = ["ask", "review"]
    return DurableRunRecord.model_validate(
        {
            **record.model_dump(mode="python"),
            "graph_state": GraphExecutionState.model_validate(state_values),
        }
    )


def _assert_settlement(
    record: DurableRunRecord,
    *,
    outcome: str,
    run_status: RunStatus,
    node_status: RunStatus,
    decided_at: datetime = _AFTER,
) -> None:
    assert record.run.status is run_status
    assert record.node_runs[0].status is node_status
    assert record.graph_state.active_node_ids == ()
    assert record.resume_at is None
    assert record.hitl_answers == {}
    evidence = record.graph_state.metadata["hitl_settlements"]["ask"]
    assert evidence["outcome"] == outcome
    assert evidence["decided_at"] == decided_at.isoformat()
    assert evidence["pause"]["resume_at"] == _DEADLINE.isoformat()
    assert "pauses" not in record.graph_state.metadata


@pytest.mark.ac("SPEC-083026-73c1/AC-1")
@pytest.mark.ac("SPEC-083026-73c1/AC-5")
async def test_deadline_survives_restart_and_timeout_preserves_attempt(tmp_path: Path) -> None:
    db = tmp_path / "hitl-timeout.db"
    first_store = SqliteDurableRunStore(db)
    original = _paused_record("restart-timeout")
    await first_store.create(original)
    del first_store

    reopened = SqliteDurableRunStore(db)
    expired = await expire_hitl_pauses(reopened, now=_AFTER)

    assert [record.run_id for record in expired] == ["restart-timeout"]
    settled = expired[0]
    _assert_settlement(
        settled,
        outcome="timed_out",
        run_status=RunStatus.TIMED_OUT,
        node_status=RunStatus.TIMED_OUT,
    )
    assert len(settled.attempts) == 1
    assert settled.attempts[0] == original.attempts[0]

    del reopened
    after_second_restart = await SqliteDurableRunStore(db).get("restart-timeout")
    assert after_second_restart == settled


@pytest.mark.ac("SPEC-083026-73c1/AC-2")
@pytest.mark.ac("SPEC-083026-73c1/AC-5")
async def test_cancel_survives_restart_without_fabricating_an_answer(tmp_path: Path) -> None:
    db = tmp_path / "hitl-cancel.db"
    store = SqliteDurableRunStore(db)
    original = _paused_record("restart-cancel")
    await store.create(original)

    cancelled = await store.cancel_hitl("restart-cancel", "ask", at=_BEFORE)

    _assert_settlement(
        cancelled,
        outcome="cancelled",
        run_status=RunStatus.CANCELLED,
        node_status=RunStatus.CANCELLED,
        decided_at=_BEFORE,
    )
    assert cancelled.attempts == original.attempts

    del store
    after_restart = await SqliteDurableRunStore(db).get("restart-cancel")
    assert after_restart == cancelled


@pytest.mark.ac("SPEC-083026-73c1/AC-2")
async def test_cancelling_one_human_frontier_member_cascades_open_siblings() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_paused_frontier_record("cancel-frontier"))

    cancelled = await store.cancel_hitl("cancel-frontier", "ask", at=_BEFORE)

    assert [node.status for node in cancelled.node_runs] == [
        RunStatus.CANCELLED,
        RunStatus.CANCELLED,
    ]
    assert "human input" in str(cancelled.node_runs[0].error)
    assert "Run terminalized as cancelled" in str(cancelled.node_runs[1].error)


async def test_timeout_is_refused_before_or_without_a_durable_deadline() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_paused_record("deadline-pending"))
    without_deadline = _with_pause_entry(
        _paused_record("deadline-absent"),
        {"kind": "hitl", "metadata": {"question": "Ship it?"}, "resume_at": None},
    )
    await store.create(without_deadline)

    with pytest.raises(HitlDeadlinePending, match="pending until"):
        await store.timeout_hitl("deadline-pending", "ask", at=_BEFORE)
    with pytest.raises(HitlDeadlinePending, match="has no deadline"):
        await store.timeout_hitl("deadline-absent", "ask", at=_AFTER)


async def test_settlement_refuses_missing_runs_and_nodes_outside_the_frontier() -> None:
    store = InMemoryDurableRunStore()
    with pytest.raises(KeyError, match="no such run"):
        await store.timeout_hitl("missing", "ask", at=_AFTER)
    with pytest.raises(KeyError, match="no such run"):
        await store.cancel_hitl("missing", "ask", at=_BEFORE)

    await store.create(_paused_record("wrong-frontier-node"))
    with pytest.raises(ValueError, match="waiting on frontier"):
        await store.cancel_hitl("wrong-frontier-node", "review", at=_BEFORE)


@pytest.mark.parametrize(
    ("raw_deadline", "message"),
    [
        (7, "not an ISO timestamp"),
        ("not-a-date", "is invalid"),
        ("2026-08-30T20:00:00", "has no timezone"),
    ],
)
def test_malformed_durable_deadlines_fail_closed(raw_deadline: object, message: str) -> None:
    record = _with_pause_entry(
        _paused_record("malformed-deadline"),
        {"kind": "hitl", "metadata": {}, "resume_at": raw_deadline},
    )

    with pytest.raises(HitlSettlementError, match=message):
        hitl_deadline(record, "ask")


def test_missing_pause_is_only_compatible_with_the_legacy_answer_path() -> None:
    record = _with_pause_entry(_paused_record("legacy-pause"), None)

    with pytest.raises(HitlSettlementError, match="no durable HITL pause"):
        hitl_deadline(record, "ask")
    assert hitl_deadline(record, "ask", require_pause=False) is None


def test_settlement_clock_requires_a_timezone() -> None:
    with pytest.raises(ValueError, match="must include a timezone"):
        settlement_time(datetime(2026, 8, 30, 20, 0))


@pytest.mark.ac("SPEC-083026-73c1/AC-3")
async def test_late_answer_is_refused_before_the_sweep_observes_expiry() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_paused_record("late-answer"))

    with pytest.raises(HitlDeadlineElapsed, match="deadline elapsed"):
        await store.submit_hitl_answer("late-answer", "ask", {"answer": "yes"}, at=_AFTER)

    still_paused = await store.get("late-answer")
    assert still_paused is not None
    assert still_paused.status is RunStatus.PAUSED
    assert still_paused.hitl_answers == {}

    [timed_out] = await expire_hitl_pauses(store, now=_AFTER)
    with pytest.raises(ValueError, match="not paused"):
        await store.submit_hitl_answer("late-answer", "ask", {"answer": "again"}, at=_AFTER)
    assert await store.get("late-answer") == timed_out


@pytest.mark.ac("SPEC-083026-73c1/AC-4")
async def test_concurrent_answer_and_cancel_persist_exactly_one_winner() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_paused_record("one-winner"))

    results = await asyncio.gather(
        store.submit_hitl_answer("one-winner", "ask", {"answer": "yes"}, at=_BEFORE),
        store.cancel_hitl("one-winner", "ask", at=_BEFORE),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    persisted = await store.get("one-winner")
    assert persisted is not None
    if persisted.status is RunStatus.QUEUED:
        assert persisted.hitl_answers["ask"]["answer"] == "yes"
        assert "hitl_settlements" not in persisted.graph_state.metadata
    else:
        assert persisted.status is RunStatus.CANCELLED
        assert persisted.hitl_answers == {}
        assert persisted.graph_state.metadata["hitl_settlements"]["ask"]["outcome"] == "cancelled"


@pytest.mark.ac("SPEC-083026-73c1/AC-4")
async def test_elapsed_deadline_wins_answer_timeout_cancel_race() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_paused_record("deadline-winner"))

    results = await asyncio.gather(
        store.submit_hitl_answer("deadline-winner", "ask", {"answer": "yes"}, at=_AFTER),
        store.cancel_hitl("deadline-winner", "ask", at=_AFTER),
        store.timeout_hitl("deadline-winner", "ask", at=_AFTER),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 2
    persisted = await store.get("deadline-winner")
    assert persisted is not None
    _assert_settlement(
        persisted,
        outcome="timed_out",
        run_status=RunStatus.TIMED_OUT,
        node_status=RunStatus.TIMED_OUT,
    )


@pytest.mark.ac("SPEC-083026-73c1/AC-4")
async def test_sqlite_instances_serialize_answer_cancel_race(tmp_path: Path) -> None:
    db = tmp_path / "hitl-race.db"
    answer_store = SqliteDurableRunStore(db)
    cancel_store = SqliteDurableRunStore(db)
    await answer_store.create(_paused_record("sqlite-one-winner"))

    results = await asyncio.gather(
        answer_store.submit_hitl_answer("sqlite-one-winner", "ask", {"answer": "yes"}, at=_BEFORE),
        cancel_store.cancel_hitl("sqlite-one-winner", "ask", at=_BEFORE),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    persisted = await SqliteDurableRunStore(db).get("sqlite-one-winner")
    assert persisted is not None
    assert persisted.status in {RunStatus.QUEUED, RunStatus.CANCELLED}


@pytest.mark.ac("SPEC-083026-73c1/AC-1")
@pytest.mark.ac("SPEC-083026-73c1/AC-5")
async def test_canonical_projection_mirrors_timeout_without_rewriting_attempt() -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-hitl-settlement")
    project = await projects.create(
        workspace_id="ws-hitl-settlement",
        parent_project_id=root.project_id,
        name="HITL",
    )
    run_store = InMemoryRunStore(project_store=projects)
    store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    graph = Graph(
        workspace_id="ws-hitl-settlement",
        project_id=project.project_id,
        name="canonical timeout",
        nodes=[Node(node_id="ask", node_type=_CanonicalAsk.kind)],
    )
    admitted = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)

    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=lambda node_id, current_graph: _CanonicalAsk(),
        run_id=admitted.run_id,
        run_store=run_store,
    )
    original_attempts = paused.attempts

    settled = await store.timeout_hitl(paused.run_id, "ask", at=_AFTER)

    _assert_settlement(
        settled,
        outcome="timed_out",
        run_status=RunStatus.TIMED_OUT,
        node_status=RunStatus.TIMED_OUT,
    )
    assert settled.attempts == original_attempts
    canonical_run = await run_store.get_run(paused.run_id)
    assert canonical_run is not None and canonical_run.status is RunStatus.TIMED_OUT
    [canonical_node_run] = await run_store.list_node_runs(paused.run_id)
    assert canonical_node_run.status is RunStatus.TIMED_OUT

    cancel_run = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    cancel_paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=lambda node_id, current_graph: _CanonicalAsk(),
        run_id=cancel_run.run_id,
        run_store=run_store,
    )
    cancel_settled = await store.cancel_hitl(cancel_paused.run_id, "ask", at=_BEFORE)
    assert cancel_settled.status is RunStatus.CANCELLED


@pytest.mark.ac("SPEC-083026-73c1/AC-6")
async def test_expiry_tick_is_bounded_and_ignores_unelapsed_pauses() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_paused_record("first"))
    await store.create(_paused_record("second"))

    assert await expire_hitl_pauses(store, now=_BEFORE) == []
    expired = await expire_hitl_pauses(store, now=_AFTER, limit=1)

    assert len(expired) == 1
    remaining = await store.list_by_status(RunStatus.PAUSED)
    assert len(remaining) == 1


async def test_expiry_tick_ignores_nonhuman_pauses_and_lost_races() -> None:
    assert await expire_hitl_pauses(InMemoryDurableRunStore(), now=_AFTER, limit=0) == []

    wait_store = InMemoryDurableRunStore()
    wait_record = _with_pause_entry(
        _paused_record("machine-wait"),
        {"kind": "wait", "metadata": {}, "resume_at": _DEADLINE.isoformat()},
    )
    await wait_store.create(wait_record)
    assert await expire_hitl_pauses(wait_store, now=_AFTER) == []

    losing_store = _LosingTimeoutStore()
    await losing_store.create(_paused_record("lost-expiry-race"))
    assert await expire_hitl_pauses(losing_store, now=_AFTER) == []
