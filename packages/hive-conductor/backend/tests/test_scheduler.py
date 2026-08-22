"""Coverage for services/scheduler.py.

The cron matcher this module used to own is gone: recurrence and fire
semantics live in `maistro.scheduling`, verified there against a brute-force
oracle. What remains here is the loop and its effects — lifecycle, projecting
the live `/v1/schedules` row onto the canonical definition, and turning a
fire into a Run.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture(autouse=True)
def _reset_singleton():
    import services.scheduler as sched

    prev = sched._runner
    sched._runner = None
    yield
    sched._runner = prev


def _schedule_stub(
    sid: str,
    template_id: str | None,
    *,
    cron: str = "* * * * *",
    enabled: bool = True,
    last_run: datetime | None = None,
) -> Any:
    class _Sched:
        def __init__(self) -> None:
            self.id = sid
            self.enabled = enabled
            self.cron_expression = cron
            self.name = f"name-{sid}"
            self.mission_template_id = template_id
            self.user_id = "u1"
            self.last_run = last_run
            self.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            self.updated_at = None

        def model_copy(self, *, update: dict[str, Any]) -> Any:
            for k, v in update.items():
                setattr(self, k, v)
            return self

    return _Sched()


# --- start/stop lifecycle ----------------------------------------------------


def test_start_scheduler_creates_singleton_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.scheduler as sched

    def _swallow(coro: Any) -> Any:
        coro.close()
        return None

    monkeypatch.setattr(sched.asyncio, "ensure_future", _swallow)
    assert sched._runner is None
    sched.start_scheduler()
    first = sched._runner
    assert first is not None
    sched.start_scheduler()
    assert sched._runner is first
    sched.stop_scheduler()


def test_stop_scheduler_clears_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.scheduler as sched

    def _swallow(coro: Any) -> Any:
        coro.close()
        return None

    monkeypatch.setattr(sched.asyncio, "ensure_future", _swallow)
    sched.start_scheduler()
    assert sched._runner is not None
    sched.stop_scheduler()
    assert sched._runner is None


def test_stop_scheduler_when_not_running_is_noop() -> None:
    import services.scheduler as sched

    assert sched._runner is None
    sched.stop_scheduler()
    assert sched._runner is None


def test_runner_stop_flips_running() -> None:
    from services.scheduler import _ScheduleRunner

    runner = _ScheduleRunner()
    assert runner._running is True
    runner.stop()
    assert runner._running is False


# --- projection onto the canonical definition --------------------------------


def test_row_projects_onto_a_canonical_schedule_definition() -> None:
    from services.scheduler import _ScheduleRunner

    from maistro.scheduling import OverlapPolicy

    fired = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    definition = _ScheduleRunner()._as_definition(
        "s1", _schedule_stub("s1", "daily-status", cron="0 9 * * *", last_run=fired)
    )
    assert definition is not None
    assert definition.schedule_id == "s1"
    assert definition.cron == "0 9 * * *"
    assert definition.graph_template_id == "daily-status"
    assert definition.last_fired_at == fired
    assert definition.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert definition.actor_principal_id == "u1"
    # A long agent Run must never be stacked on itself by default.
    assert definition.overlap_policy is OverlapPolicy.SKIP


def test_sunday_schedules_now_evaluate_on_sunday() -> None:
    """End-to-end guard on the bug the deleted matcher had: `0 9 * * 0` used to
    fire Monday because day-of-week was indexed by Python's Monday=0."""
    from services.scheduler import _ScheduleRunner

    definition = _ScheduleRunner()._as_definition(
        "s1", _schedule_stub("s1", "tpl", cron="0 9 * * 0")
    )
    assert definition is not None
    fire = definition.next_fire_after(datetime(2026, 8, 19, tzinfo=UTC))
    assert fire.strftime("%A") == "Sunday"


def test_a_row_with_no_target_is_not_evaluated() -> None:
    """A schedule that names nothing to run cannot produce work; it is skipped
    rather than "fired" into nothing."""
    from services.scheduler import _ScheduleRunner

    assert _ScheduleRunner()._as_definition("s", _schedule_stub("s", None)) is None


