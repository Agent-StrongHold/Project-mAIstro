"""The real Hive tick reads durable due state on both supported SQL backends (#1199)."""

from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.container import create_container
from maistro.graph.definitions import GraphTemplate, Node
from maistro.runs.model import RunStatus
from maistro.scheduling import Schedule
from maistro.scheduling.pg_store import PgScheduleStore
from maistro.scheduling.store import SqliteScheduleStore
from maistro.testing.postgres import postgres_dsn
from maistro.types.config import AgentConfig

NOW = datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
NOON = NOW.replace(minute=0)
ROOT = pathlib.Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def postgres_database() -> Iterator[str]:
    """Own a scratch database, never truncate the configured database's data."""
    from sqlalchemy.engine import make_url

    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            raise RuntimeError("MAISTRO_REQUIRE_PG_LEGS needs MAISTRO_TEST_PG_DSN")
        pytest.skip("MAISTRO_TEST_PG_DSN is unset")
    import psycopg

    name = f"scheduler_tick_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    url = make_url(dsn).set(database=name).render_as_string(hide_password=False)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env={**os.environ, "DATABASE_URL": url},
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        yield url
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(params=["sqlite", "postgres"])
def database_url(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> str:
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'schedules.db'}"
    return str(request.getfixturevalue("postgres_database"))


