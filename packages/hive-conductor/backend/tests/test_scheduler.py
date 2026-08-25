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

    fired: list[tuple[datetime, bool]] = []

    async def _capture(
        self: Any,
        sid: str,
        schedule: Any,
        *,
        scheduled_for: datetime | None = None,
        catchup: bool = False,
    ) -> None:
        assert scheduled_for is not None
        fired.append((scheduled_for, catchup))

    monkeypatch.setattr(_ScheduleRunner, "_fire_schedule", _capture)
    now = datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
    stub = _schedule_stub("s", "tpl", cron="0 * * * *", last_run=now - timedelta(hours=1))
    asyncio.run(_ScheduleRunner()._evaluate_schedule("s", stub, now=now))
    # The catch-up flag reaches the fire path. `evaluate()` distinguishes a
    # backfill from an on-time fire, and that distinction used to be dropped
    # between the decision and the Run (#145).
    #
    # `catchup=True` here is correct, not incidental: the 12:00 occurrence is
    # being evaluated at 12:05, which is past `_fresh_boundary`'s one-minute
    # window. The on-time case is asserted separately below, so this test
    # distinguishes the two rather than recording whichever it happens to get.
    assert fired == [(datetime(2026, 8, 21, 12, 0, tzinfo=UTC), True)]


def test_an_on_time_fire_is_not_marked_as_a_catch_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """The counterweight to the catch-up assertion above.

    Without this, threading `catchup` through would look correct while always
    passing `True` — a flag that is never `False` carries no information.
    """
    from services.scheduler import _ScheduleRunner

    fired: list[tuple[datetime, bool]] = []

    async def _capture(
        self: Any,
        sid: str,
        schedule: Any,
        *,
        scheduled_for: datetime | None = None,
        catchup: bool = False,
    ) -> None:
        assert scheduled_for is not None
        fired.append((scheduled_for, catchup))

    monkeypatch.setattr(_ScheduleRunner, "_fire_schedule", _capture)
    # Evaluated within the freshness window of its own occurrence.
    now = datetime(2026, 8, 21, 12, 0, 30, tzinfo=UTC)
    stub = _schedule_stub("s", "tpl", cron="0 * * * *", last_run=now - timedelta(hours=1))
    asyncio.run(_ScheduleRunner()._evaluate_schedule("s", stub, now=now))

    assert fired == [(datetime(2026, 8, 21, 12, 0, tzinfo=UTC), False)]


