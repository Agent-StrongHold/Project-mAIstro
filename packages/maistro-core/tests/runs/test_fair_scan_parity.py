"""A bounded scan with a continuation reaches every Run on every backend (#1127, #1098).

`tests/graph/durable_runs/test_fair_scan.py` pins the combinator over a fake
store and `test_recovery_wakeup.py` pins the recovery seam over a fake Run
store. This is the same multi-tick regression over the *real* keyset paging
each `RunStore` backend implements — in-memory, SQLite and PostgreSQL — because
"resume after the last inspected row" is only as true as `list_by_status(...,
after=cursor)` makes it, and the three backends order and compare that cursor
in three different ways.

More foreign QUEUED Runs than one tick may inspect (`DEFAULT_MAX_INSPECTED`),
the one eligible Run ordered last: a tick that restarts from the top returns
nothing forever; a tick that resumes where the last one stopped returns it on
the second call.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.graph.durable_runs.fair_scan import (
    DEFAULT_MAX_INSPECTED,
    ScanContinuation,
    fair_page_scan,
)
from maistro.runs.model import Run, RunStatus
from maistro.runs.store import run_cursor_key

pytestmark = [pytest.mark.contract("behavioral")]


async def _queued_runs(store: Any, workspace: str, project_id: str, count: int) -> list[Run]:
    graph = Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="fair scan parity",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    return [await store.create_run(graph, initial_status=RunStatus.QUEUED) for _ in range(count)]


async def test_a_run_behind_more_foreign_runs_than_one_tick_inspects_is_reached_on_the_next(
    spine: Any,
) -> None:
    store, workspace, project_id = spine
    runs = await _queued_runs(store, workspace, project_id, DEFAULT_MAX_INSPECTED + 1)
    # "Last" by the store's own keyset order, not by creation sequence: two
    # Runs created in the same microsecond tie on created_at and the id
    # breaks the tie, so the ordering is the store's to decide.
    target = max(runs, key=run_cursor_key)
    scan: ScanContinuation[tuple[str, str]] = ScanContinuation()

    def _tick():
        return fair_page_scan(
            fetch_page=lambda cursor, page_size: store.list_by_status(
                RunStatus.QUEUED, limit=page_size, project_id=project_id, after=cursor
            ),
            cursor_of=run_cursor_key,
            eligible=lambda run: run.run_id == target.run_id,
            limit=1,
            continuation=scan,
        )

    first = await _tick()
    assert first == []
    assert scan.resume_after is not None

    second = await _tick()

    assert [run.run_id for run in second] == [target.run_id]
    assert scan.resume_after == run_cursor_key(target)
