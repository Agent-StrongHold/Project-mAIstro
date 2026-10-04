"""Load and fork durable Graph state at an event sequence (#1612).

The timeline is the full-content half of the traversal history: commits and
checkpoints verify states by hash, the timeline persists the states themselves
so a sequence position can be loaded and forked. These tests pin the contract
end to end -- inclusive positions, fail-closed range/integrity checks,
read-only determinism, the park -> load -> fork proof across store reopens,
and the fence a stale writer cannot rewind.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import aiosqlite
import pytest
from pydantic import BaseModel

from maistro.graph import Edge, Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
    SequenceOutOfRangeError,
    SqliteGraphContinuationStore,
    StateHistoryIntegrityError,
    UnknownGraphRunError,
    resume_durable_graph,
    run_durable_graph,
)
from maistro.graph.durable_runs.continuation import (
    GraphContinuation,
    GraphStateEpoch,
)
from maistro.graph.durable_runs.time_travel import (
    DURABLE_GRAPH_FORK_PROVENANCE,
    state_epoch_appended,
)
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import BaseNode, NodeContext, pause_until
from maistro.graph.traversal_commit import graph_state_hash
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.concurrency import RunConcurrencyLimits
from maistro.runs.model import EvalMethod, RunEvalScore, RunStatus
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

pytestmark = [pytest.mark.contract("behavioral")]

_WORKSPACE = "ws-time-travel"


async def hitl_authorization_for_workspace() -> Any:
    from maistro.graph.durable_runs import HitlAuthorization

    async def _allow(_principal: str, _workspace_id: str) -> bool:
        return True

    return HitlAuthorization(
        effective_principal="test-time-travel-operator",
        workspace_ids=frozenset({_WORKSPACE}),
        membership_check=_allow,
    )


class _StepIn(BaseModel):
    pass


class _StepOut(BaseModel):
    text: str = "done"


class _Counting(BaseNode[_StepIn, _StepOut]):
    """A plain step that records every physical execution per node id."""

    kind: ClassVar[str] = "test.time_travel.counting"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _StepIn
    output_schema: ClassVar[type[BaseModel]] = _StepOut
    executions: ClassVar[Counter[str]] = Counter()

    async def _execute(self, inputs: _StepIn, ctx: NodeContext) -> _StepOut:
        type(self).executions[ctx.node_id] += 1
        return _StepOut()


class _Ask(BaseNode[_StepIn, _StepOut]):
    kind: ClassVar[str] = "test.time_travel.ask"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = _StepIn
    output_schema: ClassVar[type[BaseModel]] = _StepOut

    async def _execute(self, inputs: _StepIn, ctx: NodeContext) -> _StepOut:
        answered = ((ctx.metadata or {}).get("hitl_answers") or {}).get(ctx.node_id)
        if answered is not None:
            return _StepOut(text=str(answered.get("answer") or ""))
        pause_until("awaiting_human_answer", metadata={"question": "Continue?"})
        return _StepOut(text="UNREACHABLE")


def _resolver(by_node_id: dict[str, BaseNode[Any, Any]]) -> Any:
    return lambda node_id, graph: by_node_id[node_id]


def _counting_chain(workspace_id: str, project_id: str, kinds: list[str]) -> Graph:
    """A linear a -> b -> c graph with one node type per position."""
    names = ("a", "b", "c", "d")
    nodes = [Node(node_id=names[i], node_type=kinds[i]) for i in range(len(kinds))]
    edges = [Edge(from_node=names[i], to_node=names[i + 1]) for i in range(len(kinds) - 1)]
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="time-travel chain",
        nodes=nodes,
        edges=edges,
    )


async def _spine() -> tuple[InMemoryRunStore, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(_WORKSPACE)
    project = await projects.create(
        workspace_id=_WORKSPACE, parent_project_id=root.project_id, name="Time travel"
    )
    return InMemoryRunStore(project_store=projects), _WORKSPACE, project.project_id


async def _admit(run_store: InMemoryRunStore, graph: Graph) -> str:
    run = await run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    return run.run_id


async def _completed_chain(
    workspace_id: str,
    project_id: str,
    *,
    run_store: InMemoryRunStore,
    store: CanonicalDurableRunStore,
) -> str:
    graph = _counting_chain(workspace_id, project_id, [_Counting.kind] * 3)
    record = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolver({name: _Counting() for name in ("a", "b", "c")}),
        run_id=await _admit(run_store, graph),
        run_store=run_store,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert record.status is RunStatus.COMPLETED
    return record.run_id


def _fork_fact(run: Any) -> dict[str, Any]:
    fact = run.provenance[DURABLE_GRAPH_FORK_PROVENANCE]
    assert isinstance(fact, dict)
    return fact


async def _sequence_with_frontier(
    store: CanonicalDurableRunStore, run_id: str, total: int, node_id: str
) -> int:
    """The first event position whose frontier is exactly ``node_id``."""
    for sequence in range(1, total + 1):
        load = await store.load_state(run_id, sequence)
        if load.graph_state.active_node_ids == (node_id,):
            return sequence
    raise AssertionError(f"no recorded position of run {run_id!r} has frontier {node_id!r}")


async def test_launch_state_is_epoch_one_and_each_advance_appends_one() -> None:
    run_store, workspace_id, project_id = await _spine()
    continuations = InMemoryGraphContinuationStore()
    store = CanonicalDurableRunStore(run_store, continuations)
    run_id = await _completed_chain(workspace_id, project_id, run_store=run_store, store=store)

    continuation = await continuations.get(run_id)
    assert continuation is not None
    timeline = continuation.state_timeline
    assert [epoch.sequence for epoch in timeline] == list(range(1, len(timeline) + 1))
    assert len(timeline) >= 3, "launch, interior states and the tip are distinct"
    first = timeline[0]
    assert first.state.active_node_ids == ("a",)
    assert first.state.cycle == 0
    assert first.state.edge_decisions == ()
    assert first.commit_sequence is None and first.checkpoint_sequence is None

    # Every commit's resulting state is a recorded position, carrying its link.
    commit_hashes = {commit.resulting_state_hash for commit in continuation.traversal_commits}
    linked = {
        epoch.state_hash: epoch.commit_sequence
        for epoch in timeline
        if epoch.commit_sequence is not None
    }
    assert commit_hashes <= set(linked)

    tip = timeline[-1]
    final = await store.get(run_id)
    assert final is not None
    assert tip.state_hash == graph_state_hash(final.graph_state)


async def test_load_first_interior_and_terminal_positions_inclusive() -> None:
    run_store, workspace_id, project_id = await _spine()
    continuations = InMemoryGraphContinuationStore()
    store = CanonicalDurableRunStore(run_store, continuations)
    run_id = await _completed_chain(workspace_id, project_id, run_store=run_store, store=store)
    record = await store.get(run_id)
    assert record is not None
    continuation = await continuations.get(run_id)
    assert continuation is not None
    total = len(continuation.state_timeline)

    first = await store.load_state(run_id, 1)
    assert first.run_id == run_id
    assert first.sequence == 1
    assert first.graph_state.active_node_ids == ("a",)
    assert len(first.events) == 1
    assert first.traversal_commits == ()
    assert first.graph_snapshot_hash == record.run.graph.content_hash

    interior = await _sequence_with_frontier(store, run_id, total, "b")
    mid = await store.load_state(run_id, interior)
    assert len(mid.events) == interior
    assert any(epoch.commit_sequence is not None for epoch in mid.events)
    assert [commit.commit_sequence for commit in mid.traversal_commits] == list(
        range(1, len(mid.traversal_commits) + 1)
    )

    tip = await store.load_state(run_id, total)
    assert tip.sequence == total
    assert tip.state_hash == graph_state_hash(record.graph_state)
    assert tip.graph_state.model_dump(mode="json") == record.graph_state.model_dump(mode="json")
    assert len(tip.events) == total
    # The inclusive rule: the tip slice ends with the epoch carrying the tip's
    # own content.
    assert tip.events[-1].state_hash == tip.state_hash


async def test_load_out_of_range_and_legacy_empty_timeline_fail_closed() -> None:
    run_store, workspace_id, project_id = await _spine()
    continuations = InMemoryGraphContinuationStore()
    store = CanonicalDurableRunStore(run_store, continuations)
    run_id = await _completed_chain(workspace_id, project_id, run_store=run_store, store=store)
    continuation = await continuations.get(run_id)
    assert continuation is not None
    total = len(continuation.state_timeline)

    for bad in (0, -1, total + 1, 10**6):
        with pytest.raises(SequenceOutOfRangeError):
            await store.load_state(run_id, bad)

    # A continuation written by a pre-timeline writer records no positions;
    # load refuses rather than synthesizing a state nobody persisted.
    graph = _counting_chain(workspace_id, project_id, [_Counting.kind])
    legacy_run = await run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    state = GraphExecutionState(
        run_id=legacy_run.run_id,
        active_node_ids=("a",),
        blackboard_snapshot={
            "task_objective": graph.name,
            "metadata": {},
            "node_annotations": {},
        },
        metadata={"initial_inputs": {}, "hitl_answers": {}},
    )
    await continuations.create(
        GraphContinuation.of(DurableRunRecord(run=legacy_run, graph_state=state, version=1))
    )
    with pytest.raises(SequenceOutOfRangeError):
        await store.load_state(legacy_run.run_id, 1)


async def test_load_unknown_run_fails_closed() -> None:
    run_store, _workspace_id, _project_id = await _spine()
    store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    with pytest.raises(UnknownGraphRunError):
        await store.load_state("no-such-run", 1)


async def test_repeated_load_is_equivalent_and_has_no_external_effect() -> None:
    run_store, workspace_id, project_id = await _spine()
    continuations = InMemoryGraphContinuationStore()
    store = CanonicalDurableRunStore(run_store, continuations)
    run_id = await _completed_chain(workspace_id, project_id, run_store=run_store, store=store)
    record_before = await store.get(run_id)
    assert record_before is not None
    continuation_before = await continuations.get(run_id)
    assert continuation_before is not None

    first = await store.load_state(run_id, 2)
    again = await store.load_state(run_id, 2)
    assert first == again

    continuation_after = await continuations.get(run_id)
    assert continuation_after is not None
    record_after = await store.get(run_id)
    assert record_after is not None
    assert continuation_after.version == continuation_before.version
    assert continuation_after.state_timeline == continuation_before.state_timeline
    assert len(record_after.node_runs) == len(record_before.node_runs)
    assert len(record_after.attempts) == len(record_before.attempts)
    assert record_after.run.status is record_before.run.status


async def test_load_fails_closed_on_pruned_or_foreign_revision_evidence() -> None:
    run_store, workspace_id, project_id = await _spine()
    continuations = InMemoryGraphContinuationStore()
    store = CanonicalDurableRunStore(run_store, continuations)
    run_id = await _completed_chain(workspace_id, project_id, run_store=run_store, store=store)
    continuation = await continuations.get(run_id)
    assert continuation is not None

    # Prune the latest commit beneath the tip epoch: the epoch still claims the
    # link, so load must refuse instead of trusting an orphaned state.
    pruned = continuation.model_copy(
        update={
            "traversal_commits": continuation.traversal_commits[:-1],
            "version": continuation.version + 1,
        }
    )
    await continuations.update(pruned)
    with pytest.raises(StateHistoryIntegrityError, match="pruned or rewritten"):
        await store.load_state(run_id, len(pruned.state_timeline))

    # A foreign Graph revision on an epoch can never describe this Run.
    tampered_epoch = GraphStateEpoch(
        sequence=1,
        state=pruned.state_timeline[0].state,
        state_hash=pruned.state_timeline[0].state_hash,
        graph_snapshot_hash="deadbeef-foreign-graph",
    )
    foreign = pruned.model_copy(
        update={
            "state_timeline": (tampered_epoch, *pruned.state_timeline[1:]),
            "version": pruned.version + 1,
        }
    )
    await continuations.update(foreign)
    with pytest.raises(StateHistoryIntegrityError, match="incompatible"):
        await store.load_state(run_id, 1)


@pytest.fixture
def counting_reset() -> Any:
    _Counting.executions.clear()
    yield _Counting.executions
    _Counting.executions.clear()


async def test_park_load_fork_proves_both_lineages_after_store_reopen(
    tmp_path: Path,
    counting_reset: Any,
) -> None:
    """The acceptance proof: park mid-graph, load an earlier sequence, fork,
    and inspect both lineages from stores reopened after the writes."""
    db_path = tmp_path / "time-travel.db"
    limits = RunConcurrencyLimits(per_workspace=64)

    async with aiosqlite.connect(db_path) as conn:
        projects = SqliteProjectScopeStore(conn)
        await projects.ensure_schema()
        root = await projects.create_root(_WORKSPACE)
        project = await projects.create(
            workspace_id=_WORKSPACE, parent_project_id=root.project_id, name="forks"
        )
        run_store = SqliteRunStore(conn, project_store=projects, concurrency_limits=limits)
        await run_store.ensure_schema()
        continuations = SqliteGraphContinuationStore(conn)
        await continuations.ensure_schema()
        store = CanonicalDurableRunStore(run_store, continuations)

        graph = _counting_chain(
            _WORKSPACE, project.project_id, [_Counting.kind, _Ask.kind, _Counting.kind]
        )
        run = await run_store.create_run(
            graph,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        paused = await run_durable_graph(
            graph,
            store=store,
            node_resolver=_resolver({"a": _Counting(), "b": _Ask(), "c": _Counting()}),
            run_id=run.run_id,
            run_store=run_store,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        assert paused.status is RunStatus.PAUSED
        parent_id = paused.run_id
        parent_node_runs = [item.node_run_id for item in paused.node_runs]
        parent_continuation = await continuations.get(parent_id)
        assert parent_continuation is not None
        parent_timeline = len(parent_continuation.state_timeline)
    # --- process death: the connection above is closed ---

    async with aiosqlite.connect(db_path) as conn:
        projects = SqliteProjectScopeStore(conn)
        await projects.ensure_schema()
        run_store = SqliteRunStore(conn, project_store=projects, concurrency_limits=limits)
        await run_store.ensure_schema()
        continuations = SqliteGraphContinuationStore(conn)
        await continuations.ensure_schema()
        store = CanonicalDurableRunStore(run_store, continuations)

        first = await store.load_state(parent_id, 1)
        assert first.graph_state.active_node_ids == ("a",)

        child = await store.fork_from_state(parent_id, 1, "restart from the beginning")
        child_id = child.run.run_id
        fact = _fork_fact(child.run)
        assert fact["parent_run_id"] == parent_id
        assert fact["source_event_sequence"] == 1
        assert fact["reason"] == "restart from the beginning"
        assert fact["graph_snapshot_hash"] == child.run.graph.content_hash
        assert child.run.parent_run_id == parent_id
        assert child.run.status is RunStatus.QUEUED
        assert child_id != parent_id
        assert child.graph_state.run_id == child_id
        assert child.graph_state.active_node_ids == ("a",)
        for key in ("pause", "pauses", "hitl_answers", "hitl_settlements"):
            assert key not in child.graph_state.metadata, (
                f"child inherited the parent's visit fact {key!r}"
            )
    # --- process death again: the fork itself must survive it ---

    async with aiosqlite.connect(db_path) as conn:
        projects = SqliteProjectScopeStore(conn)
        await projects.ensure_schema()
        run_store = SqliteRunStore(conn, project_store=projects, concurrency_limits=limits)
        await run_store.ensure_schema()
        continuations = SqliteGraphContinuationStore(conn)
        await continuations.ensure_schema()
        store = CanonicalDurableRunStore(run_store, continuations)

        parent = await store.get(parent_id)
        assert parent is not None
        assert parent.run.status is RunStatus.PAUSED, "fork rewrote the source Run"
        assert [item.node_run_id for item in parent.node_runs] == parent_node_runs
        parent_after = await continuations.get(parent_id)
        assert parent_after is not None
        assert len(parent_after.state_timeline) == parent_timeline

        child = await store.get(child_id)
        assert child is not None
        assert child.run.provenance[DURABLE_GRAPH_FORK_PROVENANCE]["parent_run_id"] == parent_id

        resumed = await resume_durable_graph(
            child_id,
            store=store,
            node_resolver=_resolver({"a": _Counting(), "b": _Ask(), "c": _Counting()}),
            run_store=run_store,
        )
        assert resumed.status is RunStatus.PAUSED, "the child asks its own question"
        answered = await store.submit_hitl_answer(
            child_id,
            "b",
            {"answer": "yes"},
            authorization=await hitl_authorization_for_workspace(),
        )
        assert answered.status is RunStatus.QUEUED
        finished = await resume_durable_graph(
            child_id,
            store=store,
            node_resolver=_resolver({"a": _Counting(), "b": _Ask(), "c": _Counting()}),
            run_store=run_store,
        )
        assert finished.status is RunStatus.COMPLETED

        parent_final = await store.get(parent_id)
        assert parent_final is not None
        assert parent_final.run.status is RunStatus.PAUSED
        assert [item.node_run_id for item in parent_final.node_runs] == parent_node_runs
        child_node_run_ids = {item.node_run_id for item in finished.node_runs}
        assert child_node_run_ids.isdisjoint(set(parent_node_runs))
        lineage_ids = {item.run_id for item in await store.list_for_project(project.project_id)}
        assert {parent_id, child_id} <= lineage_ids


async def test_fork_inherits_state_data_not_completed_effects(
    counting_reset: Any,
) -> None:
    run_store, workspace_id, project_id = await _spine()
    store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    run_id = await _completed_chain(workspace_id, project_id, run_store=run_store, store=store)
    assert _Counting.executions == Counter({"a": 1, "b": 1, "c": 1})
    continuation = store._continuations
    continuation_row = await continuation.get(run_id)
    assert continuation_row is not None
    total = len(continuation_row.state_timeline)
    interior = await _sequence_with_frontier(store, run_id, total, "b")

    child = await store.fork_from_state(run_id, interior, "retry the tail only")
    assert _Counting.executions == Counter({"a": 1, "b": 1, "c": 1}), "fork executed a node"
    inherited = child.graph_state
    assert inherited.active_node_ids == ("b",)
    assert inherited.cycle >= 1
    assert any(
        decision.source_node_id == "a" and decision.selected
        for decision in inherited.edge_decisions
    ), "the completed a->b routing history is inherited as data"
    assert child.node_runs == ()

    resumed = await resume_durable_graph(
        child.run_id,
        store=store,
        node_resolver=_resolver({"a": _Counting(), "b": _Counting(), "c": _Counting()}),
        run_store=run_store,
    )
    assert resumed.status is RunStatus.COMPLETED
    assert _Counting.executions["a"] == 1, "the fork re-executed completed work"
    assert _Counting.executions["b"] == 2
    assert _Counting.executions["c"] == 2
    assert [item.node_id for item in resumed.node_runs] == ["b", "c"]
    for node_run in resumed.node_runs:
        assert node_run.run_id == child.run_id


async def test_stale_writer_cannot_rewind_history_with_prior_version() -> None:
    run_store, workspace_id, project_id = await _spine()
    continuations = InMemoryGraphContinuationStore()
    store = CanonicalDurableRunStore(run_store, continuations)

    graph = _counting_chain(workspace_id, project_id, [_Ask.kind, _Counting.kind])
    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolver({"a": _Ask(), "b": _Counting()}),
        run_id=await _admit(run_store, graph),
        run_store=run_store,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert paused.status is RunStatus.PAUSED
    stale = await store.get(paused.run_id)
    assert stale is not None

    from maistro.graph.durable_runs import HitlAuthorization

    async def _allow(_principal: str, _workspace_id: str) -> bool:
        return True

    await store.submit_hitl_answer(
        paused.run_id,
        "a",
        {"answer": "go"},
        authorization=HitlAuthorization(
            effective_principal="stale-writer-operator",
            workspace_ids=frozenset({_WORKSPACE}),
            membership_check=_allow,
        ),
    )
    current = await store.get(paused.run_id)
    assert current is not None
    assert current.version > stale.version

    with pytest.raises(ValueError, match="version regression"):
        await store.update(stale)
    after = await store.get(paused.run_id)
    assert after is not None
    continuation = await continuations.get(paused.run_id)
    assert continuation is not None
    assert [epoch.sequence for epoch in continuation.state_timeline] == list(
        range(1, len(continuation.state_timeline) + 1)
    )
    assert len(after.node_runs) == len(current.node_runs)

    # The fork's fresh identity cannot be duplicated by a second create either.
    child = await store.fork_from_state(paused.run_id, 1, "second lineage")
    with pytest.raises(ValueError, match="collision"):
        await store.create(
            DurableRunRecord(run=child.run, graph_state=child.graph_state, version=1)
        )


async def test_fork_records_goal_and_rubric_revisions() -> None:
    run_store, workspace_id, project_id = await _spine()
    store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    graph = _counting_chain(workspace_id, project_id, [_Counting.kind] * 2)

    named = await run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        # A Goal rides in the admission provenance (working_graph wiring).
        provenance={"goal_id": "goal-77"},
    )
    plain = await run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    plain_done = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolver({"a": _Counting(), "b": _Counting()}),
        run_id=plain.run_id,
        run_store=run_store,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert plain_done.status is RunStatus.COMPLETED

    scored = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolver({"a": _Counting(), "b": _Counting()}),
        run_id=named.run_id,
        run_store=run_store,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert scored.status is RunStatus.COMPLETED
    node_run = scored.node_runs[0]
    attempt = next(item for item in scored.attempts if item.node_run_id == node_run.node_run_id)
    await run_store.record_eval_score(
        RunEvalScore(
            run_id=scored.run_id,
            node_run_id=node_run.node_run_id,
            attempt_id=attempt.attempt_id,
            goal_id="goal-77",
            goal_revision=3,
            rubric_id="rubric-9",
            rubric_revision=5,
            dimension_id="accuracy",
            raw_score=0.9,
            passed=True,
            method=EvalMethod.DETERMINISTIC,
        )
    )

    child = await store.fork_from_state(scored.run_id, 1, "re-run under rubric 5")
    fact = _fork_fact(child.run)
    assert fact["parent_run_id"] == scored.run_id
    assert fact["source_event_sequence"] == 1
    assert fact["graph_snapshot_hash"] == scored.run.graph.content_hash
    assert fact["goal_id"] == "goal-77"
    assert fact["goal_revision"] == 3
    assert fact["rubric_id"] == "rubric-9"
    assert fact["rubric_revision"] == 5
    assert datetime.fromisoformat(str(fact["forked_at"])).tzinfo is UTC

    plain_child = await store.fork_from_state(plain.run_id, 1, "no eval history")
    plain_fact = _fork_fact(plain_child.run)
    assert "goal_id" not in plain_fact
    assert "rubric_revision" not in plain_fact
    assert plain_fact["reason"] == "no eval history"


async def test_fork_rejects_blank_reason_and_bad_sequence() -> None:
    run_store, workspace_id, project_id = await _spine()
    store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    run_id = await _completed_chain(workspace_id, project_id, run_store=run_store, store=store)

    with pytest.raises(ValueError, match="non-blank reason"):
        await store.fork_from_state(run_id, 1, "   ")
    with pytest.raises(SequenceOutOfRangeError):
        await store.fork_from_state(run_id, 10**6, "off the tip")
    with pytest.raises(UnknownGraphRunError):
        await store.fork_from_state("no-such-run", 1, "ghost")


async def test_epoch_append_is_stable_for_unchanged_state() -> None:
    """Same content written twice must not extend the timeline: positions are
    stable once recorded, or a sequence would not name one state forever."""
    state = GraphExecutionState(
        run_id="run-epoch",
        active_node_ids=("a",),
        blackboard_snapshot={"task_objective": "t"},
        metadata={"initial_inputs": {}},
    )
    continuation = GraphContinuation(run_id="run-epoch", graph_state=state, version=1)

    appended = state_epoch_appended(continuation, previous=None, graph_snapshot_hash="graph-hash")
    assert len(appended.state_timeline) == 1
    assert appended.state_timeline[0].sequence == 1
    assert appended.state_timeline[0].state_hash == graph_state_hash(state)

    stable = state_epoch_appended(
        continuation.model_copy(update={"version": 2}),
        previous=appended,
        graph_snapshot_hash="graph-hash",
    )
    assert len(stable.state_timeline) == 1

    changed_state = GraphExecutionState.model_validate(
        {**state.model_dump(mode="json"), "cycle": 1}
    )
    advanced = state_epoch_appended(
        continuation.model_copy(update={"graph_state": changed_state, "version": 3}),
        previous=appended,
        graph_snapshot_hash="graph-hash",
    )
    assert [epoch.sequence for epoch in advanced.state_timeline] == [1, 2]
    assert advanced.state_timeline[1].state_hash == graph_state_hash(changed_state)