def test_a_row_without_a_creation_time_still_fires() -> None:
    """A row predating the column must not be read as brand new — that would
    suppress every occurrence and silently retire the schedule."""
    from services.scheduler import _ScheduleRunner

    stub = _schedule_stub("s", "tpl", cron="0 * * * *")
    stub.created_at = None
    definition = _ScheduleRunner()._as_definition("s", stub)
    assert definition is not None
    assert definition.created_at.year == 1970


# --- tick --------------------------------------------------------------------


def test_tick_evaluates_enabled_schedules_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.scheduler as sched_mod
    from services.scheduler import _ScheduleRunner

    evaluated: list[str] = []

    class _FakeStores:
        schedules: ClassVar = {
            "on": _schedule_stub("on", None),
            "off": _schedule_stub("off", None, enabled=False),
        }

    monkeypatch.setitem(sys.modules, "stores", _FakeStores)

    async def _capture(self: Any, sid: str, schedule: Any, *, now: datetime) -> None:
        evaluated.append(sid)

    monkeypatch.setattr(_ScheduleRunner, "_evaluate_schedule", _capture)
    asyncio.run(_ScheduleRunner()._tick())
    assert evaluated == ["on"]
    assert sched_mod is not None


def test_tick_swallows_evaluation_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """One bad schedule must not stop the loop for every other schedule."""
    from services.scheduler import _ScheduleRunner

    class _FakeStores:
        schedules: ClassVar = {"s": _schedule_stub("s", None)}

    monkeypatch.setitem(sys.modules, "stores", _FakeStores)

    async def _boom(self: Any, sid: str, schedule: Any, *, now: datetime) -> None:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(_ScheduleRunner, "_evaluate_schedule", _boom)
    asyncio.run(_ScheduleRunner()._tick())  # must not raise


def test_evaluate_fires_a_due_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.scheduler import _ScheduleRunner

    fired: list[datetime] = []

    async def _capture(
        self: Any,
        sid: str,
        schedule: Any,
        *,
        scheduled_for: datetime | None = None,
        catchup: bool = False,
    ) -> None:
        assert scheduled_for is not None
        fired.append(scheduled_for)

    monkeypatch.setattr(_ScheduleRunner, "_fire_schedule", _capture)
    now = datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
    stub = _schedule_stub("s", "tpl", cron="0 * * * *", last_run=now - timedelta(hours=1))
    asyncio.run(_ScheduleRunner()._evaluate_schedule("s", stub, now=now))
    assert fired == [datetime(2026, 8, 21, 12, 0, tzinfo=UTC)]


def test_an_in_flight_schedule_does_not_stack_a_second_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overlap SKIP: the default that keeps a twenty-minute agent Run off a
    fifteen-minute schedule's back."""
    from services.scheduler import _ScheduleRunner

    fired: list[str] = []

    async def _capture(
        self: Any, sid: str, schedule: Any, *, scheduled_for: datetime | None = None
    ) -> None:
        fired.append(sid)

    monkeypatch.setattr(_ScheduleRunner, "_fire_schedule", _capture)
    runner = _ScheduleRunner()
    runner._in_flight.add("s")
    now = datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
    stub = _schedule_stub("s", "tpl", cron="0 * * * *", last_run=now - timedelta(hours=1))
    asyncio.run(runner._evaluate_schedule("s", stub, now=now))
    assert fired == []


# --- run() loop --------------------------------------------------------------


def test_run_loop_logs_and_continues_on_tick_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.scheduler as sched_mod
    from services.scheduler import _ScheduleRunner

    calls = [0]

    async def _flaky_tick(self: Any) -> None:
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("synthetic tick error")
        self._running = False

    monkeypatch.setattr(_ScheduleRunner, "_tick", _flaky_tick)

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(sched_mod.asyncio, "sleep", _no_sleep)
    asyncio.run(_ScheduleRunner().run())
    assert calls[0] >= 2


# --- Schedule -> canonical Run ------------------------------------------------


