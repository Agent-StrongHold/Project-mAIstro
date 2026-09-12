"""PostgreSQL proofs for the schedule cursor and the occurrence claim (#1059, #1199).

The same properties `tests/scheduling/test_store.py` and
`tests/runs/test_archive_conformance.py` assert on every backend, stated here
against `PgScheduleStore` and `PgRunStore` alone so that ci.yml's pg17/pg18
jobs -- which collect `tests/persistence` and not those directories -- run
them on both server versions. Every test skips without `MAISTRO_TEST_PG_DSN`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from maistro.graph import Graph, Node
from maistro.runs.model import RunStatus
from maistro.scheduling.model import Schedule

pytestmark = [pytest.mark.contract("behavioral")]

NOON = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
COLD = NOW - timedelta(days=120)
NINETY_DAYS = timedelta(days=90)


def _schedule(**overrides: object) -> Schedule:
    defaults: dict[str, object] = {
        "workspace_id": "w-pg-claims",
        "project_id": "p-pg-claims",
        "cron": "0 * * * *",
        "graph_template_id": "hourly",
    }
    return Schedule(**{**defaults, **overrides})  # type: ignore[arg-type]


def _store(pg_pool: Any) -> Any:
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.scheduling.pg_store import PgScheduleStore

    return PgScheduleStore(pg_pool)


async def test_pg_a_stale_write_cannot_move_the_cursor_backward(pg_pool: Any) -> None:
    """Two replicas with different horizons: the one that recorded a newer
    occurrence wins under the row lock, and the delayed one moves nothing
    backward -- cursor, pointer, due time, or count (#1059 review)."""
    store = _store(pg_pool)
    schedule = await store.put(_schedule())
    await store.record_fire(
        schedule.schedule_id,
        fired_at=NOON + timedelta(hours=1),
        run_id="run-newer",
        next_due_at=NOON + timedelta(hours=2),
        fires=0,
        fired=[NOON + timedelta(hours=1)],
    )

    late = await store.record_fire(
        schedule.schedule_id,
        fired_at=NOON,
        run_id="run-older",
        next_due_at=NOON + timedelta(hours=1),
        fires=0,
        fired=[NOON],
    )

    assert late is not None
    assert late.last_fired_at == NOON + timedelta(hours=1)
    assert late.last_run_id == "run-newer"
    assert late.next_due_at == NOON + timedelta(hours=2)
    assert late.runs_so_far == 1


async def test_pg_two_pools_recording_one_occurrence_count_it_once(pg_pool: Any) -> None:
    """The ticker that won the claim and the ticker it refused, on separate
    connection pools, both record the same occurrence; `FOR UPDATE` orders
    the writes and `_advance` counts the occurrence against the cursor it
    finds, so the count moves once and `max_runs=1` disables the schedule."""
    import asyncpg

    from maistro.persistence import _register_json_codecs
    from maistro.scheduling.pg_store import PgScheduleStore
    from maistro.testing.postgres import postgres_dsn

    store = _store(pg_pool)
    schedule = await store.put(_schedule(max_runs=1))
    other_pool = await asyncpg.create_pool(
        postgres_dsn(), min_size=1, max_size=2, init=_register_json_codecs
    )
    try:
        other = PgScheduleStore(other_pool)
        await asyncio.gather(
            *(
                replica.record_fire(
                    schedule.schedule_id,
                    fired_at=NOON,
                    run_id="run-winner",
                    next_due_at=NOON + timedelta(hours=1),
                    fires=0,
                    fired=[NOON],
                )
                for replica in (store, other, store, other)
            )
        )
    finally:
        await other_pool.close()

    final = await store.get(schedule.schedule_id)
    assert final is not None
    assert final.runs_so_far == 1
    assert final.enabled is False and final.next_due_at is None
    assert final.last_run_id == "run-winner"


async def test_pg_put_keeps_the_cursors_a_concurrent_record_fire_wrote(pg_pool: Any) -> None:
    """A definition refresh racing a fire: `put` merges under the same row
    lock `record_fire` takes, so whichever lands second, the fire survives
    and the definition is the caller's (Codex, #1199)."""
    store = _store(pg_pool)
    schedule = await store.put(_schedule(name="before"))

    await asyncio.gather(
        store.record_fire(
            schedule.schedule_id,
            fired_at=NOON,
            run_id="run-1",
            next_due_at=NOON + timedelta(hours=1),
        ),
        store.put(schedule.model_copy(update={"name": "after"})),
    )

    final = await store.get(schedule.schedule_id)
    assert final is not None
    assert final.name == "after"
    assert final.runs_so_far == 1
    assert final.last_run_id == "run-1"
    assert final.last_fired_at == NOON
    assert final.next_due_at == NOON + timedelta(hours=1)


async def test_pg_a_due_cursor_write_counts_no_fire_by_default(pg_pool: Any) -> None:
    store = _store(pg_pool)
    schedule = await store.put(_schedule(max_runs=1))
    recorded = await store.record_fire(
        schedule.schedule_id, fired_at=None, run_id=None, next_due_at=NOON + timedelta(hours=1)
    )
    assert recorded is not None
    assert recorded.runs_so_far == 0 and recorded.enabled is True
    assert recorded.next_due_at == NOON + timedelta(hours=1)
    assert recorded.last_fired_at is None


async def test_pg_an_archived_winner_still_holds_its_occurrence_claim(
    pg_pool: Any, tmp_path: Any
) -> None:
    """Migration 034 promotes the claim out of the payload: after the archive
    tier NULLs a cold winner's payload, a second Run for the occurrence is
    still refused and the winner is still the answer to
    `get_run_for_occurrence`, read through the tombstone (#1059 review)."""
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.archive.filesystem import FilesystemArchiveStore
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.pg_store import PgRunStore
    from maistro.runs.sources import ADMISSION_SOURCE, SCHEDULE_SOURCE
    from maistro.runs.store import DuplicateOccurrence

    workspace = "w-pg-archived-claim"
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace, parent_project_id=root.project_id, name="Cold"
    )
    store = PgRunStore(
        pg_pool, project_store=projects, archive_store=FilesystemArchiveStore(str(tmp_path))
    )
    graph = Graph(
        workspace_id=workspace,
        project_id=project.project_id,
        name="archived claim",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    schedule_id = f"sched-archived-{uuid4().hex}"
    provenance = {
        ADMISSION_SOURCE: SCHEDULE_SOURCE,
        "schedule_id": schedule_id,
        "scheduled_for": COLD.isoformat(),
    }
    winner = await store.create_run(graph, provenance=provenance)
    await store.transition_run(winner.run_id, RunStatus.QUEUED)
    await store.transition_run(winner.run_id, RunStatus.RUNNING)
    await store.transition_run(winner.run_id, RunStatus.COMPLETED, at=COLD)

    assert await store.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS) == 1
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT payload, schedule_id, scheduled_for FROM canonical_runs WHERE run_id = $1",
            winner.run_id,
        )
    assert row is not None and row["payload"] is None, "the tombstone has no payload"
    assert (row["schedule_id"], row["scheduled_for"]) == (schedule_id, COLD.isoformat())

    with pytest.raises(DuplicateOccurrence):
        await store.create_run(graph, provenance=dict(provenance))
    found = await store.get_run_for_occurrence(schedule_id, COLD.isoformat())
    assert found is not None and found.run_id == winner.run_id
