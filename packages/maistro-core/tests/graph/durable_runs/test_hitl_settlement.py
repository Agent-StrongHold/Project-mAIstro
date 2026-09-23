"""Durable timeout/cancel semantics for human-paused graph work (#737)."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    HitlAuthenticatedSession,
    HitlAuthorization,
    HitlAuthorizationRequired,
    HitlDelegationEvidence,
    InMemoryGraphContinuationStore,
    resume_durable_graph,
    run_durable_graph,
)
from maistro.graph.durable_runs.hitl import (
    HitlDeadlineElapsed,
    HitlDeadlinePending,
    HitlSettlementError,
    earliest_hitl_deadline,
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
from maistro.graph.nodes import BaseNode, NodeContext, get_node, pause_until
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.lifecycle import transition_attempt, transition_node_run
from maistro.runs.model import Attempt, AttemptStatus, NodeRun, RunStatus

from .._canonical_helpers import durable_record

pytestmark = [pytest.mark.contract("behavioral")]

_DEADLINE = datetime(2026, 8, 30, 20, 0, tzinfo=UTC)
_BEFORE = _DEADLINE - timedelta(seconds=1)
_AFTER = _DEADLINE + timedelta(seconds=1)


async def _allow_test_membership(_principal: str, _workspace_id: str) -> bool:
    return True


def _test_authorization() -> HitlAuthorization:
    return HitlAuthorization.for_verified_session(
        HitlAuthenticatedSession.from_authenticated_boundary(
            "test-hitl-operator", _allow_test_membership
        ),
        {
            "test-workspace",
            "ws-hitl-reconcile",
            "ws-hitl-settlement",
            "ws-1097",
            "owned-workspace",
            "foreign-workspace",
        },
    )


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
        authorization: HitlAuthorization,
        at: datetime | None = None,
        workspace_id: str | None = None,
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


def _paused_record(
    run_id: str,
    *,
    workspace_id: str = "test-workspace",
) -> DurableRunRecord:
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
        workspace_id=workspace_id,
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
    expired = await expire_hitl_pauses(reopened, now=_AFTER, authorization=_test_authorization())

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
async def test_pre_index_sqlite_pause_is_backfilled_and_expires_after_restart(
    tmp_path: Path,
) -> None:
    db = tmp_path / "pre-index-hitl.db"
    original = _paused_record("pre-index-timeout")
    row = SqliteDurableRunStore._to_row(original)
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE durable_graph_runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                active_node_id TEXT,
                project_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resume_at TEXT,
                version INTEGER NOT NULL DEFAULT 0,
                record_json TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """INSERT INTO durable_graph_runs
               (run_id, status, active_node_id, project_id, created_at,
                resume_at, version, record_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["run_id"],
                row["status"],
                row["active_node_id"],
                row["project_id"],
                row["created_at"],
                row["resume_at"],
                row["version"],
                row["record_json"],
            ),
        )
        conn.commit()

    store = SqliteDurableRunStore(db)
    expired = await expire_hitl_pauses(
        store, now=_AFTER, limit=1, authorization=_test_authorization()
    )

    assert [record.run_id for record in expired] == ["pre-index-timeout"]
    assert expired[0].status is RunStatus.TIMED_OUT


async def test_cancel_survives_restart_without_fabricating_an_answer(tmp_path: Path) -> None:
    db = tmp_path / "hitl-cancel.db"
    store = SqliteDurableRunStore(db)
    original = _paused_record("restart-cancel")
    await store.create(original)

    cancelled = await store.cancel_hitl(
        "restart-cancel", "ask", at=_BEFORE, authorization=_test_authorization()
    )

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

    cancelled = await store.cancel_hitl(
        "cancel-frontier", "ask", at=_BEFORE, authorization=_test_authorization()
    )

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
        await store.timeout_hitl(
            "deadline-pending", "ask", at=_BEFORE, authorization=_test_authorization()
        )
    with pytest.raises(HitlDeadlinePending, match="has no deadline"):
        await store.timeout_hitl(
            "deadline-absent", "ask", at=_AFTER, authorization=_test_authorization()
        )


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_settlement_requires_object_authorization_before_target_lookup(
    backend: str, tmp_path: Path
) -> None:
    store = (
        InMemoryDurableRunStore()
        if backend == "memory"
        else SqliteDurableRunStore(tmp_path / "unscoped-hitl.db")
    )
    await store.create(_paused_record("unscoped-settlement"))

    with pytest.raises(HitlAuthorizationRequired, match="authorization is required"):
        await store.list_hitl_due(
            now=_AFTER,
            authorization=None,  # type: ignore[arg-type]
        )
    with pytest.raises(HitlAuthorizationRequired, match="authorization is required"):
        await store.cancel_hitl(
            "unscoped-settlement",
            "ask",
            at=_BEFORE,
            authorization=None,  # type: ignore[arg-type]
        )

    unchanged = await store.get("unscoped-settlement")
    assert unchanged is not None and unchanged.status is RunStatus.PAUSED


async def test_settlement_refuses_missing_runs_and_nodes_outside_the_frontier() -> None:
    store = InMemoryDurableRunStore()
    with pytest.raises(KeyError, match="no such run"):
        await store.timeout_hitl("missing", "ask", at=_AFTER, authorization=_test_authorization())
    with pytest.raises(KeyError, match="no such run"):
        await store.cancel_hitl("missing", "ask", at=_BEFORE, authorization=_test_authorization())

    await store.create(_paused_record("wrong-frontier-node"))
    with pytest.raises(ValueError, match="waiting on frontier"):
        await store.cancel_hitl(
            "wrong-frontier-node", "review", at=_BEFORE, authorization=_test_authorization()
        )


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


