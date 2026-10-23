"""Process-loss and overlap-policy evidence for duplicate winner linkage (#1059)."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from maistro.graph.definitions import GraphTemplate, Node
from maistro.graph.templates import InMemoryGraphTemplateStore
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus
from maistro.scheduling.admission import ScheduleRunAdmitter
from maistro.scheduling.engine import SkipReason
from maistro.scheduling.model import OverlapPolicy, Schedule

pytestmark = [pytest.mark.contract("behavioral")]

NOON = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
POLICIES = (OverlapPolicy.SKIP, OverlapPolicy.BUFFER_ONE, OverlapPolicy.CANCEL_OTHER)

# Run this in a separate interpreter and database connection. The overridden
# cursor write is a checkpoint, not an exception: the parent kills the process
# while it is suspended here, so no finally/compensation handler can run.
_CRASH_WORKER = r"""
import asyncio
import json
import sys

import asyncpg

from maistro.graph.definitions import GraphTemplate
from maistro.graph.templates import InMemoryGraphTemplateStore
from maistro.persistence import _register_json_codecs
from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.runs.pg_store import PgRunStore
from maistro.scheduling.admission import ScheduleRunAdmitter
from maistro.scheduling.model import Schedule
from maistro.scheduling.pg_store import PgScheduleStore
from maistro.testing.postgres import postgres_dsn


async def main():
    request = json.loads(sys.stdin.read())
    pool = await asyncpg.create_pool(
        postgres_dsn(), min_size=1, max_size=2, init=_register_json_codecs
    )
    projects = PgProjectScopeStore(pool)
    runs = PgRunStore(pool, project_store=projects)
    schedule = Schedule.model_validate(request["schedule"])
    templates = InMemoryGraphTemplateStore()
    await templates.put(GraphTemplate.model_validate(request["template"]))

    class StopBeforeCursor(PgScheduleStore):
        async def record_fire(self, schedule_id, **kwargs):
            winner = await runs.get_run_for_occurrence(
                schedule_id, kwargs["fired_at"].isoformat()
            )
            assert winner is not None
            print("ADMITTED:" + winner.run_id, flush=True)
            await asyncio.Event().wait()
            raise AssertionError("the killed worker must never resume")

    try:
        from datetime import datetime
        await ScheduleRunAdmitter(runs, templates, StopBeforeCursor(pool)).admit_due(
            schedule, now=datetime.fromisoformat(request["now"])
        )
    finally:
        await pool.close()


