"""Pending human work is queryable before the limit (#1109).

`/v1/hitl/pending` used to page the generic PAUSED listing and filter each
page in memory, so `limit` bounded a PAUSED *prefix* rather than human work:
more machine-only pauses than one request could inspect hid the human pause
behind them from every request, permanently, because every request reread the
same prefix from the top. The fix is the pause-kind projection the issue asks
for by preference: `has_hitl_pause` on the continuation, maintained on every
write beside the deadline projection (#1056), and `list_hitl_paused` reading
it, so human eligibility is decided by the store before any page is cut.

These run against all three continuation backends for the same reason
`test_canonical_due_scan` does — the fix is a statement about keyset paging
(`after`) and each backend orders and compares that cursor its own way — and
against the canonical and standalone run stores, because each must revalidate
the projection against the canonical record: an index is a candidate page,
never a second queue.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import aiosqlite
import pytest
from pydantic import BaseModel

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    pending_hitl_node_ids,
    pending_hitl_records,
    run_durable_graph,
)
from maistro.graph.durable_runs.continuation import (
    GraphContinuation,
    GraphContinuationStore,
    InMemoryGraphContinuationStore,
    SqliteGraphContinuationStore,
)
from maistro.graph.durable_runs.hitl import HitlAuthorization
from maistro.graph.durable_runs.stores import InMemoryDurableRunStore, SqliteDurableRunStore
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import BaseNode, NodeContext, pause_until
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.lifecycle import transition_node_run, transition_run
from maistro.runs.model import GraphSnapshot, NodeRun, Run, RunStatus
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

pytestmark = [pytest.mark.contract("behavioral")]

WORKSPACE = "workspace-hitl-paused"
OTHER_WORKSPACE = "workspace-hitl-paused-other"
BASE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class _Empty(BaseModel):
    pass


class _DeadlinelessAsk(BaseNode[_Empty, _Empty]):
    """A human pause carrying no deadline at all.

    This is the row the deadline index (#1056) can never return and the
    pause-kind projection must: a person waiting without a timeout is still a
    person waiting.
    """

    kind: ClassVar[str] = "test.hitl_paused_index.deadlineless_ask"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = _Empty
    output_schema: ClassVar[type[BaseModel]] = _Empty

    async def _execute(self, inputs: _Empty, ctx: NodeContext) -> _Empty:
        pause_until("awaiting_human_answer", metadata={"question": "Ship it?"})
        return _Empty()


async def _allow_membership(_principal: str, _workspace_id: str) -> bool:
    return True


def _authorization(*workspace_ids: str) -> HitlAuthorization:
    return HitlAuthorization(
        effective_principal="test-hitl-operator",
        workspace_ids=frozenset(workspace_ids or (WORKSPACE,)),
        membership_check=_allow_membership,
    )


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def continuations(
    request: pytest.FixtureRequest, tmp_path: Any, pg_pool: Any
) -> AsyncIterator[GraphContinuationStore]:
    if request.param == "memory":
        yield InMemoryGraphContinuationStore()
        return
    if request.param == "sqlite":
        async with aiosqlite.connect(tmp_path / "continuations.db") as conn:
            store = SqliteGraphContinuationStore(conn)
            await store.ensure_schema()
            yield store
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.graph.durable_runs.pg_continuation import PgGraphContinuationStore

    yield PgGraphContinuationStore(pg_pool)


def _record(
    run_id: str,
    *,
    kind: str = "hitl",
    status: RunStatus = RunStatus.PAUSED,
    project_id: str = "proj-pending",
    workspace_id: str = WORKSPACE,
    created_at: datetime = BASE,
    with_deadline: bool = False,
) -> DurableRunRecord:
    """A durable record paused the way the executor leaves one."""
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="pending discovery",
        nodes=[Node(node_id="ask", node_type="human.ask_question")],
    )
    run = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        graph=GraphSnapshot.from_graph(graph),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    run = run.model_copy(update={"created_at": created_at})
    run = transition_run(run, RunStatus.QUEUED)
    run = transition_run(run, RunStatus.RUNNING)
    if status is not RunStatus.RUNNING:
        run = transition_run(run, status)
    node_run = NodeRun(run_id=run_id, node_id="ask", ordinal=1)
    node_run = transition_node_run(node_run, RunStatus.QUEUED)
    node_run = transition_node_run(node_run, RunStatus.RUNNING)
    node_run = transition_node_run(node_run, RunStatus.PAUSED)
    pause: dict[str, Any] = {"kind": kind, "metadata": {"question": "Ship it?"}}
    if with_deadline:
        pause["resume_at"] = (BASE + timedelta(hours=1)).isoformat()
    state = GraphExecutionState(
        run_id=run_id,
        active_node_ids=("ask",),
        blackboard_snapshot={},
        metadata={"initial_inputs": {}, "hitl_answers": {}, "pauses": {"ask": pause}},
    )
    return DurableRunRecord(
        run=run,
        graph_state=state,
        node_runs=(node_run,),
        version=1,
    )


async def _plant(
    continuations: GraphContinuationStore,
    record: DurableRunRecord,
) -> None:
    await continuations.create(GraphContinuation.of(record))


async def test_projection_claims_only_human_paused_rows(continuations) -> None:
    """The projection is pause-kind at PAUSED, not any pause at any status."""
    await _plant(continuations, _record("paused-human"))
    await _plant(continuations, _record("paused-machine", kind="wait"))
    await _plant(continuations, _record("running-human", status=RunStatus.RUNNING))
    await _plant(continuations, _record("waiting-human", status=RunStatus.WAITING))

    run_ids = await continuations.list_hitl_paused_run_ids()

    assert run_ids == ["paused-human"]


async def test_projection_includes_a_human_pause_without_a_deadline(continuations) -> None:
    """A person waiting without a timeout is still a person waiting.

    The deadline projection (#1056) leaves this row NULL, which is exactly why
    pending discovery cannot reuse `list_hitl_due`: it would hide every
    deadline-less human pause behind the same bounded-prefix defect.
    """
    await _plant(
        continuations,
        _record("deadlineless-human", created_at=BASE + timedelta(minutes=1)),
    )
    await _plant(continuations, _record("deadline-human", created_at=BASE + timedelta(minutes=2)))

    run_ids = await continuations.list_hitl_paused_run_ids()

    assert run_ids == ["deadlineless-human", "deadline-human"]


async def test_machine_prefix_never_occupies_the_projection_page(continuations) -> None:
    """The starvation shape, at the projection: a machine-only prefix, longer
    than the page, ahead of human work. The query bounds human work, not a
    PAUSED prefix, so the page holds the human rows and only them."""
    for index in range(10):
        await _plant(continuations, _record(f"machine-{index:02d}", kind="wait"))
    await _plant(continuations, _record("human-1"))
    await _plant(continuations, _record("human-2"))

    first = await continuations.list_hitl_paused_run_ids(limit=2)
    assert first == ["human-1", "human-2"]

    from maistro.graph.durable_runs.fair_scan import cursor_time

    resume_after = (
        cursor_time(BASE),
        "human-2",
    )
    rest = await continuations.list_hitl_paused_run_ids(limit=2, after=resume_after)
    assert rest == []


async def test_projection_filters_by_project(continuations) -> None:
    """Project scope narrows the projection; it cannot leak another project."""
    await _plant(continuations, _record("mine"))
    await _plant(continuations, _record("theirs", project_id="proj-other"))

    run_ids = await continuations.list_hitl_paused_run_ids(project_id="proj-pending")

    assert run_ids == ["mine"]


async def test_projection_pages_forward_on_the_created_cursor(continuations) -> None:
    """`after` is the store's own keyset spelling: strictly newer, per page."""
    for index in range(4):
        await _plant(
            continuations, _record(f"human-{index}", created_at=BASE + timedelta(minutes=index))
        )

    from maistro.graph.durable_runs.fair_scan import cursor_time

    page = await continuations.list_hitl_paused_run_ids(limit=2)
    assert page == ["human-0", "human-1"]
    rest = await continuations.list_hitl_paused_run_ids(
        limit=2, after=(cursor_time(BASE + timedelta(minutes=1)), "human-1")
    )
    assert rest == ["human-2", "human-3"]


async def _canonical_fixture() -> tuple[CanonicalDurableRunStore, InMemoryRunStore, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    run_store = InMemoryRunStore(project_store=projects)
    return (
        CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore()),
        run_store,
        (root.project_id),
    )


async def test_real_human_pause_without_a_deadline_is_discoverable() -> None:
    """End to end through the executor: the durable frontier, not a fixture's
    say-so, puts the pause in the projection — with no deadline anywhere."""
    store, run_store, project_id = await _canonical_fixture()
    graph = Graph(
        workspace_id=WORKSPACE,
        project_id=project_id,
        name="deadlineless",
        nodes=[Node(node_id="ask", node_type=_DeadlinelessAsk.kind)],
    )
    admitted = await run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=lambda node_id, current_graph: _DeadlinelessAsk(),
        run_id=admitted.run_id,
        run_store=run_store,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert paused.status is RunStatus.PAUSED
    # The deadline projection is NULL by construction; the pause-kind
    # projection is what makes this Run discoverable.
    assert paused.resume_at is None

    found = await store.list_hitl_paused(limit=10, project_id=project_id)

    assert [record.run_id for record in found] == [paused.run_id]


async def test_machine_only_paused_prefix_cannot_occupy_the_page() -> None:
    """The mutation this seam must fail: `list_by_status(PAUSED, limit=N)`
    followed by an in-memory HITL filter bounds a generic PAUSED prefix, so
    machine-only pauses ahead of human work hide it from every page. The
    projection decides eligibility before the limit, so the page holds the
    human Run however long the prefix ahead of it grows."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    run_store = InMemoryRunStore(project_store=projects)
    continuations = InMemoryGraphContinuationStore()
    store = CanonicalDurableRunStore(run_store, continuations)
    for index in range(5):
        await _canonical_row(
            run_store,
            continuations,
            run_id=f"machine-{index}",
            workspace_id=WORKSPACE,
            project_id=root.project_id,
            # PAUSED with no human pause in the frontier: the ineligible
            # prefix the issue plants.
            with_pause=False,
        )
    human_id = await _canonical_row(
        run_store,
        continuations,
        run_id="human-behind-the-prefix",
        workspace_id=WORKSPACE,
        project_id=root.project_id,
    )

    page = await store.list_hitl_paused(limit=2, project_id=root.project_id)

    assert [record.run_id for record in page] == [human_id]


async def test_answering_removes_the_run_from_the_projection() -> None:
    """The projection follows the canonical lifecycle: answered work stops
    being pending on the next read, without a second queue to retire."""
    store, run_store, project_id = await _canonical_fixture()
    graph = Graph(
        workspace_id=WORKSPACE,
        project_id=project_id,
        name="answered",
        nodes=[Node(node_id="ask", node_type=_DeadlinelessAsk.kind)],
    )
    admitted = await run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=lambda node_id, current_graph: _DeadlinelessAsk(),
        run_id=admitted.run_id,
        run_store=run_store,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert [record.run_id for record in await store.list_hitl_paused(project_id=project_id)] == [
        paused.run_id
    ]

    await store.submit_hitl_answer(
        paused.run_id,
        "ask",
        {"answer": "yes"},
        authorization=_authorization(WORKSPACE),
    )

    assert await store.list_hitl_paused(project_id=project_id) == []


async def _canonical_row(
    run_store: InMemoryRunStore,
    continuations: GraphContinuationStore,
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    status: RunStatus = RunStatus.PAUSED,
    with_pause: bool = True,
) -> None:
    """One canonical spine Run plus its continuation, the way persistence
    writes them: the Run on the spine, the pause facts in the frontier, the
    projection denormalized beside them."""
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="pending discovery",
        nodes=[Node(node_id="ask", node_type="human.ask_question")],
    )
    admitted = await run_store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    await run_store.transition_run(admitted.run_id, RunStatus.RUNNING)
    if status is not RunStatus.RUNNING:
        await run_store.transition_run(admitted.run_id, status)
    run = await run_store.get_run(admitted.run_id)
    assert run is not None
    node_runs = tuple(await run_store.list_node_runs(admitted.run_id))
    pauses = {"ask": {"kind": "hitl", "metadata": {"question": "Ship it?"}}} if with_pause else {}
    state = GraphExecutionState(
        run_id=admitted.run_id,
        active_node_ids=("ask",) if with_pause else (),
        blackboard_snapshot={},
        metadata={"initial_inputs": {}, "hitl_answers": {}, "pauses": pauses},
    )
    record = DurableRunRecord(run=run, graph_state=state, node_runs=node_runs, version=1)
    await continuations.create(GraphContinuation.of(record))
    return admitted.run_id


async def test_stale_projected_row_is_never_disclosed() -> None:
    """An index is a candidate page, not a second queue: a row the projection
    claims but canonical state disqualifies is dropped at read time."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    run_store = InMemoryRunStore(project_store=projects)
    continuations = InMemoryGraphContinuationStore()
    store = CanonicalDurableRunStore(run_store, continuations)
    stale_id = await _canonical_row(
        run_store,
        continuations,
        run_id="stale-claim",
        workspace_id=WORKSPACE,
        project_id=root.project_id,
        status=RunStatus.WAITING,
        with_pause=False,
    )
    # A row whose projection says "human pause" while the durable frontier and
    # the canonical Run both say otherwise.
    stored = await continuations.get(stale_id)
    assert stored is not None
    await continuations.update(
        stored.model_copy(update={"version": 2, "status": RunStatus.PAUSED, "has_hitl_pause": True})
    )

    found = await store.list_hitl_paused(limit=10, project_id=root.project_id)

    assert found == []


async def test_canonical_scope_filters_bind_before_disclosure() -> None:
    """Project and Workspace scope filter the assembled canonical records:
    another tenant's human work is not in the page, whatever the index holds."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    other_root = await projects.create_root(OTHER_WORKSPACE)
    run_store = InMemoryRunStore(project_store=projects)
    continuations = InMemoryGraphContinuationStore()
    store = CanonicalDurableRunStore(run_store, continuations)
    mine_id = await _canonical_row(
        run_store,
        continuations,
        run_id="mine",
        workspace_id=WORKSPACE,
        project_id=root.project_id,
    )
    await _canonical_row(
        run_store,
        continuations,
        run_id="theirs",
        workspace_id=OTHER_WORKSPACE,
        project_id=other_root.project_id,
    )
    other_project = await projects.create(
        workspace_id=WORKSPACE,
        parent_project_id=root.project_id,
        name="sibling project",
    )
    await _canonical_row(
        run_store,
        continuations,
        run_id="other-project",
        workspace_id=WORKSPACE,
        project_id=other_project.project_id,
    )

    mine = await store.list_hitl_paused(project_id=root.project_id)
    assert [record.run_id for record in mine] == [mine_id]
    leaked = [
        record
        for record in await store.list_hitl_paused(project_id=root.project_id)
        if record.run.workspace_id == OTHER_WORKSPACE
    ]
    assert leaked == []
    scoped = await store.list_hitl_paused(project_id=root.project_id, workspace_id=WORKSPACE)
    assert [record.run_id for record in scoped] == [mine_id]
    foreign = await store.list_hitl_paused(project_id=root.project_id, workspace_id=OTHER_WORKSPACE)
    assert foreign == []


@pytest.fixture(params=["memory", "sqlite"])
async def standalone_store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[InMemoryDurableRunStore | SqliteDurableRunStore]:
    if request.param == "memory":
        yield InMemoryDurableRunStore()
        return
    yield SqliteDurableRunStore(tmp_path / "durable.db")


async def test_standalone_stores_page_the_projection(standalone_store) -> None:
    """The door's fallback store answers the same projection contract, so the
    fix cannot depend on which backend the product happened to boot."""
    for index in range(6):
        await standalone_store.create(
            _record(
                f"machine-{index}",
                kind="wait",
                created_at=BASE + timedelta(seconds=index),
            )
        )
    await standalone_store.create(_record("human-1", created_at=BASE + timedelta(seconds=100)))
    await standalone_store.create(_record("human-2", created_at=BASE + timedelta(seconds=101)))

    page = await standalone_store.list_hitl_paused(limit=1)
    assert [record.run_id for record in page] == ["human-1"]

    rest = await standalone_store.list_hitl_paused(
        limit=5,
        after=(  # the store's own cursor spelling
            (BASE + timedelta(seconds=100)).astimezone(UTC).isoformat(),
            "human-1",
        ),
    )
    assert [record.run_id for record in rest] == ["human-2"]

    foreign = await standalone_store.list_hitl_paused(
        limit=5,
        workspace_id=OTHER_WORKSPACE,
    )
    assert foreign == []


async def test_sqlite_reopens_with_the_projection_intact(tmp_path: Path) -> None:
    """Restart keeps discovery working, two ways: the persisted projection
    survives a reopen, and rows written before the column existed are
    backfilled from the durable pause entries rather than hidden."""
    path = tmp_path / "durable.db"
    store = SqliteDurableRunStore(path)
    await store.create(_record("survives-restart"))

    reopened = SqliteDurableRunStore(path)
    assert [r.run_id for r in await reopened.list_hitl_paused()] == ["survives-restart"]

    # Simulate a row written before the projection existed: NULL means "not
    # projected", and the reopen must claim it from the durable pause entry.
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE durable_graph_runs SET has_hitl_pause = NULL")
        conn.commit()
    assert [r.run_id for r in await reopened.list_hitl_paused()] == []

    repaired = SqliteDurableRunStore(path)
    assert [r.run_id for r in await repaired.list_hitl_paused()] == ["survives-restart"]


# --- the canonical walk (`pending_hitl_records`) ---


def _multi_pause_record(
    run_id: str,
    node_ids: tuple[str, ...],
    *,
    project_id: str = "proj-pending",
    workspace_id: str = WORKSPACE,
    created_at: datetime = BASE,
) -> DurableRunRecord:
    """One Run waiting on a person at several nodes independently."""
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="multi pause",
        nodes=[Node(node_id=node_id, node_type="human.ask_question") for node_id in node_ids],
    )
    run = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        graph=GraphSnapshot.from_graph(graph),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    run = run.model_copy(update={"created_at": created_at})
    run = transition_run(run, RunStatus.QUEUED)
    run = transition_run(run, RunStatus.RUNNING)
    run = transition_run(run, RunStatus.PAUSED)
    node_runs = tuple(
        transition_node_run(
            transition_node_run(
                transition_node_run(
                    NodeRun(run_id=run_id, node_id=node_id, ordinal=ordinal),
                    RunStatus.QUEUED,
                ),
                RunStatus.RUNNING,
            ),
            RunStatus.PAUSED,
        )
        for ordinal, node_id in enumerate(node_ids, start=1)
    )
    state = GraphExecutionState(
        run_id=run_id,
        active_node_ids=node_ids,
        blackboard_snapshot={},
        metadata={
            "initial_inputs": {},
            "hitl_answers": {},
            "pauses": {
                node_id: {"kind": "hitl", "metadata": {"question": "Ship it?"}}
                for node_id in node_ids
            },
        },
    )
    return DurableRunRecord(run=run, graph_state=state, node_runs=node_runs, version=1)


async def test_walk_bounds_items_not_records() -> None:
    """`limit` bounds pending items, and each Run's pauses count individually."""
    store = InMemoryDurableRunStore()
    first = _record("walk-first", created_at=BASE)
    second = _record("walk-second", created_at=BASE + timedelta(seconds=1))
    await store.create(first)
    await store.create(second)
    authorization = _authorization(WORKSPACE)

    one = await pending_hitl_records(
        store,
        authorization=authorization,
        workspace_id=WORKSPACE,
        project_id="proj-pending",
        limit=1,
    )
    assert [record.run_id for record in one.records] == ["walk-first"]
    assert one.exhausted is False  # the item limit stopped it, not the projection

    both = await pending_hitl_records(
        store,
        authorization=authorization,
        workspace_id=WORKSPACE,
        project_id="proj-pending",
        limit=5,
    )
    assert [record.run_id for record in both.records] == ["walk-first", "walk-second"]
    assert both.exhausted is True  # the projection ran out


async def test_walk_counts_a_multi_pause_run_against_the_item_limit() -> None:
    """One Run waiting at two nodes carries two items against one limit."""
    store = InMemoryDurableRunStore()
    await store.create(_multi_pause_record("walk-multi", ("ask-a", "ask-b")))

    scan = await pending_hitl_records(
        store,
        authorization=_authorization(WORKSPACE),
        workspace_id=WORKSPACE,
        project_id="proj-pending",
        limit=1,
    )

    assert [record.run_id for record in scan.records] == ["walk-multi"]
    assert len(pending_hitl_node_ids(scan.records[0])) == 2


async def test_walk_excludes_work_the_authorization_cannot_see() -> None:
    """The membership predicate is the disclosure decision: a caller whose
    live membership check fails sees nothing, whatever the projection holds."""
    store = InMemoryDurableRunStore()
    await store.create(_record("walk-denied"))

    async def deny(_principal: str, _workspace_id: str) -> bool:
        return False

    scan = await pending_hitl_records(
        store,
        authorization=HitlAuthorization(
            effective_principal="test-hitl-operator",
            workspace_ids=frozenset({WORKSPACE}),
            membership_check=deny,
        ),
        workspace_id=WORKSPACE,
        project_id="proj-pending",
        limit=10,
    )

    assert scan.records == ()


async def test_walk_without_a_project_covers_the_workspace() -> None:
    """`project_id=None` walks the whole Workspace; a named Project narrows."""
    store = InMemoryDurableRunStore()
    await store.create(_record("walk-proj-a", project_id="proj-a", created_at=BASE))
    await store.create(
        _record("walk-proj-b", project_id="proj-b", created_at=BASE + timedelta(seconds=1))
    )

    wide = await pending_hitl_records(
        store,
        authorization=_authorization(WORKSPACE),
        workspace_id=WORKSPACE,
        project_id=None,
        limit=10,
    )
    assert [record.run_id for record in wide.records] == ["walk-proj-a", "walk-proj-b"]
    assert wide.exhausted is True

    narrow = await pending_hitl_records(
        store,
        authorization=_authorization(WORKSPACE),
        workspace_id=WORKSPACE,
        project_id="proj-b",
        limit=10,
    )
    assert [record.run_id for record in narrow.records] == ["walk-proj-b"]


async def test_walk_stops_at_the_inspection_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One request's cost is bounded even when human work remains behind it."""
    import maistro.graph.durable_runs.hitl as hitl_scan

    monkeypatch.setattr(hitl_scan, "MAX_PENDING_SCAN_RECORDS", 1)
    store = InMemoryDurableRunStore()
    await store.create(_record("ceiling-first", created_at=BASE))
    await store.create(_record("ceiling-second", created_at=BASE + timedelta(seconds=1)))

    scan = await pending_hitl_records(
        store,
        authorization=_authorization(WORKSPACE),
        workspace_id=WORKSPACE,
        project_id="proj-pending",
        limit=5,
    )

    assert [record.run_id for record in scan.records] == ["ceiling-first"]
    assert scan.exhausted is False
