"""Stale due-index rows must not hide live due work (#1098, #1127).

`CanonicalDurableRunStore` keeps its due index in the continuation store and
the Run status on the canonical spine, so the two can disagree: a continuation
still carries an elapsed `resume_at` while its Run has already completed. Those
rows sit at the front of the deadline ordering and stay there until
reconciliation retires them.

`list_due` reads one bounded page of them, assembles it, and drops every row
whose Run is no longer due -- so a page made entirely of stale rows comes back
empty, which is exactly what the end of the index also looks like. A fair scan
that reads the two as the same thing resets its continuation to the top on
every tick and never reaches the live Run behind the stale prefix, however many
ticks it is given.

These run against all three continuation backends, because the fix is a
statement about keyset paging (`after`) and each backend orders and compares
that cursor its own way.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import aiosqlite
import pytest

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import CanonicalDurableRunStore
from maistro.graph.durable_runs.continuation import (
    GraphContinuation,
    GraphContinuationStore,
    InMemoryGraphContinuationStore,
    SqliteGraphContinuationStore,
)
from maistro.graph.durable_runs.fair_scan import ScanContinuation, fair_page_scan
from maistro.graph.execution_state import GraphExecutionState
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import RunStatus

pytestmark = [pytest.mark.contract("behavioral")]

WORKSPACE = "workspace-due-scan"
NOW = datetime(2026, 9, 12, 4, 0, tzinfo=UTC)

#: One full default page of stale rows, which is the shape that starves: the
#: whole page is dropped, so the walk sees an empty list and cannot tell it
#: from the end of the index.
STALE_AHEAD = 100


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


async def _spine() -> tuple[InMemoryRunStore, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    project = await projects.create(
        workspace_id=WORKSPACE, parent_project_id=root.project_id, name="Due"
    )
    return InMemoryRunStore(project_store=projects), WORKSPACE, project.project_id


async def _row(
    run_store: InMemoryRunStore,
    continuations: GraphContinuationStore,
    *,
    workspace_id: str,
    project_id: str,
    resume_at: datetime,
    settled: bool,
) -> str:
    """One due-index row whose canonical Run is either settled or still live."""
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="due scan",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    await run_store.transition_run(run.run_id, RunStatus.RUNNING)
    await run_store.transition_run(
        run.run_id, RunStatus.COMPLETED if settled else RunStatus.WAITING
    )
    await continuations.create(
        GraphContinuation(
            run_id=run.run_id,
            graph_state=GraphExecutionState(run_id=run.run_id),
            status=RunStatus.WAITING,
            project_id=project_id,
            created_at=resume_at,
            resume_at=resume_at,
        )
    )
    return run.run_id


async def _stale_prefix_then_live(
    continuations: GraphContinuationStore,
) -> tuple[CanonicalDurableRunStore, str]:
    """`STALE_AHEAD` settled rows, then one Run that really is due."""
    run_store, workspace_id, project_id = await _spine()
    store = CanonicalDurableRunStore(run_store, continuations)
    for index in range(STALE_AHEAD):
        await _row(
            run_store,
            continuations,
            workspace_id=workspace_id,
            project_id=project_id,
            resume_at=NOW - timedelta(minutes=30) + timedelta(seconds=index),
            settled=True,
        )
    live = await _row(
        run_store,
        continuations,
        workspace_id=workspace_id,
        project_id=project_id,
        resume_at=NOW - timedelta(seconds=1),
        settled=False,
    )
    return store, live


async def test_a_full_page_of_settled_rows_reads_as_no_due_work(
    continuations: GraphContinuationStore,
) -> None:
    """The precondition, stated as a test: this is why an empty page cannot be
    read as the end of the index."""
    store, _live = await _stale_prefix_then_live(continuations)

    assert await store.list_due(now=NOW, limit=STALE_AHEAD) == []


async def test_the_live_run_behind_a_settled_page_is_found_in_one_scan(
    continuations: GraphContinuationStore,
) -> None:
    store, live = await _stale_prefix_then_live(continuations)

    page = await store.scan_due_page(now=NOW, limit=1)

    assert [record.run_id for record in page.items] == [live]
    assert page.inspected == STALE_AHEAD + 1
    assert page.exhausted is False
    assert page.resume_after is not None


async def test_a_scan_over_the_store_reaches_it_rather_than_resetting_each_tick(
    continuations: GraphContinuationStore,
) -> None:
    """The whole seam: the combinator over the real store, ticked twice.

    Before the fix the first tick returned nothing and reset the continuation
    to the top, so the second tick re-read the identical settled page. The
    live Run was unreachable on every tick, forever.
    """
    store, live = await _stale_prefix_then_live(continuations)
    scan: ScanContinuation[tuple[str, str]] = ScanContinuation()

    async def tick() -> list[str]:
        found = await fair_page_scan(
            fetch_page=lambda cursor, page_size: store.scan_due_page(
                now=NOW, limit=page_size, after=cursor
            ),
            cursor_of=lambda record: (record.resume_at.isoformat(), record.run_id),
            eligible=lambda record: True,
            limit=1,
            continuation=scan,
        )
        return [record.run_id for record in found]

    assert await tick() == [live]
    # Nothing left behind it: the next tick walks off the end and says so by
    # resetting, which is the one case where starting over is right.
    assert await tick() == []
    assert scan.resume_after is None


async def test_an_exhausted_index_is_reported_as_exhausted(
    continuations: GraphContinuationStore,
) -> None:
    run_store, workspace_id, project_id = await _spine()
    store = CanonicalDurableRunStore(run_store, continuations)
    await _row(
        run_store,
        continuations,
        workspace_id=workspace_id,
        project_id=project_id,
        resume_at=NOW - timedelta(seconds=5),
        settled=True,
    )

    page = await store.scan_due_page(now=NOW, limit=5)

    assert page.items == []
    assert page.exhausted is True
    assert page.inspected == 1


async def test_the_inspection_ceiling_bounds_one_scan_of_a_settled_prefix(
    continuations: GraphContinuationStore,
) -> None:
    """The bound the issues ask for: a long settled prefix costs a bounded
    walk per tick, and the position it reached carries to the next one."""
    store, live = await _stale_prefix_then_live(continuations)

    first = await store.scan_due_page(now=NOW, limit=1, max_inspected=10)

    assert first.items == []
    assert first.inspected == 10
    assert first.exhausted is False

    second = await store.scan_due_page(
        now=NOW, limit=1, after=first.resume_after, max_inspected=STALE_AHEAD
    )
    assert [record.run_id for record in second.items] == [live]
