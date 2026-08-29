"""One contract, three continuation backends (#44).

The continuation is the half of a durable graph run the canonical spine does
not hold, so it is the half a restart loses if any one backend disagrees with
the others. These run the same suite against all three, because the failures
that matter here are the ones a single-backend test cannot see: a fence that
is a read-then-write in one store and a SQL predicate in another, a collision
that raises in memory and silently overwrites on disk.

The error arms are the point. A continuation store that quietly accepts a
stale version is how two workers both believe they advanced the same Run, and
that is precisely what `version` exists to prevent -- so each store is asked to
refuse, not merely to accept.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import aiosqlite
import pytest

from maistro.graph.durable_runs.continuation import (
    GraphContinuation,
    GraphContinuationStore,
    InMemoryGraphContinuationStore,
    SqliteGraphContinuationStore,
)
from maistro.graph.execution_state import GraphExecutionState
from maistro.runs.model import RunStatus

BACKENDS = ["memory", "sqlite", "postgres"]


@pytest.fixture(params=BACKENDS)
async def store(
    request: pytest.FixtureRequest, tmp_path: Any, pg_pool: Any
) -> AsyncIterator[GraphContinuationStore]:
    """The same store contract, however it is spelled.

    `pg_pool` is requested unconditionally and yields `None` when no server is
    configured, so only the PostgreSQL parametrization skips.
    """
    if request.param == "memory":
        yield InMemoryGraphContinuationStore()
        return
    if request.param == "sqlite":
        async with aiosqlite.connect(tmp_path / "continuations.db") as conn:
            sqlite_store = SqliteGraphContinuationStore(conn)
            await sqlite_store.ensure_schema()
            yield sqlite_store
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.graph.durable_runs.pg_continuation import PgGraphContinuationStore

    yield PgGraphContinuationStore(pg_pool)


def _continuation(
    run_id: str,
    *,
    version: int = 1,
    status: RunStatus = RunStatus.RUNNING,
    project_id: str = "proj-1",
    minutes: int = 0,
) -> GraphContinuation:
    return GraphContinuation(
        run_id=run_id,
        graph_state=GraphExecutionState(run_id=run_id, active_node_ids=("step",)),
        version=version,
        status=status,
        project_id=project_id,
        created_at=datetime(2026, 8, 29, tzinfo=UTC) + timedelta(minutes=minutes),
    )


async def test_a_written_continuation_reads_back_whole(store: GraphContinuationStore) -> None:
    written = await store.create(_continuation("run-1"))

    read = await store.get("run-1")

    assert read is not None
    assert read.run_id == written.run_id
    assert read.graph_state.active_node_ids == ("step",)
    assert read.version == 1
    assert read.status is RunStatus.RUNNING


async def test_an_unknown_run_is_absent(store: GraphContinuationStore) -> None:
    assert await store.get("no-such-run") is None


async def test_a_second_create_for_one_run_is_refused(store: GraphContinuationStore) -> None:
    """Two creates mean two traversals believe they own the same Run."""
    await store.create(_continuation("run-1"))

    with pytest.raises(ValueError, match="collision"):
        await store.create(_continuation("run-1"))


async def test_a_newer_version_advances_the_continuation(store: GraphContinuationStore) -> None:
    await store.create(_continuation("run-1"))

    await store.update(_continuation("run-1", version=2, status=RunStatus.PAUSED))

    read = await store.get("run-1")
    assert read is not None
    assert read.version == 2
    assert read.status is RunStatus.PAUSED


async def test_updating_a_run_that_was_never_created_is_a_key_error(
    store: GraphContinuationStore,
) -> None:
    """Distinguished from a stale write deliberately: one is a missing Run and
    the other is a lost race, and a caller that cannot tell them apart will
    retry the wrong one."""
    with pytest.raises(KeyError):
        await store.update(_continuation("run-1", version=2))


@pytest.mark.parametrize("incoming", [1, 0])
async def test_a_version_that_did_not_advance_is_refused(
    store: GraphContinuationStore, incoming: int
) -> None:
    """The fence. Equal is refused as well as older: a writer that read version
    1, worked, and wrote 1 back has not advanced anything, and letting it
    through would silently discard whatever the other writer committed."""
    await store.create(_continuation("run-1", version=1))

    with pytest.raises(ValueError, match="version regression"):
        await store.update(_continuation("run-1", version=incoming))

    read = await store.get("run-1")
    assert read is not None
    assert read.version == 1


async def test_the_listings_agree_across_backends(store: GraphContinuationStore) -> None:
    await store.create(_continuation("run-a", status=RunStatus.PAUSED, minutes=0))
    await store.create(
        _continuation("run-b", status=RunStatus.PAUSED, project_id="proj-2", minutes=1)
    )
    await store.create(_continuation("run-c", status=RunStatus.RUNNING, minutes=2))

    assert await store.list_run_ids_by_status(RunStatus.PAUSED) == ["run-a", "run-b"]
    assert await store.list_run_ids_by_status(RunStatus.PAUSED, project_id="proj-2") == ["run-b"]
    assert await store.list_run_ids_by_status(RunStatus.PAUSED, limit=1) == ["run-a"]
    assert await store.list_run_ids_by_status(RunStatus.COMPLETED) == []
    assert await store.list_run_ids_for_project("proj-1") == ["run-c", "run-a"]
    assert await store.list_run_ids_for_project("proj-1", limit=1) == ["run-c"]
    assert await store.list_run_ids_for_project("proj-3") == []