@pytest.fixture
async def configured(database_url: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    import stores
    from services import scheduler

    from maistro.capabilities.effect_context import default_effect_context

    class Clock:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return NOW

    monkeypatch.setattr(scheduler, "datetime", Clock)
    # These are the only legacy rows this isolated tick is allowed to see.
    monkeypatch.setattr(stores.schedules, "_data", {})
    container = await create_container(
        AgentConfig(
            router_api_key="test-key", workspace_id="tick-parity", database_url=database_url
        )
    )
    monkeypatch.setattr(
        scheduler._ScheduleRunner, "_canonical_container", staticmethod(lambda: container)
    )
    try:
        if database_url.startswith("postgres"):
            assert isinstance(container.schedule_store, PgScheduleStore)
            # Only our freshly created database, never the configured test server's DB.
            await container.pg_pool.execute(
                "TRUNCATE canonical_projects, schedules, graph_templates RESTART IDENTITY CASCADE"
            )
        else:
            assert isinstance(container.schedule_store, SqliteScheduleStore)
        root = await container.project_scope_store.create_root("tick-parity")
        await container.template_store.put(
            GraphTemplate(
                template_id="tick-template",
                workspace_id="tick-parity",
                version=1,
                name="canonical template",
                nodes=[
                    Node(
                        node_id="only", node_type="transform.alias_keys", parameters={"mapping": {}}
                    )
                ],
                metadata={"entry_node": "only"},
            )
        )
        await container.schedule_store.put(
            Schedule(
                schedule_id="tick-schedule",
                workspace_id="tick-parity",
                project_id=root.project_id,
                name="canonical schedule",
                cron="0 * * * *",
                graph_template_id="tick-template",
                actor_principal_id="tick-actor",
                created_at=NOON - timedelta(days=1),
                last_fired_at=NOON - timedelta(hours=1),
            )
        )
        yield container
    finally:
        await container.aclose()
        default_effect_context.cache_clear()


async def runs(container: Any) -> list[Any]:
    result = []
    for status in RunStatus:
        result.extend(await container.run_store.list_by_status(status, limit=100))
    return result


async def hive_row(container: Any, **changes: Any) -> Any:
    import stores
    from models.schemas import Schedule as HiveSchedule

    canonical = await container.schedule_store.get("tick-schedule")
    row = HiveSchedule(
        id=canonical.schedule_id,
        user_id="tick-actor",
        workspace_id=canonical.workspace_id,
        project_id=canonical.project_id,
        name=canonical.name,
        description="",
        cron_expression=canonical.cron,
        mission_template_id=canonical.graph_template_id,
        max_runs=canonical.max_runs,
        created_at=canonical.created_at,
        updated_at=canonical.created_at,
        last_run=canonical.last_fired_at,
    ).model_copy(update=changes)
    stores.schedules._data[row.id] = row
    return row


async def test_tick_executes_canonical_only_schedule_once(configured: Any) -> None:
    from services.scheduler import _ScheduleRunner

    await _ScheduleRunner()._tick()
    [run] = await runs(configured)
    assert run.status is RunStatus.COMPLETED
    assert run.provenance["schedule_id"] == "tick-schedule"
    assert run.actor_principal_id == "tick-actor"
    recorded = await configured.schedule_store.get("tick-schedule")
    assert recorded.runs_so_far == 1 and recorded.last_run_id == run.run_id
    assert recorded.next_due_at == NOON + timedelta(hours=1)
    [node] = await configured.run_store.list_node_runs(run.run_id)
    assert len(await configured.run_store.list_attempts(node.node_run_id)) == 1
    await _ScheduleRunner()._tick()
    assert [item.run_id for item in await runs(configured)] == [run.run_id]
    assert len(await configured.run_store.list_attempts(node.node_run_id)) == 1


async def test_no_fire_persists_next_due_and_stops_selection(configured: Any) -> None:
    from services.scheduler import _ScheduleRunner

    original = await configured.schedule_store.get("tick-schedule")
    await configured.schedule_store.put(original.model_copy(update={"cron": "0 0 1 1 *"}))
    assert len(await configured.schedule_store.due(now=NOW)) == 1
    await _ScheduleRunner()._tick()
    recorded = await configured.schedule_store.get("tick-schedule")
    assert recorded.next_due_at == datetime(2027, 1, 1, tzinfo=UTC)
    assert recorded.last_fired_at == original.last_fired_at
    assert recorded.runs_so_far == 0 and recorded.last_run_id is None
    assert await configured.schedule_store.due(now=NOW) == []
    await _ScheduleRunner()._tick()
    assert await runs(configured) == []


async def test_due_failure_still_consumes_existing_queued_run(
    configured: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from services.scheduler import _ScheduleRunner

    schedule = await configured.schedule_store.get("tick-schedule")
    admitted = await configured.schedule_admitter.admit_due(schedule, now=NOW)
    [run_id] = admitted.run_ids
    assert (await configured.run_store.get_run(run_id)).status is RunStatus.QUEUED

    async def unavailable(**kwargs: Any) -> Any:
        raise RuntimeError("due read unavailable")

    monkeypatch.setattr(configured.schedule_store, "due", unavailable)
    await _ScheduleRunner()._tick()
    assert (await configured.run_store.get_run(run_id)).status is RunStatus.COMPLETED
    assert "due read unavailable" in caplog.text


async def test_audit_uses_canonical_definition_not_drifted_hive_row(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from routes import audit
    from services.scheduler import _ScheduleRunner

    await hive_row(configured, name="stale Hive name", mission_template_id="wrong-template")
    entries: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        audit,
        "log_audit",
        lambda action, actor, **kwargs: entries.append((action, kwargs["detail"])),
    )
    await _ScheduleRunner()._tick()
    assert [detail["name"] for action, detail in entries if action == "schedule_fire"] == [
        "canonical schedule"
    ]
    assert [detail["dag_id"] for action, detail in entries if action == "schedule_run"] == [
        "tick-template"
    ]
    [run] = await runs(configured)
    assert run.graph.materialize().source_template.template_id == "tick-template"


@pytest.mark.parametrize("change", ["delete", "disable", "future", "future_cursor"])
async def test_stale_due_snapshot_cannot_override_locked_edit(
    configured: Any, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from services.scheduler import _ScheduleRunner, definition_lock

    selected = asyncio.Event()
    due = configured.schedule_store.due

    async def snapshot(**kwargs: Any) -> Any:
        result = await due(**kwargs)
        selected.set()
        return result

    monkeypatch.setattr(configured.schedule_store, "due", snapshot)
    admitted: list[str] = []
    admit = configured.schedule_admitter.admit_due

    async def record_admission(schedule: Schedule, **kwargs: Any) -> Any:
        admitted.append(schedule.schedule_id)
        return await admit(schedule, **kwargs)

    monkeypatch.setattr(configured.schedule_admitter, "admit_due", record_admission)
    async with definition_lock("tick-schedule"):
        tick = asyncio.create_task(_ScheduleRunner()._tick())
        await asyncio.wait_for(selected.wait(), timeout=5)
        if change == "delete":
            await configured.schedule_store.delete("tick-schedule")
        elif change == "future_cursor":
            await configured.schedule_store.record_fire(
                "tick-schedule",
                fired_at=None,
                run_id=None,
                next_due_at=NOON + timedelta(hours=1),
                fires=0,
            )
        else:
            current = await configured.schedule_store.get("tick-schedule")
            updates = {"enabled": False} if change == "disable" else {"cron": "0 0 1 1 *"}
            await configured.schedule_store.put(current.model_copy(update=updates))
    await asyncio.wait_for(tick, timeout=5)
    assert await runs(configured) == []
    if change == "future_cursor":
        assert admitted == []
    if change == "delete":
        assert await configured.schedule_store.get("tick-schedule") is None


async def test_tick_and_manual_fire_share_definition_lock_and_keep_both_counts(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.scheduler import _ScheduleRunner, fire_now

    await hive_row(configured)
    entered, release, manual_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
    admit = configured.schedule_admitter.admit_due

    async def paused(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("manual"):
            manual_entered.set()
        else:
            entered.set()
            await release.wait()
        return await admit(*args, **kwargs)

    monkeypatch.setattr(configured.schedule_admitter, "admit_due", paused)
    tick = asyncio.create_task(_ScheduleRunner()._tick())
    await asyncio.wait_for(entered.wait(), timeout=5)
    manual = asyncio.create_task(fire_now("tick-schedule", fire_id="manual-once"))
    try:
        from services.scheduler import _definition_locks

        assert _definition_locks["tick-schedule"].locked()
        # Two turns let the manual coroutine reach the shared lock without a timing bound.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not manual_entered.is_set()
    finally:
        release.set()
        await asyncio.gather(tick, manual)
    recorded = await configured.schedule_store.get("tick-schedule")
    assert recorded.runs_so_far == 2
    assert recorded.last_run_id == manual.result()
    assert recorded.last_fired_at == NOON
    assert recorded.next_due_at == NOON + timedelta(hours=1)
    assert len(await runs(configured)) == 2
    assert all(run.status is RunStatus.COMPLETED for run in await runs(configured))


async def test_tick_never_backfills_an_orphan_hive_row(configured: Any) -> None:
    import stores
    from services.scheduler import _ScheduleRunner

    row = await hive_row(configured)
    stores.schedules._data["orphan"] = row.model_copy(update={"id": "orphan"})
    await _ScheduleRunner()._tick()
    assert await configured.schedule_store.get("orphan") is None
    assert len(await runs(configured)) == 1


@pytest.mark.parametrize("cursor_failure", [False, True])
async def test_restart_consumes_queued_run_without_refiring(
    configured: Any, database_url: str, monkeypatch: pytest.MonkeyPatch, cursor_failure: bool
) -> None:
    from services.scheduler import _ScheduleRunner

    from maistro.runs.consumption import TickAccounting

    async def defer_consumer() -> TickAccounting:
        return TickAccounting(attempted=0, succeeded=0, failed=0, parked=0, skipped=0)

    monkeypatch.setattr(configured, "execute_admitted_runs_accounting", defer_consumer)
    if cursor_failure:
        record_fire = configured.schedule_store.record_fire

        async def fail_cursor(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("run_id"):
                raise RuntimeError("process died before cursor write")
            return await record_fire(*args, **kwargs)

        monkeypatch.setattr(configured.schedule_store, "record_fire", fail_cursor)
    await _ScheduleRunner()._tick()
    [queued] = await runs(configured)
    assert queued.status is RunStatus.QUEUED
    await configured.aclose()
    restarted = await create_container(
        AgentConfig(
            router_api_key="test-key", workspace_id="tick-parity", database_url=database_url
        )
    )
    monkeypatch.setattr(_ScheduleRunner, "_canonical_container", staticmethod(lambda: restarted))
    try:
        await _ScheduleRunner()._tick()
        [completed] = await runs(restarted)
        assert completed.run_id == queued.run_id and completed.status is RunStatus.COMPLETED
        recorded = await restarted.schedule_store.get("tick-schedule")
        # In-window duplicate reconciliation does not credit the dead winner's
        # count (#1269); this cutover preserves that existing core contract.
        assert recorded.runs_so_far == (0 if cursor_failure else 1)
        assert recorded.last_run_id == completed.run_id
        assert recorded.next_due_at == NOON + timedelta(hours=1)
        [node] = await restarted.run_store.list_node_runs(completed.run_id)
        assert len(await restarted.run_store.list_attempts(node.node_run_id)) == 1
        await _ScheduleRunner()._tick()
        assert [item.run_id for item in await runs(restarted)] == [queued.run_id]
        assert len(await restarted.run_store.list_attempts(node.node_run_id)) == 1
    finally:
        await restarted.aclose()


@pytest.mark.parametrize("has_run", [False, True])
async def test_future_schedule_recovers_expired_manual_marker_without_extra_fire(
    configured: Any, monkeypatch: pytest.MonkeyPatch, has_run: bool
) -> None:
    from services.scheduler import ScheduleNotFireable, _ScheduleRunner, fire_now

    from maistro.scheduling import admission

    original = await configured.schedule_store.get("tick-schedule")
    await configured.schedule_store.put(
        original.model_copy(update={"cron": "0 0 1 1 *", "max_runs": 1})
    )
    await _ScheduleRunner()._tick()
    future = await configured.schedule_store.get("tick-schedule")
    assert future.next_due_at == datetime(2027, 1, 1, tzinfo=UTC)
    if has_run:
        await hive_row(configured)
        settle = configured.schedule_store.settle_pending_fire

        async def interrupted_settlement(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("process died after manual Run creation")

        monkeypatch.setattr(
            configured.schedule_store, "settle_pending_fire", interrupted_settlement
        )
        with pytest.raises(ScheduleNotFireable, match="process died"):
            await fire_now("tick-schedule", fire_id="pending-manual")
        monkeypatch.setattr(configured.schedule_store, "settle_pending_fire", settle)
    else:
        # A process died after the durable reservation but before Run creation.
        await configured.schedule_store.reserve_fire("tick-schedule", fire_id="pending-manual")
    reserved = await configured.schedule_store.get("tick-schedule")
    [marker] = reserved.pending_fires
    assert reserved.runs_so_far == 0 and reserved.enabled

    wall = marker.stamped_at

    class RecoveryClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return wall

    monkeypatch.setattr(admission, "datetime", RecoveryClock)
    # Selection is only a chance to recover. The admitter still owns the
    # lease and must leave a live holder's marker alone, even on a slow host.
    await _ScheduleRunner()._tick()
    assert (await configured.schedule_store.get("tick-schedule")).pending_fires == (marker,)

    wall += admission._PENDING_FIRE_LEASE + timedelta(seconds=1)
    await _ScheduleRunner()._tick()
    recovered = await configured.schedule_store.get("tick-schedule")
    assert recovered.pending_fires == ()
    assert recovered.runs_so_far == int(has_run)
    assert recovered.enabled is not has_run
    assert recovered.last_fired_at == original.last_fired_at
    assert recovered.next_due_at == (None if has_run else future.next_due_at)
    admitted = await runs(configured)
    assert len(admitted) == int(has_run)
    if has_run:
        assert recovered.last_run_id == admitted[0].run_id
        assert admitted[0].status is RunStatus.COMPLETED
        [node] = await configured.run_store.list_node_runs(admitted[0].run_id)
        assert len(await configured.run_store.list_attempts(node.node_run_id)) == 1
    await _ScheduleRunner()._tick()
    assert [item.run_id for item in await runs(configured)] == [item.run_id for item in admitted]