async def test_deadline_projection_skips_malformed_active_pause() -> None:
    record = _with_pause_entry(
        _paused_record("malformed-projection"),
        {"kind": "hitl", "metadata": {}, "resume_at": "2026-08-30T20:00:00"},
    )

    assert earliest_hitl_deadline(record) is None


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
        await store.submit_hitl_answer(
            "late-answer", "ask", {"answer": "yes"}, at=_AFTER, authorization=_test_authorization()
        )

    still_paused = await store.get("late-answer")
    assert still_paused is not None
    assert still_paused.status is RunStatus.PAUSED
    assert still_paused.hitl_answers == {}

    [timed_out] = await expire_hitl_pauses(store, now=_AFTER, authorization=_test_authorization())
    with pytest.raises(ValueError, match="not paused"):
        await store.submit_hitl_answer(
            "late-answer",
            "ask",
            {"answer": "again"},
            at=_AFTER,
            authorization=_test_authorization(),
        )
    assert await store.get("late-answer") == timed_out


@pytest.mark.ac("SPEC-083026-73c1/AC-4")
async def test_concurrent_answer_and_cancel_persist_exactly_one_winner() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_paused_record("one-winner"))

    results = await asyncio.gather(
        store.submit_hitl_answer(
            "one-winner", "ask", {"answer": "yes"}, at=_BEFORE, authorization=_test_authorization()
        ),
        store.cancel_hitl("one-winner", "ask", at=_BEFORE, authorization=_test_authorization()),
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
        store.submit_hitl_answer(
            "deadline-winner",
            "ask",
            {"answer": "yes"},
            at=_AFTER,
            authorization=_test_authorization(),
        ),
        store.cancel_hitl("deadline-winner", "ask", at=_AFTER, authorization=_test_authorization()),
        store.timeout_hitl(
            "deadline-winner", "ask", at=_AFTER, authorization=_test_authorization()
        ),
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
async def test_two_workspace_late_race_cannot_settle_foreign_pause() -> None:
    """A scoped caller wins only its own deadline race, never a foreign Run."""
    store = InMemoryDurableRunStore()
    await store.create(_paused_record("owned-race", workspace_id="owned-workspace"))
    await store.create(_paused_record("foreign-race", workspace_id="foreign-workspace"))
    authorization = HitlAuthorization.for_verified_session(
        HitlAuthenticatedSession.from_authenticated_boundary("member-user", _allow_test_membership),
        ["owned-workspace"],
    )

    results = await asyncio.gather(
        store.submit_hitl_answer(
            "owned-race",
            "ask",
            {"answer": "late"},
            at=_AFTER,
            authorization=authorization,
        ),
        store.timeout_hitl(
            "owned-race",
            "ask",
            at=_AFTER,
            authorization=authorization,
        ),
        store.submit_hitl_answer(
            "foreign-race",
            "ask",
            {"answer": "late"},
            at=_AFTER,
            authorization=authorization,
        ),
        store.cancel_hitl(
            "foreign-race",
            "ask",
            at=_AFTER,
            authorization=authorization,
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    owned = await store.get("owned-race")
    foreign = await store.get("foreign-race")
    assert owned is not None and owned.status is RunStatus.TIMED_OUT
    assert foreign is not None and foreign.status is RunStatus.PAUSED


async def _canonical_two_workspace_fixture() -> tuple[Any, Any, Any, Any]:
    """Two real `human.approve_draft` Runs, paused in two canonical Workspaces."""
    projects = InMemoryProjectScopeStore()
    run_store = InMemoryRunStore(project_store=projects)
    store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    paused: dict[str, Any] = {}
    for workspace_id in ("ws-1058-member", "ws-1058-foreign"):
        root = await projects.create_root(workspace_id)
        project = await projects.create(
            workspace_id=workspace_id,
            parent_project_id=root.project_id,
            name=f"two-workspace settlement {workspace_id}",
        )
        graph = Graph(
            workspace_id=workspace_id,
            project_id=project.project_id,
            name="approval",
            nodes=[
                Node(
                    node_id="ask",
                    node_type="human.approve_draft",
                    inputs={"draft": {"ticket": "PROJ-1"}, "timeout_seconds": 100},
                )
            ],
        )
        admitted = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
        paused[workspace_id] = await run_durable_graph(
            graph,
            store=store,
            node_resolver=lambda node_id, current_graph: get_node("human.approve_draft")(),
            run_id=admitted.run_id,
            run_store=run_store,
        )
    return store, run_store, paused["ws-1058-member"], paused["ws-1058-foreign"]


async def test_canonical_mutations_refuse_a_foreign_workspace_authorization() -> None:
    """Object authorization binds at the canonical spine, not only its copies.

    The in-memory and SQLite stores each carry their own membership
    predicate; the spine-backed `CanonicalDurableRunStore` must refuse the
    same foreign settlement through its `_mutate_hitl` boundary, and an
    expiry tick scoped to the member Workspace must never settle the foreign
    Run. Removing the `permits` predicate there must fail this test.
    """
    store, _run_store, member, foreign = await _canonical_two_workspace_fixture()
    authorization = HitlAuthorization.for_verified_session(
        HitlAuthenticatedSession.from_authenticated_boundary("member-user", _allow_test_membership),
        ["ws-1058-member"],
    )

    mutations = [
        lambda: store.submit_hitl_answer(
            foreign.run_id,
            "ask",
            {"answer": "late"},
            at=_AFTER,
            authorization=authorization,
        ),
        lambda: store.timeout_hitl(foreign.run_id, "ask", at=_AFTER, authorization=authorization),
        lambda: store.cancel_hitl(foreign.run_id, "ask", at=_AFTER, authorization=authorization),
    ]
    for mutate in mutations:
        with pytest.raises(KeyError, match="outside the authorized Workspace"):
            await mutate()

    unsettled = await store.get(foreign.run_id)
    assert unsettled is not None and unsettled.status is RunStatus.PAUSED

    deadline = hitl_deadline(foreign, "ask")
    assert deadline is not None
    expired = await expire_hitl_pauses(
        store, now=deadline + timedelta(seconds=1), authorization=authorization
    )
    assert [record.run_id for record in expired] == [member.run_id]

    still_paused = await store.get(foreign.run_id)
    assert still_paused is not None and still_paused.status is RunStatus.PAUSED
    timed_out = await store.get(member.run_id)
    assert timed_out is not None and timed_out.status is RunStatus.TIMED_OUT


async def test_inmemory_mutations_refuse_a_foreign_workspace_authorization() -> None:
    """The store-level predicate itself, not a deadline, refuses the mutation.

    Settled before the pause deadline so no `HitlDeadlineElapsed` can mask the
    refusal: only the Workspace membership predicate can produce this
    KeyError. Removing it from the in-memory store must fail this test.
    """
    store = InMemoryDurableRunStore()
    await store.create(_paused_record("foreign-direct", workspace_id="foreign-workspace"))
    authorization = HitlAuthorization.for_verified_session(
        HitlAuthenticatedSession.from_authenticated_boundary("member-user", _allow_test_membership),
        ["owned-workspace"],
    )

    mutations = [
        lambda: store.submit_hitl_answer(
            "foreign-direct",
            "ask",
            {"answer": "yes"},
            at=_BEFORE,
            authorization=authorization,
        ),
        lambda: store.timeout_hitl("foreign-direct", "ask", at=_AFTER, authorization=authorization),
        lambda: store.cancel_hitl("foreign-direct", "ask", at=_BEFORE, authorization=authorization),
    ]
    for mutate in mutations:
        with pytest.raises(KeyError, match="outside the authorized Workspace"):
            await mutate()

    record = await store.get("foreign-direct")
    assert record is not None and record.run.status is RunStatus.PAUSED


async def test_sqlite_instances_serialize_answer_cancel_race(tmp_path: Path) -> None:
    db = tmp_path / "hitl-race.db"
    answer_store = SqliteDurableRunStore(db)
    cancel_store = SqliteDurableRunStore(db)
    await answer_store.create(_paused_record("sqlite-one-winner"))

    results = await asyncio.gather(
        answer_store.submit_hitl_answer(
            "sqlite-one-winner",
            "ask",
            {"answer": "yes"},
            at=_BEFORE,
            authorization=_test_authorization(),
        ),
        cancel_store.cancel_hitl(
            "sqlite-one-winner", "ask", at=_BEFORE, authorization=_test_authorization()
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    persisted = await SqliteDurableRunStore(db).get("sqlite-one-winner")
    assert persisted is not None
    assert persisted.status in {RunStatus.QUEUED, RunStatus.CANCELLED}


async def test_sqlite_rechecks_membership_before_serialized_settlement(tmp_path: Path) -> None:
    """A revocation after target discovery must prevent the SQLite write."""
    store = SqliteDurableRunStore(tmp_path / "hitl-membership-race.db")
    await store.create(_paused_record("sqlite-membership-race"))
    checks: list[tuple[str, str]] = []

    async def membership(principal: str, workspace_id: str) -> bool:
        checks.append((principal, workspace_id))
        return len(checks) == 1

    authorization = HitlAuthorization.for_verified_session(
        HitlAuthenticatedSession.from_authenticated_boundary("member-user", membership),
        ["test-workspace"],
    )
    with pytest.raises(KeyError, match="outside the authorized Workspace"):
        await store.cancel_hitl(
            "sqlite-membership-race",
            "ask",
            at=_BEFORE,
            authorization=authorization,
        )

    persisted = await store.get("sqlite-membership-race")
    assert len(checks) == 2
    assert persisted is not None and persisted.status is RunStatus.PAUSED


@pytest.mark.ac("SPEC-083026-73c1/AC-1")
@pytest.mark.ac("SPEC-083026-73c1/AC-5")
async def test_reconcile_repairs_crash_after_terminal_continuation_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash between continuation and spine writes is restart-repairable."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-hitl-reconcile")
    project = await projects.create(
        workspace_id="ws-hitl-reconcile",
        parent_project_id=root.project_id,
        name="HITL",
    )
    run_store = InMemoryRunStore(project_store=projects)
    continuations = InMemoryGraphContinuationStore()
    store = CanonicalDurableRunStore(run_store, continuations)
    graph = Graph(
        workspace_id="ws-hitl-reconcile",
        project_id=project.project_id,
        name="crash after timeout evidence",
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
    original_transition_run = run_store.transition_run
    crash = True

    async def crash_before_run_mirror(run_id: str, target: RunStatus, **kwargs: Any) -> Any:
        nonlocal crash
        if crash and target is RunStatus.TIMED_OUT:
            crash = False
            raise RuntimeError("injected crash after HITL continuation write")
        return await original_transition_run(run_id, target, **kwargs)

    monkeypatch.setattr(run_store, "transition_run", crash_before_run_mirror)
    with pytest.raises(RuntimeError, match="injected crash"):
        await store.timeout_hitl(
            paused.run_id, "ask", at=_AFTER, authorization=_test_authorization()
        )

    interrupted = await run_store.get_run(paused.run_id)
    assert interrupted is not None and interrupted.status is RunStatus.PAUSED
    [interrupted_node] = await run_store.list_node_runs(paused.run_id)
    assert interrupted_node.status is RunStatus.TIMED_OUT

    # A newly opened canonical facade sees the durable terminal continuation
    # and repairs the remaining spine projection without another Attempt.
    reopened = CanonicalDurableRunStore(run_store, continuations)
    assert await reopened.reconcile_persistence() == 1
    repaired = await reopened.get(paused.run_id)
    assert repaired is not None and repaired.status is RunStatus.TIMED_OUT
    assert repaired.node_runs[0].status is RunStatus.TIMED_OUT
    assert repaired.attempts == original_attempts
    # The repair stamps the recorded settlement, not the moment it ran: the
    # durable evidence says when the deadline elapsed, and canonical latency
    # and audit read `finished_at`.
    assert repaired.run.finished_at == _AFTER
    assert repaired.node_runs[0].finished_at == _AFTER
    assert await reopened.reconcile_persistence() == 0


@pytest.mark.ac("SPEC-083026-73c1/AC-1")
async def test_reconcile_cancelled_evidence_without_pause_detail() -> None:
    """A cancellation remains repairable when legacy evidence lacks pause detail."""
    run_store, continuations, project_id = await _canonical_spine()
    store = CanonicalDurableRunStore(run_store, continuations)
    paused = await _canonical_pause(store, run_store, project_id)
    continuation = await continuations.get(paused.run_id)
    assert continuation is not None
    [node_run] = paused.node_runs
    metadata = {
        **continuation.graph_state.metadata,
        "hitl_settlements": {
            "ask": {
                "outcome": "cancelled",
                "node_run_id": node_run.node_run_id,
                "decided_at": _BEFORE.isoformat(),
            }
        },
    }
    interrupted = continuation.model_copy(
        update={
            "status": RunStatus.CANCELLED,
            "graph_state": continuation.graph_state.model_copy(update={"metadata": metadata}),
            "version": continuation.version + 1,
        }
    )
    await continuations.update(interrupted)

    assert await store.reconcile_persistence() == 1
    repaired = await store.get(paused.run_id)
    assert repaired is not None and repaired.status is RunStatus.CANCELLED
    assert repaired.node_runs[0].status is RunStatus.CANCELLED
    assert "was cancelled" in str(repaired.node_runs[0].error)


async def _canonical_pause(
    store: CanonicalDurableRunStore, run_store: InMemoryRunStore, project_id: str
) -> DurableRunRecord:
    graph = Graph(
        workspace_id="ws-hitl-reconcile",
        project_id=project_id,
        name="human pause",
        nodes=[Node(node_id="ask", node_type=_CanonicalAsk.kind)],
    )
    admitted = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    return await run_durable_graph(
        graph,
        store=store,
        node_resolver=lambda node_id, current_graph: _CanonicalAsk(),
        run_id=admitted.run_id,
        run_store=run_store,
    )


async def _canonical_spine() -> tuple[InMemoryRunStore, InMemoryGraphContinuationStore, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-hitl-reconcile")
    project = await projects.create(
        workspace_id="ws-hitl-reconcile", parent_project_id=root.project_id, name="HITL"
    )
    return (
        InMemoryRunStore(project_store=projects),
        InMemoryGraphContinuationStore(),
        project.project_id,
    )


async def _crash_after_continuation_timeout(
    store: CanonicalDurableRunStore,
    run_store: InMemoryRunStore,
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist the terminal continuation, then die before the Run mirror."""
    original_transition_run = run_store.transition_run
    crash = True

    async def crash_before_run_mirror(target_run_id: str, target: RunStatus, **kwargs: Any) -> Any:
        nonlocal crash
        if crash and target is RunStatus.TIMED_OUT and target_run_id == run_id:
            crash = False
            raise RuntimeError("injected crash after HITL continuation write")
        return await original_transition_run(target_run_id, target, **kwargs)

    monkeypatch.setattr(run_store, "transition_run", crash_before_run_mirror)
    with pytest.raises(RuntimeError, match="injected crash"):
        await store.timeout_hitl(run_id, "ask", at=_AFTER, authorization=_test_authorization())
    monkeypatch.setattr(run_store, "transition_run", original_transition_run)
    interrupted = await run_store.get_run(run_id)
    assert interrupted is not None and interrupted.status is RunStatus.PAUSED


async def test_reconcile_reaches_settlement_residue_behind_a_full_terminal_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One consistent TIMED_OUT row is enough to fill a budget of one.

    Scanning the continuation buckets in enum order re-read that consistent
    prefix on every tick and never reached the residue behind it. Settlement
    residue is a PAUSED canonical Run with a terminal continuation, so it is
    found from the canonical side, whose PAUSED bucket does not accumulate.
    """
    run_store, continuations, project_id = await _canonical_spine()
    store = CanonicalDurableRunStore(run_store, continuations)
    settled = await _canonical_pause(store, run_store, project_id)
    await store.timeout_hitl(settled.run_id, "ask", at=_AFTER, authorization=_test_authorization())
    residue = await _canonical_pause(store, run_store, project_id)
    await _crash_after_continuation_timeout(store, run_store, residue.run_id, monkeypatch)

    reopened = CanonicalDurableRunStore(run_store, continuations)
    assert await reopened.reconcile_persistence(limit=1) == 1

    repaired = await reopened.get(residue.run_id)
    assert repaired is not None and repaired.status is RunStatus.TIMED_OUT
    assert repaired.run.finished_at == _AFTER
    assert await reopened.reconcile_persistence(limit=1) == 0


async def test_concurrent_reconcile_ticks_settle_the_same_residue_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tick that mirrors second finds the Run already settled and stops.

    Both ticks read the canonical Run PAUSED; the loser's terminal hop is then
    refused by the lifecycle table. That refusal is the same repair already
    done, not a failure of this tick.
    """
    run_store, continuations, project_id = await _canonical_spine()
    store = CanonicalDurableRunStore(run_store, continuations)
    residue = await _canonical_pause(store, run_store, project_id)
    await _crash_after_continuation_timeout(store, run_store, residue.run_id, monkeypatch)

    original_transition_run = run_store.transition_run
    raced = False

    async def other_tick_lands_first(run_id: str, target: RunStatus, **kwargs: Any) -> Any:
        nonlocal raced
        if target is RunStatus.TIMED_OUT and not raced:
            raced = True
            await original_transition_run(run_id, target, **kwargs)
        return await original_transition_run(run_id, target, **kwargs)

    monkeypatch.setattr(run_store, "transition_run", other_tick_lands_first)
    reopened = CanonicalDurableRunStore(run_store, continuations)

    assert await reopened.reconcile_persistence() == 0
    assert raced is True
    repaired = await reopened.get(residue.run_id)
    assert repaired is not None and repaired.status is RunStatus.TIMED_OUT
    assert repaired.run.finished_at == _AFTER


async def test_expiry_repairs_a_pause_whose_run_mirror_never_landed() -> None:
    """A PAUSED continuation over a RUNNING canonical Run heads the deadline
    index forever; the tick repairs the projection and settles it."""
    run_store, continuations, project_id = await _canonical_spine()
    store = CanonicalDurableRunStore(run_store, continuations)
    valid = await _canonical_pause(store, run_store, project_id)
    # The crash shape: the continuation parked PAUSED with its deadline, and
    # the process died before the canonical Run was mirrored out of RUNNING.
    original_transition_run = run_store.transition_run
    crash = True

    async def crash_before_pause_mirror(run_id: str, target: RunStatus, **kwargs: Any) -> Any:
        nonlocal crash
        if crash and target is RunStatus.PAUSED:
            crash = False
            raise RuntimeError("injected crash before the pause mirror")
        return await original_transition_run(run_id, target, **kwargs)

    run_store.transition_run = crash_before_pause_mirror  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="injected crash"):
        await _canonical_pause(store, run_store, project_id)
    run_store.transition_run = original_transition_run  # type: ignore[method-assign]
    (stale_id,) = [
        run_id
        for run_id in await continuations.list_run_ids_by_status(RunStatus.PAUSED)
        if run_id != valid.run_id
    ]
    stale_run = await run_store.get_run(stale_id)
    assert stale_run is not None and stale_run.status is RunStatus.RUNNING

    first = await expire_hitl_pauses(
        store, now=_AFTER, limit=1, authorization=_test_authorization()
    )
    second = await expire_hitl_pauses(
        store, now=_AFTER, limit=1, authorization=_test_authorization()
    )

    assert {record.run_id for record in first + second} == {stale_id, valid.run_id}
    for run_id in (stale_id, valid.run_id):
        settled = await run_store.get_run(run_id)
        assert settled is not None and settled.status is RunStatus.TIMED_OUT
    assert (
        await expire_hitl_pauses(store, now=_AFTER, limit=1, authorization=_test_authorization())
        == []
    )


async def test_expiry_pages_past_a_projection_that_cannot_be_repaired() -> None:
    """A stale candidate the reconciler cannot fix must not hide the rest."""
    run_store, continuations, project_id = await _canonical_spine()
    store = CanonicalDurableRunStore(run_store, continuations)
    stale = await _canonical_pause(store, run_store, project_id)
    valid = await _canonical_pause(store, run_store, project_id)
    # Cancelled on the canonical side while the continuation still says PAUSED.
    await run_store.transition_run(stale.run_id, RunStatus.CANCELLED)

    settled = await expire_hitl_pauses(
        store, now=_AFTER, limit=1, authorization=_test_authorization()
    )

    assert [record.run_id for record in settled] == [valid.run_id]
    cancelled = await run_store.get_run(stale.run_id)
    assert cancelled is not None and cancelled.status is RunStatus.CANCELLED


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

    settled = await store.timeout_hitl(
        paused.run_id, "ask", at=_AFTER, authorization=_test_authorization()
    )

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
    cancel_settled = await store.cancel_hitl(
        cancel_paused.run_id, "ask", at=_BEFORE, authorization=_test_authorization()
    )
    assert cancel_settled.status is RunStatus.CANCELLED


@pytest.mark.ac("SPEC-083026-73c1/AC-6")
async def test_expiry_tick_is_bounded_and_ignores_unelapsed_pauses() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_paused_record("first"))
    await store.create(_paused_record("second"))

    assert await expire_hitl_pauses(store, now=_BEFORE, authorization=_test_authorization()) == []
    expired = await expire_hitl_pauses(
        store, now=_AFTER, limit=1, authorization=_test_authorization()
    )

    assert len(expired) == 1
    remaining = await store.list_by_status(RunStatus.PAUSED)
    assert len(remaining) == 1


async def test_scoped_expiry_requires_effective_principal_and_keeps_foreign_run_paused() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_paused_record("owned-expiry", workspace_id="owned-workspace"))
    await store.create(_paused_record("foreign-expiry", workspace_id="foreign-workspace"))

    with pytest.raises(KeyError, match="outside the requested Workspace"):
        await store.cancel_hitl(
            "owned-expiry",
            "ask",
            at=_BEFORE,
            workspace_id="foreign-workspace",
            authorization=_test_authorization(),
        )

    authorization = HitlAuthorization.for_verified_session(
        HitlAuthenticatedSession.from_authenticated_boundary("member-user", _allow_test_membership),
        ["owned-workspace"],
    )
    expired = await expire_hitl_pauses(store, now=_AFTER, authorization=authorization)

    assert [record.run_id for record in expired] == ["owned-expiry"]
    foreign = await store.get("foreign-expiry")
    assert foreign is not None and foreign.status is RunStatus.PAUSED


@pytest.mark.parametrize(
    ("factory", "expected"),
    [
        (
            lambda: HitlAuthorization.for_verified_session(
                HitlAuthenticatedSession.from_authenticated_boundary("", _allow_test_membership),
                frozenset(),
            ),
            "effective principal",
        ),
    ],
)
def test_scoped_hitl_expiry_rejects_missing_principal(factory, expected):
    with pytest.raises(ValueError, match=expected):
        factory()


def test_authenticated_hitl_requires_typed_session_evidence() -> None:
    with pytest.raises(TypeError):
        HitlAuthorization.for_verified_session(  # type: ignore[arg-type]
            "service",
            ["owned-workspace"],
        )
    with pytest.raises(TypeError, match="authenticated boundary"):
        HitlAuthenticatedSession("service", _allow_test_membership)
    with pytest.raises(TypeError, match="evidence factory"):
        HitlAuthorization("service", frozenset({"owned-workspace"}), _allow_test_membership)


def test_delegated_hitl_requires_typed_evidence() -> None:
    with pytest.raises(TypeError, match="typed evidence"):
        HitlAuthorization.for_delegated_service(
            "service",
            ["owned-workspace"],
            delegation_evidence="opaque text",  # type: ignore[arg-type]
            evidence_validator=lambda _evidence: _allow_test_membership(
                "service", "owned-workspace"
            ),
            evidence_consumer=_consume_nothing,
            membership_check=_allow_test_membership,
        )


async def _consume_nothing(_evidence: HitlDelegationEvidence) -> None:
    return None


async def test_delegated_hitl_validates_and_consumes_bound_evidence() -> None:
    store = InMemoryDurableRunStore()
    await store.create(_paused_record("delegated-evidence", workspace_id="owned-workspace"))
    evidence = HitlDelegationEvidence(
        issuer="did:key:issuer",
        subject="service",
        workspace_ids=frozenset({"owned-workspace"}),
        actions=frozenset({"hitl.settle"}),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        token_id="hitl-token-1",
    )
    validations: list[str] = []
    consumed: list[str] = []

    async def validate(token: HitlDelegationEvidence) -> bool:
        validations.append(token.token_id)
        return token.token_id == "hitl-token-1"

    async def consume(token: HitlDelegationEvidence) -> None:
        consumed.append(token.token_id)

    authorization = HitlAuthorization.for_delegated_service(
        "service",
        ["owned-workspace"],
        delegation_evidence=evidence,
        evidence_validator=validate,
        evidence_consumer=consume,
        membership_check=_allow_test_membership,
    )
    settled = await store.cancel_hitl(
        "delegated-evidence",
        "ask",
        at=_BEFORE,
        authorization=authorization,
    )

    assert settled.status is RunStatus.CANCELLED
    assert validations == ["hitl-token-1"]
    assert consumed == ["hitl-token-1"]


async def test_delegated_expiry_does_not_consume_evidence_during_discovery() -> None:
    """Due-list visibility must leave one-use authority for timeout settlement."""
    store = InMemoryDurableRunStore()
    await store.create(_paused_record("delegated-expiry", workspace_id="owned-workspace"))
    evidence = HitlDelegationEvidence(
        issuer="did:key:issuer",
        subject="service",
        workspace_ids=frozenset({"owned-workspace"}),
        actions=frozenset({"hitl.settle"}),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        token_id="hitl-expiry-token",
    )
    validations: list[str] = []
    consumed: list[str] = []

    async def validate(token: HitlDelegationEvidence) -> bool:
        validations.append(token.token_id)
        return True

    async def consume(token: HitlDelegationEvidence) -> None:
        consumed.append(token.token_id)

    authorization = HitlAuthorization.for_delegated_service(
        "service",
        ["owned-workspace"],
        delegation_evidence=evidence,
        evidence_validator=validate,
        evidence_consumer=consume,
        membership_check=_allow_test_membership,
    )

    expired = await expire_hitl_pauses(store, now=_AFTER, authorization=authorization)

    assert [record.run_id for record in expired] == ["delegated-expiry"]
    assert (await store.get("delegated-expiry")).status is RunStatus.TIMED_OUT
    assert validations == ["hitl-expiry-token", "hitl-expiry-token"]
    assert consumed == ["hitl-expiry-token"]


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_expiry_deadline_query_skips_an_ineligible_paused_prefix(
    backend: str, tmp_path: Path
) -> None:
    if backend == "memory":
        store = InMemoryDurableRunStore()
    else:
        store = SqliteDurableRunStore(tmp_path / "hitl-fairness.db")

    # These records are older in the operator's mental ordering, but their
    # durable pause entries are not HITL. They must not consume the settlement
    # limit or become a repeatedly reread prefix.
    for index in range(3):
        nonhuman = _with_pause_entry(
            _paused_record(f"nonhuman-{index}"),
            {"kind": "wait", "metadata": {}, "resume_at": _DEADLINE.isoformat()},
        ).model_copy(update={"resume_at": None})
        await store.create(nonhuman)
    future = _with_pause_entry(
        _paused_record("future-hitl"),
        {"kind": "hitl", "metadata": {}, "resume_at": (_AFTER + timedelta(days=1)).isoformat()},
    ).model_copy(update={"resume_at": None})
    await store.create(future)

    expired = _paused_record("expired-hitl").model_copy(update={"resume_at": None})
    await store.create(expired)

    settled = await expire_hitl_pauses(
        store, now=_AFTER, limit=1, authorization=_test_authorization()
    )

    assert [record.run_id for record in settled] == ["expired-hitl"]
    assert await store.get("expired-hitl") is not None
    assert (await store.get("expired-hitl")).status is RunStatus.TIMED_OUT


async def test_expiry_tick_ignores_nonhuman_pauses_and_lost_races() -> None:
    assert (
        await expire_hitl_pauses(
            InMemoryDurableRunStore(), now=_AFTER, limit=0, authorization=_test_authorization()
        )
        == []
    )

    wait_store = InMemoryDurableRunStore()
    wait_record = _with_pause_entry(
        _paused_record("machine-wait"),
        {"kind": "wait", "metadata": {}, "resume_at": _DEADLINE.isoformat()},
    )
    await wait_store.create(wait_record)
    assert (
        await expire_hitl_pauses(wait_store, now=_AFTER, authorization=_test_authorization()) == []
    )

    losing_store = _LosingTimeoutStore()
    await losing_store.create(_paused_record("lost-expiry-race"))
    assert (
        await expire_hitl_pauses(losing_store, now=_AFTER, authorization=_test_authorization())
        == []
    )


async def test_expiry_scan_pages_past_a_long_ineligible_prefix() -> None:
    """#1056: a run of ineligible PAUSED Runs longer than both the caller's
    ``limit`` and the scan's own page size must not hide an expired HITL pause
    ordered behind them. Before the fix, ``list_by_status(..., limit=N)`` was
    applied directly at the store, so a small ``limit`` alone could never see
    past an ineligible prefix that long -- the scan had to actually advance a
    cursor across more than one page to find it."""
    store = InMemoryDurableRunStore()
    base = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

    def _created_at(record: DurableRunRecord, moment: datetime) -> DurableRunRecord:
        return record.model_copy(
            update={"run": record.run.model_copy(update={"created_at": moment})}
        )

    # More than the scan's own default page size (100), so finding the
    # expired pause requires walking multiple pages, not just decoupling
    # `limit` from a single larger fetch.
    for i in range(120):
        machine_wait = _with_pause_entry(
            _paused_record(f"machine-{i}"),
            {"kind": "wait", "metadata": {}, "resume_at": _DEADLINE.isoformat()},
        )
        await store.create(_created_at(machine_wait, base + timedelta(seconds=i)))

    expired = _created_at(
        _paused_record("expired-behind-the-prefix"), base + timedelta(seconds=500)
    )
    await store.create(expired)

    settled = await expire_hitl_pauses(
        store, now=_AFTER, limit=5, authorization=_test_authorization()
    )

    assert [record.run_id for record in settled] == ["expired-behind-the-prefix"]


# --- #1097: a malformed answer must not rewrite the durable deadline -------


async def _canonical_hitl_fixture() -> tuple[Any, Any, Any]:
    """A real `human.approve_draft` Run, admitted and paused end to end.

    Through the canonical spine rather than a hand-built record, so this
    proves what `answer_record`/`get_node("human.approve_draft")` actually do
    together, not what this suite believes they do.
    """
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-1097")
    project = await projects.create(
        workspace_id="ws-1097",
        parent_project_id=root.project_id,
        name="deadline preservation",
    )
    run_store = InMemoryRunStore(project_store=projects)
    store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    graph = Graph(
        workspace_id="ws-1097",
        project_id=project.project_id,
        name="approval",
        nodes=[
            Node(
                node_id="ask",
                node_type="human.approve_draft",
                inputs={"draft": {"ticket": "PROJ-1"}, "timeout_seconds": 100},
            )
        ],
    )
    admitted = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=lambda node_id, current_graph: get_node("human.approve_draft")(),
        run_id=admitted.run_id,
        run_store=run_store,
    )
    return store, run_store, paused


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
async def test_a_malformed_answer_re_pauses_without_moving_the_deadline() -> None:
    store, _run_store, paused = await _canonical_hitl_fixture()
    original_deadline = hitl_deadline(paused, "ask")
    assert original_deadline is not None

    malformed_at = original_deadline - timedelta(seconds=50)
    await store.submit_hitl_answer(
        paused.run_id,
        "ask",
        {"reviewer_note": "still deciding"},
        at=malformed_at,
        authorization=_test_authorization(),
    )
    resumed = await store.get(paused.run_id)
    assert resumed is not None
    assert resumed.status is RunStatus.PAUSED
    assert hitl_deadline(resumed, "ask") == original_deadline, (
        "a malformed answer must re-pause on the *original* admitted "
        "deadline, not a freshly computed now + timeout_seconds"
    )


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
async def test_repeated_malformed_answers_at_t_minus_1s_cannot_extend_the_deadline() -> None:
    """The issue's own repro shape: bad answers arriving right up against the
    deadline must not push it back, and the Run still expires exactly when
    originally admitted."""
    store, run_store, paused = await _canonical_hitl_fixture()
    original_deadline = hitl_deadline(paused, "ask")
    assert original_deadline is not None

    current = paused
    for offset in (timedelta(seconds=90), timedelta(seconds=30), timedelta(seconds=1)):
        malformed_at = original_deadline - offset
        await store.submit_hitl_answer(
            current.run_id,
            "ask",
            {"reviewer_note": "not yet"},
            at=malformed_at,
            authorization=_test_authorization(),
        )
        current = await store.get(current.run_id)
        assert current is not None
        assert current.status is RunStatus.PAUSED
        assert hitl_deadline(current, "ask") == original_deadline

    expired = await expire_hitl_pauses(
        store, now=original_deadline - timedelta(seconds=1), authorization=_test_authorization()
    )
    assert expired == []

    expired = await expire_hitl_pauses(
        store, now=original_deadline + timedelta(seconds=1), authorization=_test_authorization()
    )
    assert [record.run_id for record in expired] == [paused.run_id]
    settled = await run_store.get_run(paused.run_id)
    assert settled is not None and settled.status is RunStatus.TIMED_OUT


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
async def test_a_valid_answer_before_the_preserved_deadline_still_settles() -> None:
    """A malformed answer followed by a real verdict still resumes normally --
    preserving the deadline must not make a good answer un-actionable."""
    store, run_store, paused = await _canonical_hitl_fixture()
    original_deadline = hitl_deadline(paused, "ask")
    assert original_deadline is not None

    def _resolver(node_id: str, current_graph: Any) -> Any:
        return get_node("human.approve_draft")()

    await store.submit_hitl_answer(
        paused.run_id,
        "ask",
        {"reviewer_note": "later"},
        at=original_deadline - timedelta(seconds=50),
        authorization=_test_authorization(),
    )
    still_paused = await store.get(paused.run_id)
    assert still_paused is not None
    assert still_paused.status is RunStatus.PAUSED
    assert hitl_deadline(still_paused, "ask") == original_deadline

    await store.submit_hitl_answer(
        paused.run_id,
        "ask",
        {"verdict": "approved"},
        at=original_deadline - timedelta(seconds=10),
        authorization=_test_authorization(),
    )
    settled = await resume_durable_graph(
        paused.run_id, store=store, node_resolver=_resolver, run_store=run_store
    )
    assert settled.status is RunStatus.COMPLETED


class _OverEagerIndexStore(InMemoryDurableRunStore):
    """A store whose deadline index offers a Run the durable pause disagrees with.

    The index is a projection written beside the record, so it can be stale or
    simply wrong after a crash between the two writes. Everything it returns is
    therefore re-derived from the pause itself before anything is settled.
    """

    async def list_hitl_due(
        self,
        *,
        authorization: HitlAuthorization,
        now: datetime,
        limit: int = 100,
    ) -> list[DurableRunRecord]:
        del authorization, now, limit
        return list(self._rows.values())


@pytest.mark.asyncio
async def test_an_index_hit_whose_pause_is_not_elapsed_is_not_timed_out() -> None:
    """`list_hitl_due` proposes; the durable pause disposes.

    A deadline index that says due while the pause says otherwise must not
    settle the Run. Timing out on the projection alone would let a stale index
    row cancel live human work.
    """
    store = _OverEagerIndexStore()
    await store.create(_paused_record("hitl-index-not-elapsed"))

    assert await expire_hitl_pauses(store, now=_BEFORE, authorization=_test_authorization()) == []

    record = await store.get("hitl-index-not-elapsed")
    assert record is not None
    assert record.run.status is RunStatus.PAUSED


@pytest.mark.asyncio
async def test_an_index_hit_with_no_readable_pause_is_skipped_not_settled() -> None:
    """A frontier node carrying no usable pause entry is passed over.

    `hitl_pause` refuses the node rather than guessing, and the scan moves to
    the next active node instead of settling a Run on a pause it cannot read.
    """
    store = _OverEagerIndexStore()
    record = _paused_record("hitl-index-unreadable")
    metadata = dict(record.graph_state.metadata)
    metadata["pauses"] = {"ask": {"kind": "timer", "resume_at": _DEADLINE.isoformat()}}
    metadata.pop("pause", None)
    await store.create(
        record.model_copy(
            update={"graph_state": record.graph_state.model_copy(update={"metadata": metadata})}
        )
    )

    assert await expire_hitl_pauses(store, now=_AFTER, authorization=_test_authorization()) == []

    stored = await store.get("hitl-index-unreadable")
    assert stored is not None
    assert stored.run.status is RunStatus.PAUSED
