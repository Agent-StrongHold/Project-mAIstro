"""Recurring enable/disable/max_runs admission is the same on every backend (#46).

`test_admission.py` pins these semantics on the in-memory stores only, and
`test_pg_admission.py` covers only the concurrent-claim race. The cursors a
tick leaves behind — `runs_so_far`, `last_run_id`, `last_fired_at`,
`next_due_at`, `enabled` — are written by three different `record_fire`
implementations, so the same scenario runs here against each, wired through
`wire_execution_spine` exactly as a deployment wires them, and must leave the
same rows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from maistro.graph.definitions import GraphTemplate, Node
from maistro.runs.store import RunStore
from maistro.runs.wiring import wire_execution_spine
from maistro.scheduling.admission import ScheduleRunAdmitter
from maistro.scheduling.model import Schedule
from maistro.scheduling.store import ScheduleStore

NOON = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
WORKSPACE = "issue-46-parity"
TEMPLATE_ID = "issue-46-template"
SCHEDULE_ID = "issue-46-schedule"


@dataclass
class Backend:
    admitter: ScheduleRunAdmitter
    runs: RunStore
    schedules: ScheduleStore
    project_id: str


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def backend(
    request: pytest.FixtureRequest, tmp_path: Path, pg_pool: Any
) -> AsyncIterator[Backend]:
    conns: list[aiosqlite.Connection] = []
    conn: Any = None
    schedule_conn: Any = None
    pool: Any = None
    if request.param == "sqlite":
        # Two connections on one file, as `Container.schedule_conn` opens them.
        db = str(tmp_path / "parity.db")
        conn = await aiosqlite.connect(db)
        schedule_conn = await aiosqlite.connect(db)
        conns = [conn, schedule_conn]
    elif request.param == "postgres":
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        pool = pg_pool
    try:
        (
            projects,
            runs,
            _admitter,
            templates,
            schedules,
            _continuations,
        ) = await wire_execution_spine(
            conn, workspace_id=WORKSPACE, pg_pool=pool, schedule_conn=schedule_conn
        )
        root = await projects.root_for_workspace(WORKSPACE)
        project = await projects.create(
            workspace_id=WORKSPACE, parent_project_id=root.project_id, name="Parity"
        )
        await templates.put(
            GraphTemplate(
                template_id=TEMPLATE_ID,
                workspace_id=WORKSPACE,
                version=1,
                name="parity",
                nodes=[Node(node_id="n1", node_type="agent", name="a")],
            )
        )
        yield Backend(
            ScheduleRunAdmitter(runs, templates, schedules), runs, schedules, project.project_id
        )
    finally:
        for c in conns:
            await c.close()


async def _tick(backend: Backend, now: datetime) -> list[str]:
    """What the canonical tick does: admit whatever `due()` selects."""
    run_ids: list[str] = []
    for schedule in await backend.schedules.due(now=now):
        admission = await backend.admitter.admit_due(schedule, now=now)
        run_ids.extend(admission.run_ids)
    return run_ids


async def _row(backend: Backend) -> dict[str, object]:
    """The cursor state, with `last_run_id` resolved to the occurrence it names.

    Run ids are minted per backend, so the id itself cannot match across them;
    the occurrence the pointer resolves to in that backend's own run store can.
    """
    stored = await backend.schedules.get(SCHEDULE_ID)
    assert stored is not None
    last_run_for: str | None = None
    if stored.last_run_id is not None:
        run = await backend.runs.get_run(stored.last_run_id)
        assert run is not None
        last_run_for = run.provenance["scheduled_for"]
    return {
        "enabled": stored.enabled,
        "runs_so_far": stored.runs_so_far,
        "last_run_for": last_run_for,
        "last_fired_at": stored.last_fired_at,
        "next_due_at": stored.next_due_at,
    }


async def _occurrence_run_ids(backend: Backend, *moments: datetime) -> list[str | None]:
    found = []
    for moment in moments:
        run = await backend.runs.get_run_for_occurrence(SCHEDULE_ID, moment.isoformat())
        found.append(run.run_id if run is not None else None)
    return found


async def test_enable_disable_and_max_runs_leave_identical_rows(backend: Backend) -> None:
    schedule = await backend.schedules.put(
        Schedule(
            schedule_id=SCHEDULE_ID,
            workspace_id=WORKSPACE,
            project_id=backend.project_id,
            name="hourly",
            cron="0 * * * *",
            graph_template_id=TEMPLATE_ID,
            max_runs=2,
            created_at=NOON - timedelta(days=30),
            last_fired_at=NOON - timedelta(hours=1),
        )
    )
    one_pm = NOON + timedelta(hours=1)

    first = await _tick(backend, NOON)
    assert len(first) == 1
    assert await _row(backend) == {
        "enabled": True,
        "runs_so_far": 1,
        "last_run_for": NOON.isoformat(),
        "last_fired_at": NOON,
        "next_due_at": one_pm,
    }

    # Disabling is a definition write: it must keep the cursors, and neither
    # `due()` nor the admitter handed the disabled row may fire it.
    stored = await backend.schedules.get(SCHEDULE_ID)
    assert stored is not None
    disabled = await backend.schedules.put(schedule.model_copy(update={"enabled": False}))
    assert disabled.runs_so_far == 1 and disabled.last_run_id == stored.last_run_id
    assert await backend.schedules.due(now=one_pm) == []
    assert (await backend.admitter.admit_due(disabled, now=one_pm)).run_ids == ()
    assert await _row(backend) == {
        "enabled": False,
        "runs_so_far": 1,
        "last_run_for": NOON.isoformat(),
        "last_fired_at": NOON,
        "next_due_at": one_pm,
    }

    # Re-enabled, it fires the owed occurrence; that reaches max_runs, so the
    # same write disables it and clears the due cursor.
    await backend.schedules.put(schedule.model_copy(update={"enabled": True}))
    second = await _tick(backend, one_pm)
    assert len(second) == 1
    assert await _row(backend) == {
        "enabled": False,
        "runs_so_far": 2,
        "last_run_for": one_pm.isoformat(),
        "last_fired_at": one_pm,
        "next_due_at": None,
    }

    two_pm = NOON + timedelta(hours=2)
    assert await backend.schedules.due(now=two_pm) == []
    assert await _tick(backend, two_pm) == []
    assert await _occurrence_run_ids(backend, NOON, one_pm, two_pm) == [*first, *second, None]


async def test_a_future_schedule_records_its_cursor_and_leaves_due(backend: Backend) -> None:
    tick = NOON + timedelta(seconds=30)
    await backend.schedules.put(
        Schedule(
            schedule_id=SCHEDULE_ID,
            workspace_id=WORKSPACE,
            project_id=backend.project_id,
            name="hourly",
            cron="0 * * * *",
            graph_template_id=TEMPLATE_ID,
            created_at=NOON + timedelta(seconds=1),
        )
    )

    assert await _tick(backend, tick) == []
    assert await _row(backend) == {
        "enabled": True,
        "runs_so_far": 0,
        "last_run_for": None,
        "last_fired_at": None,
        "next_due_at": NOON + timedelta(hours=1),
    }
    assert await backend.schedules.due(now=NOON + timedelta(minutes=59)) == []
    assert [s.schedule_id for s in await backend.schedules.due(now=NOON + timedelta(hours=1))] == [
        SCHEDULE_ID
    ]