def test_an_in_flight_schedule_does_not_stack_a_second_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overlap SKIP: the default that keeps a twenty-minute agent Run off a
    fifteen-minute schedule's back."""
    from services.scheduler import _ScheduleRunner

    fired: list[str] = []

    async def _capture(
        self: Any,
        sid: str,
        schedule: Any,
        *,
        scheduled_for: datetime | None = None,
        catchup: bool = False,
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


def test_a_scheduled_run_records_its_schedule_on_the_run() -> None:
    """#46 asks for schedule provenance retained *on the Run*, not beside it.

    It lived only in the `schedule_run` audit line, so a Run a schedule fired
    was indistinguishable from one a person started — you could go Run → audit
    → schedule, but nothing on the Run itself said where it came from. Tasks
    (#41) and chat turns (#131) both carry theirs on the Run; scheduling was
    the outlier (#145).
    """
    import stores
    from services.dag_agents import get_registry
    from services.scheduler import _ScheduleRunner

    registry = get_registry()
    registry.register(
        {
            "id": "sched-prov",
            "name": "Sched Prov",
            "entry_node": "only",
            "nodes": [{"id": "only", "kind": "transform.alias_keys", "config": {"mapping": {}}}],
            "edges": [],
        }
    )
    stub = _schedule_stub("s-prov", "sched-prov")
    stores.schedules._data["s-prov"] = stub  # type: ignore[attr-defined]
    try:
        scheduled_for = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
        asyncio.run(
            _ScheduleRunner()._fire_schedule(
                "s-prov", stub, scheduled_for=scheduled_for, catchup=True
            )
        )

        from services.dag_agents import _run_store

        runs = [r.run for r in _run_store._rows.values()]  # type: ignore[attr-defined]
        scheduled = [r for r in runs if r.provenance.get("schedule_id") == "s-prov"]
        assert len(scheduled) == 1, "exactly one Run, and it names its schedule"
        provenance = scheduled[0].provenance

        assert provenance["admission_source"] == "schedule"
        assert provenance["scheduled_for"] == scheduled_for.isoformat()
        assert provenance["catchup"] is True
        # The executor's own marker survives the merge — a Run that claimed a
        # different executor than the one that walked it would be worse than
        # one that claimed none.
        assert provenance["executor"] == "durable_graph"
    finally:
        stores.schedules._data.pop("s-prov", None)  # type: ignore[attr-defined]
        registry.deregister("sched-prov")


def test_fire_schedule_unresolved_template_says_so_instead_of_going_quiet() -> None:
    """An unregistered target is reported, not silently skipped (#145).

    This used to be a bare `return` after `last_run` had already been stamped,
    so the schedule looked like it had fired: no warning, no audit line, no
    Run. `DagRegistry` is an in-process dict, so an empty registry is the
    normal state after a restart — exactly when an operator most needs to be
    told that a schedule is firing into nothing.
    """
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
        assert "run_id" not in new_entries[1]["detail"], "nothing ran, so nothing to name"
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


# --- #231: the cursor advances only after a Run exists -----------------------


def _register(dag_id: str) -> None:
    from services.dag_agents import get_registry

    get_registry().register(
        {
            "id": dag_id,
            "name": dag_id,
            "entry_node": "only",
            "nodes": [{"id": "only", "kind": "transform.alias_keys", "config": {"mapping": {}}}],
            "edges": [],
        }
    )


class _RecordingStore:
    """A ScheduleStore that remembers what the runner asked it to do."""

    def __init__(self) -> None:
        self.saved: dict[str, Any] = {}
        self.fires: list[dict[str, Any]] = []

    async def get(self, schedule_id: str) -> Any:
        return self.saved.get(schedule_id)

    async def put(self, schedule: Any) -> Any:
        self.saved[schedule.schedule_id] = schedule
        return schedule

    async def record_fire(self, schedule_id: str, **kwargs: Any) -> Any:
        self.fires.append({"schedule_id": schedule_id, **kwargs})
        return self.saved.get(schedule_id)


def _run_evaluate(sid: str, stub: Any, *, now: datetime, store: Any = None) -> None:
    import services.scheduler as sched

    runner = sched._ScheduleRunner()
    runner._canonical_store = staticmethod(lambda: store)  # type: ignore[method-assign]
    asyncio.run(runner._evaluate_schedule(sid, stub, now=now))


def test_an_unregistered_template_leaves_the_occurrence_owed() -> None:
    """The defect this issue names: a firing that produced no Run must not
    advance the cursor.

    `_fire_schedule` used to stamp `last_run` on its first line and discover
    the template was unregistered afterwards, so the schedule asserted it had
    fired with no `run_id` anywhere — a receipt for work that never started.
    """
    import stores

    now = datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
    stub = _schedule_stub(
        "s-owed", "tpl-never-registered", cron="0 * * * *", last_run=now - timedelta(hours=1)
    )
    stores.schedules._data["s-owed"] = stub  # type: ignore[attr-defined]
    store = _RecordingStore()
    try:
        _run_evaluate("s-owed", stub, now=now, store=store)
        assert store.fires == [], "nothing ran, so the cursor must not move"
        current = stores.schedules._data["s-owed"]  # type: ignore[attr-defined]
        assert current.last_run == now - timedelta(hours=1), "the row's cursor is untouched too"
    finally:
        stores.schedules._data.pop("s-owed", None)  # type: ignore[attr-defined]


def test_the_owed_occurrence_fires_once_the_template_resolves() -> None:
    """The other half: leaving it owed is only right if it can still happen."""
    import stores

    now = datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
    stub = _schedule_stub(
        "s-later", "sched-resolves-late", cron="0 * * * *", last_run=now - timedelta(hours=1)
    )
    stores.schedules._data["s-later"] = stub  # type: ignore[attr-defined]
    store = _RecordingStore()
    try:
        _run_evaluate("s-later", stub, now=now, store=store)
        assert store.fires == []

        _register("sched-resolves-late")
        _run_evaluate(
            "s-later",
            stores.schedules._data["s-later"],  # type: ignore[attr-defined]
            now=now,
            store=store,
        )

        assert len(store.fires) == 1
        assert store.fires[0]["run_id"]
        assert store.fires[0]["fired_at"] == datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    finally:
        stores.schedules._data.pop("s-later", None)  # type: ignore[attr-defined]


def test_the_cursor_records_the_run_that_claimed_the_occurrence() -> None:
    """`last_run_id` must resolve to the canonical Run, not to nothing."""
    import stores

    _register("sched-cursor")
    now = datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
    stub = _schedule_stub(
        "s-cursor", "sched-cursor", cron="0 * * * *", last_run=now - timedelta(hours=1)
    )
    stores.schedules._data["s-cursor"] = stub  # type: ignore[attr-defined]
    store = _RecordingStore()
    try:
        _run_evaluate("s-cursor", stub, now=now, store=store)
        assert len(store.fires) == 1
        fire = store.fires[0]
        assert fire["schedule_id"] == "s-cursor"
        assert isinstance(fire["run_id"], str) and fire["run_id"]
        # The next occurrence, computed from the nominal fire rather than now.
        assert fire["next_due_at"] == datetime(2026, 8, 21, 13, 0, tzinfo=UTC)
        row = stores.schedules._data["s-cursor"]  # type: ignore[attr-defined]
        assert row.last_run == datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    finally:
        stores.schedules._data.pop("s-cursor", None)  # type: ignore[attr-defined]


def test_the_durable_cursor_outranks_the_in_memory_row() -> None:
    """A restart loses the row's `last_run`; the store's is what counts.

    Without this the schedule would re-fire every occurrence inside the
    catch-up window on the first tick after every restart.
    """
    import stores

    from maistro.scheduling import Schedule

    _register("sched-restart")
    now = datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
    # The row came back from a restart with no cursor at all.
    stub = _schedule_stub("s-restart", "sched-restart", cron="0 * * * *", last_run=None)
    stores.schedules._data["s-restart"] = stub  # type: ignore[attr-defined]
    store = _RecordingStore()
    store.saved["s-restart"] = Schedule(
        schedule_id="s-restart",
        workspace_id="hive:schedule:s-restart",
        project_id="hive:schedule:s-restart",
        cron="0 * * * *",
        graph_template_id="sched-restart",
        last_fired_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
        last_run_id="run-from-before-the-restart",
        runs_so_far=3,
    )
    try:
        _run_evaluate("s-restart", stub, now=now, store=store)
        assert store.fires == [], "the 12:00 occurrence already fired before the restart"
    finally:
        stores.schedules._data.pop("s-restart", None)  # type: ignore[attr-defined]


def test_without_a_bridge_the_scheduler_still_fires() -> None:
    """No Container, no canonical store — the loop degrades, it does not stop."""
    import stores

    _register("sched-no-bridge")
    now = datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
    stub = _schedule_stub(
        "s-nb", "sched-no-bridge", cron="0 * * * *", last_run=now - timedelta(hours=1)
    )
    stores.schedules._data["s-nb"] = stub  # type: ignore[attr-defined]
    try:
        _run_evaluate("s-nb", stub, now=now, store=None)
        row = stores.schedules._data["s-nb"]  # type: ignore[attr-defined]
        assert row.last_run == datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    finally:
        stores.schedules._data.pop("s-nb", None)  # type: ignore[attr-defined]