asyncio.run(main())
"""


async def _definitions(
    schedules: Any, workspace: str, project_id: str, policy: OverlapPolicy
) -> tuple[InMemoryGraphTemplateStore, GraphTemplate, Schedule]:
    templates = InMemoryGraphTemplateStore()
    template = await templates.put(
        GraphTemplate(
            workspace_id=workspace,
            version=1,
            name="winner linkage crash test",
            nodes=[Node(node_id="n1", node_type="agent", name="a")],
        )
    )
    schedule = await schedules.put(
        Schedule(
            workspace_id=workspace,
            project_id=project_id,
            name="hourly",
            cron="0 * * * *",
            graph_template_id=template.template_id,
            overlap_policy=policy,
            created_at=NOON - timedelta(days=1),
            last_fired_at=NOON - timedelta(hours=1),
        )
    )
    return templates, template, schedule


async def _recover_and_check_policy(
    runs: Any,
    schedules: Any,
    templates: InMemoryGraphTemplateStore,
    schedule: Schedule,
    winner: str,
) -> None:
    ticker = ScheduleRunAdmitter(runs, templates, schedules)
    recovered = await ticker.admit_due(schedule, now=NOON)
    assert recovered.run_ids == ()
    assert recovered.already_fired == (NOON,)
    linked = await schedules.get(schedule.schedule_id)
    assert linked is not None
    assert linked.last_fired_at == NOON
    assert linked.last_run_id == winner
    in_flight = await runs.get_run(linked.last_run_id)
    assert in_flight is not None and in_flight.status is RunStatus.QUEUED

    later = await ticker.admit_due(
        linked,
        now=NOON + timedelta(hours=1),
        active_run=in_flight.status not in TERMINAL_RUN_STATUSES,
    )
    if schedule.overlap_policy is OverlapPolicy.CANCEL_OTHER:
        # The admitter signals cancellation; the execution caller owns it.
        assert later.cancel_active_run is True
        assert len(later.run_ids) == 1 and later.run_ids[0] != winner
        return

    assert later.run_ids == ()
    expected = (
        SkipReason.BUFFERED
        if schedule.overlap_policy is OverlapPolicy.BUFFER_ONE
        else SkipReason.OVERLAP
    )
    assert [skip.reason for skip in later.skipped] == [expected]
    final = await schedules.get(schedule.schedule_id)
    assert final is not None and final.last_run_id == winner
    if schedule.overlap_policy is OverlapPolicy.BUFFER_ONE:
        assert final.last_fired_at == NOON
    queued = await runs.list_by_status(RunStatus.QUEUED, project_id=schedule.project_id)
    assert [run.run_id for run in queued] == [winner]


async def _kill_after_admission(template: GraphTemplate, schedule: Schedule) -> str:
    worker = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        _CRASH_WORKER,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert worker.stdin is not None and worker.stdout is not None
    try:
        worker.stdin.write(
            json.dumps(
                {
                    "template": template.model_dump(mode="json"),
                    "schedule": schedule.model_dump(mode="json"),
                    "now": NOON.isoformat(),
                }
            ).encode()
        )
        await worker.stdin.drain()
        worker.stdin.close()
        async with asyncio.timeout(45):
            while True:
                line = await worker.stdout.readline()
                assert line, "worker exited before reaching the post-admission checkpoint"
                if line.startswith(b"ADMITTED:"):
                    winner = line.decode().strip().split(":", 1)[1]
                    break
        worker.kill()
        await asyncio.wait_for(worker.communicate(), timeout=15)
        assert worker.returncode == -signal.SIGKILL
        return winner
    finally:
        if worker.returncode is None:
            worker.kill()
            await asyncio.wait_for(worker.communicate(), timeout=15)


async def _pg_context(pg_pool: Any, policy: OverlapPolicy) -> tuple[Any, ...]:
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.pg_store import PgRunStore
    from maistro.scheduling.pg_store import PgScheduleStore

    workspace = f"winner-crash-{uuid4().hex}"
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(workspace)
    schedules = PgScheduleStore(pg_pool)
    templates, template, schedule = await _definitions(
        schedules, workspace, root.project_id, policy
    )
    return PgRunStore(pg_pool, project_store=projects), schedules, templates, template, schedule


@pytest.mark.skipif(os.name != "posix", reason="this regression requires SIGKILL")
@pytest.mark.parametrize("policy", POLICIES)
async def test_pg_worker_killed_between_admission_and_record_fire(
    pg_pool: Any, policy: OverlapPolicy
) -> None:
    if pg_pool is None:
        pytest.skip("PostgreSQL test DSN is not configured")
    runs, schedules, templates, template, schedule = await _pg_context(pg_pool, policy)
    winner = await _kill_after_admission(template, schedule)
    before = await schedules.get(schedule.schedule_id)
    assert before is not None
    assert before.last_run_id is None
    assert before.last_fired_at == NOON - timedelta(hours=1)
    assert await runs.get_run_for_occurrence(schedule.schedule_id, NOON.isoformat()) is not None
    await _recover_and_check_policy(runs, schedules, templates, before, winner)


async def test_pg_replicas_converge_on_one_occurrence_and_schedule_pointer(pg_pool: Any) -> None:
    if pg_pool is None:
        pytest.skip("PostgreSQL test DSN is not configured")
    import asyncpg

    from maistro.persistence import _register_json_codecs
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.pg_store import PgRunStore
    from maistro.scheduling.pg_store import PgScheduleStore
    from maistro.testing.postgres import postgres_dsn

    runs, schedules, templates, _template, schedule = await _pg_context(pg_pool, OverlapPolicy.SKIP)
    other_pool = await asyncpg.create_pool(
        postgres_dsn(), min_size=1, max_size=2, init=_register_json_codecs
    )
    try:
        other_runs = PgRunStore(other_pool, project_store=PgProjectScopeStore(other_pool))
        other_schedules = PgScheduleStore(other_pool)
        results = await asyncio.gather(
            ScheduleRunAdmitter(runs, templates, schedules).admit_due(schedule, now=NOON),
            ScheduleRunAdmitter(other_runs, templates, other_schedules).admit_due(
                schedule, now=NOON
            ),
        )
        admitted = [run_id for result in results for run_id in result.run_ids]
        assert len(admitted) == 1
        assert sum(len(result.already_fired) for result in results) == 1
        for replica_runs, replica_schedules in (
            (runs, schedules),
            (other_runs, other_schedules),
        ):
            winner = await replica_runs.get_run_for_occurrence(
                schedule.schedule_id, NOON.isoformat()
            )
            recorded = await replica_schedules.get(schedule.schedule_id)
            assert winner is not None and winner.run_id == admitted[0]
            assert recorded is not None
            assert recorded.last_run_id == admitted[0]
            assert recorded.last_fired_at == NOON
            assert recorded.runs_so_far == 1
    finally:
        await other_pool.close()