def test_fire_schedule_with_registered_dag_produces_canonical_run() -> None:
    """A firing whose target is a registered DAG executes through the canonical
    durable path and audits the Run identity, not just that it fired."""
    import stores
    from services.dag_agents import get_registry
    from services.scheduler import _ScheduleRunner

    registry = get_registry()
    registry.register(
        {
            "id": "sched-synth",
            "name": "Sched Synth",
            "entry_node": "only",
            "nodes": [{"id": "only", "kind": "transform.alias_keys", "config": {"mapping": {}}}],
            "edges": [],
        }
    )
    stub = _schedule_stub("s-run", "sched-synth")
    stores.schedules._data["s-run"] = stub  # type: ignore[attr-defined]
    before = len(stores.audit_log)
    try:
        scheduled_for = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
        asyncio.run(_ScheduleRunner()._fire_schedule("s-run", stub, scheduled_for=scheduled_for))
        new_entries = [
            e for e in list(stores.audit_log.values())[before:] if e.get("target") == "s-run"
        ]
        fires = [e for e in new_entries if e["action"] == "schedule_fire"]
        assert len(fires) == 1
        # The nominal occurrence is recorded, not the moment the tick noticed.
        assert fires[0]["detail"]["scheduled_for"] == scheduled_for.isoformat()

        runs = [e for e in new_entries if e["action"] == "schedule_run"]
        assert len(runs) == 1
        detail = runs[0]["detail"]
        assert detail["dag_id"] == "sched-synth"
        assert detail["status"] == "completed"
        assert detail["run_id"]
        assert detail["template_version"] == 1
    finally:
        stores.schedules._data.pop("s-run", None)  # type: ignore[attr-defined]
        registry.deregister("sched-synth")


def test_fire_schedule_unresolved_template_says_no_run_was_created() -> None:
    """A mission_template_id that is not a registered DAG produces no Run — and
    now says so instead of returning silently.

    `DagRegistry` is in-process, so this is also what a restart looks like
    before the DAG is re-registered. `last_run` has already been stamped by
    then, so a silent return left a schedule that appeared to have fired and
    had not (#145)."""
    import stores
    from services.scheduler import _ScheduleRunner

    stub = _schedule_stub("s-noop", "tpl-not-a-dag")
    stores.schedules._data["s-noop"] = stub  # type: ignore[attr-defined]
    before = len(stores.audit_log)
    try:
        asyncio.run(_ScheduleRunner()._fire_schedule("s-noop", stub))
        new_entries = [
            e for e in list(stores.audit_log.values())[before:] if e.get("target") == "s-noop"
        ]
        assert [e["action"] for e in new_entries] == ["schedule_fire", "schedule_run"]
        assert new_entries[1]["detail"]["error"] == "template_not_registered"
        assert "run_id" not in new_entries[1]["detail"]
    finally:
        stores.schedules._data.pop("s-noop", None)  # type: ignore[attr-defined]


def test_fire_schedule_no_template_id_skips_audit() -> None:
    import stores
    from services.scheduler import _ScheduleRunner

    stub = _schedule_stub("s2", None)
    stores.schedules._data["s2"] = stub  # type: ignore[attr-defined]
    before = len(stores.audit_log)
    try:
        asyncio.run(_ScheduleRunner()._fire_schedule("s2", stub))
        new_for_s2 = [
            e for e in list(stores.audit_log.values())[before:] if e.get("target") == "s2"
        ]
        assert new_for_s2 == []
    finally:
        stores.schedules._data.pop("s2", None)  # type: ignore[attr-defined]


def test_fire_schedule_run_failure_is_audited_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stores
    from services.dag_agents import get_registry
    from services.scheduler import _ScheduleRunner

    registry = get_registry()
    registry.register(
        {
            "id": "sched-boom",
            "name": "Sched Boom",
            "entry_node": "only",
            "nodes": [{"id": "only", "kind": "transform.alias_keys", "config": {"mapping": {}}}],
            "edges": [],
        }
    )

    async def _boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("synthetic run failure")

    import services.dag_agents as dag_agents_mod

    monkeypatch.setattr(dag_agents_mod, "run_durable_graph", _boom)

    stub = _schedule_stub("s-fail", "sched-boom")
    stores.schedules._data["s-fail"] = stub  # type: ignore[attr-defined]
    before = len(stores.audit_log)
    try:
        asyncio.run(_ScheduleRunner()._fire_schedule("s-fail", stub))
        runs = [
            e
            for e in list(stores.audit_log.values())[before:]
            if e.get("target") == "s-fail" and e["action"] == "schedule_run"
        ]
        assert len(runs) == 1
        assert runs[0]["detail"]["error"] == "RuntimeError"
    finally:
        stores.schedules._data.pop("s-fail", None)  # type: ignore[attr-defined]
        registry.deregister("sched-boom")
