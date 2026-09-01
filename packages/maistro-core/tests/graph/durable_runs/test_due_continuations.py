from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite
import pytest

from maistro.graph.durable_runs.continuation import (
    GraphContinuation,
    InMemoryGraphContinuationStore,
    SqliteGraphContinuationStore,
)
from maistro.graph.execution_state import GraphExecutionState
from maistro.runs.model import RunStatus

pytestmark = [pytest.mark.contract("behavioral")]


def _continuation(
    run_id: str,
    *,
    status: RunStatus,
    resume_at: datetime | None,
    created_at: datetime,
) -> GraphContinuation:
    return GraphContinuation(
        run_id=run_id,
        graph_state=GraphExecutionState(run_id=run_id),
        status=status,
        project_id="project-1",
        created_at=created_at,
        resume_at=resume_at,
    )


async def _assert_due_query(store) -> None:
    now = datetime(2026, 9, 1, 3, 30, tzinfo=UTC)
    rows = (
        _continuation(
            "due-waiting",
            status=RunStatus.WAITING,
            resume_at=now - timedelta(seconds=2),
            created_at=now - timedelta(minutes=3),
        ),
        _continuation(
            "hitl-paused",
            status=RunStatus.PAUSED,
            resume_at=now - timedelta(seconds=1),
            created_at=now - timedelta(minutes=2),
        ),
        _continuation(
            "future",
            status=RunStatus.WAITING,
            resume_at=now + timedelta(seconds=1),
            created_at=now - timedelta(minutes=1),
        ),
        _continuation(
            "no-deadline",
            status=RunStatus.WAITING,
            resume_at=None,
            created_at=now,
        ),
        _continuation(
            "terminal",
            status=RunStatus.COMPLETED,
            resume_at=now - timedelta(minutes=1),
            created_at=now,
        ),
    )
    for row in rows:
        await store.create(row)

    # PAUSED is the canonical HITL state. `resume_durable_graph` deliberately
    # refuses it until an answer/timeout decision has been persisted, so the
    # clock-driven wakeup query must not turn a stale deadline into a human
    # answer. Ordinary timed waits are WAITING.
    assert await store.list_due_run_ids(now=now, limit=10) == ["due-waiting"]
    assert await store.list_due_run_ids(now=now, limit=1) == ["due-waiting"]


@pytest.mark.asyncio
async def test_in_memory_continuation_store_queries_only_due_resumable_rows() -> None:
    await _assert_due_query(InMemoryGraphContinuationStore())


@pytest.mark.asyncio
async def test_sqlite_continuation_store_queries_resume_at_index(tmp_path: Path) -> None:
    async with aiosqlite.connect(tmp_path / "continuations.db") as conn:
        store = SqliteGraphContinuationStore(conn)
        await store.ensure_schema()
        await _assert_due_query(store)
