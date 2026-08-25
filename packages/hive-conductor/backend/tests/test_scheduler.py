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


# --- #265: the bound and the zone reach the product surface ------------------


def _bounded_stub(
    sid: str,
    template_id: str,
    *,
    cron: str = "* * * * *",
    last_run: datetime | None = None,
    timezone: str = "UTC",
    max_runs: int | None = None,
) -> Any:
    """A row carrying the columns #265 adds."""
    stub = _schedule_stub(sid, template_id, cron=cron, last_run=last_run)
    stub.timezone = timezone
    stub.max_runs = max_runs
    stub.last_run_id = None
    return stub


def _schedule_runs(sid: str, *, since: int) -> list[dict[str, Any]]:
    """The `schedule_run` audit entries for `sid` that carry a run_id."""
    import stores

    return [
        e
        for e in list(stores.audit_log.values())[since:]
        if e.get("target") == sid and e["action"] == "schedule_run" and "run_id" in e["detail"]
    ]


def test_the_definition_takes_its_zone_and_bound_from_the_row() -> None:
    """Both used to be unreachable: the zone was hardcoded UTC and the bound
    was never set, so `max_runs` could not be applied by any caller."""
    from services.scheduler import _ScheduleRunner

    definition = _ScheduleRunner()._as_definition(
        "s1", _bounded_stub("s1", "tpl", timezone="America/Chicago", max_runs=4)
    )
    assert definition is not None
    assert definition.timezone == "America/Chicago"
    assert definition.max_runs == 4


def test_a_row_without_the_new_columns_still_projects() -> None:
    """The columns are additive: a row persisted before them keeps firing, in
    UTC and unbounded, which is exactly what it did."""
    from services.scheduler import _ScheduleRunner

    stub = _schedule_stub("legacy", "tpl")
    assert not hasattr(stub, "timezone")
    assert not hasattr(stub, "max_runs")
    definition = _ScheduleRunner()._as_definition("legacy", stub)
    assert definition is not None
    assert definition.timezone == "UTC"
    assert definition.max_runs is None


def test_the_definition_carries_the_rows_disabled_flag() -> None:
    """`enabled` used to be hardcoded True. `_definition_for` ends in
    `store.put(...)`, so a hardcoded True there puts an `enabled: true`
    straight back over a disable `record_fire` had just written."""
    from services.scheduler import _ScheduleRunner

    stub = _schedule_stub("off", "tpl", enabled=False)
    definition = _ScheduleRunner()._as_definition("off", stub)
    assert definition is not None
    assert definition.enabled is False


def test_a_non_utc_zone_is_evaluated_in_that_zone() -> None:
    """AC: a schedule with a non-UTC zone fires at the intended local time.

    Both definitions read `0 9 * * *` and both fire at 09:00 *local* — the
    point is that those are different instants. In August, Chicago is CDT, so
    its 09:00 is 14:00 UTC. Before the column existed every schedule was
    evaluated in UTC, so this one fired five hours early.
    """
    from services.scheduler import _ScheduleRunner

    runner = _ScheduleRunner()
    local = runner._as_definition(
        "s-tz", _bounded_stub("s-tz", "tpl", cron="0 9 * * *", timezone="America/Chicago")
    )
    utc = runner._as_definition("s-utc", _bounded_stub("s-utc", "tpl", cron="0 9 * * *"))
    assert local is not None and utc is not None

    from_moment = datetime(2026, 8, 20, 0, 0, tzinfo=UTC)
    local_fire = local.next_fire_after(from_moment)
    utc_fire = utc.next_fire_after(from_moment)

    assert local_fire.hour == 9, "09:00 in its own zone"
    assert local_fire.astimezone(UTC).hour == 14, "which is 14:00 UTC in August"
    assert utc_fire.astimezone(UTC).hour == 9
    assert local_fire != utc_fire, "the zone changes the instant, not just the label"


def test_a_bounded_schedule_fires_its_bound_and_then_disables() -> None:
    """AC: `max_runs: 3` fires exactly three times through the real runner,
    and the `/v1/schedules` row then reports `enabled: false`."""
    import stores

    from maistro.scheduling import InMemoryScheduleStore

    _register("sched-bounded")
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    stub = _bounded_stub(
        "s-bound", "sched-bounded", last_run=now - timedelta(minutes=1), max_runs=3
    )
    stores.schedules._data["s-bound"] = stub  # type: ignore[attr-defined]
    store = InMemoryScheduleStore()
    before = len(stores.audit_log)
    try:
        for minute in range(5):
            _run_evaluate(
                "s-bound",
                stores.schedules._data["s-bound"],  # type: ignore[attr-defined]
                now=now + timedelta(minutes=minute),
                store=store,
            )
        assert len(_schedule_runs("s-bound", since=before)) == 3, "the bound is the bound"

        row = stores.schedules._data["s-bound"]  # type: ignore[attr-defined]
        assert row.enabled is False, "a spent schedule must say so on the surface"
        assert row.next_run is None

        recorded = asyncio.run(store.get("s-bound"))
        assert recorded is not None
        assert recorded.runs_so_far == 3
        assert recorded.enabled is False
    finally:
        stores.schedules._data.pop("s-bound", None)  # type: ignore[attr-defined]


def test_the_disable_is_not_resurrected_by_the_next_tick() -> None:
    """AC: the disable survives further ticks, and the canonical store stops
    returning the schedule from `due()`.

    `_definition_for` ends in `store.put(definition)`. While `_as_definition`
    hardcoded `enabled=True`, that put overwrote the disable `record_fire` had
    just written — leaving a spent schedule enabled, reported as due forever
    (`_is_due` reads a null `next_due_at` as due), and never firing.
    """
    import stores

    from maistro.scheduling import InMemoryScheduleStore

    _register("sched-resurrect")
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    stub = _bounded_stub(
        "s-res", "sched-resurrect", last_run=now - timedelta(minutes=1), max_runs=1
    )
    stores.schedules._data["s-res"] = stub  # type: ignore[attr-defined]
    store = InMemoryScheduleStore()
    before = len(stores.audit_log)
    try:
        _run_evaluate("s-res", stub, now=now, store=store)
        assert len(_schedule_runs("s-res", since=before)) == 1

        for minute in (1, 2, 3):
            _run_evaluate(
                "s-res",
                stores.schedules._data["s-res"],  # type: ignore[attr-defined]
                now=now + timedelta(minutes=minute),
                store=store,
            )

        assert len(_schedule_runs("s-res", since=before)) == 1, "no fire after exhaustion"
        recorded = asyncio.run(store.get("s-res"))
        assert recorded is not None and recorded.enabled is False
        due = asyncio.run(store.due(now=now + timedelta(minutes=10)))
        assert [d.schedule_id for d in due] == [], "a spent schedule is not due"
    finally:
        stores.schedules._data.pop("s-res", None)  # type: ignore[attr-defined]


def test_the_row_carries_the_run_that_claimed_the_occurrence() -> None:
    """AC: `last_run_id` on the row resolves to the canonical Run. `last_run`
    alone said only *that* something fired."""
    import stores

    from maistro.scheduling import InMemoryScheduleStore

    _register("sched-runid")
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    stub = _bounded_stub("s-runid", "sched-runid", last_run=now - timedelta(minutes=1))
    stores.schedules._data["s-runid"] = stub  # type: ignore[attr-defined]
    store = InMemoryScheduleStore()
    before = len(stores.audit_log)
    try:
        _run_evaluate("s-runid", stub, now=now, store=store)
        runs = _schedule_runs("s-runid", since=before)
        assert len(runs) == 1
        run_id = runs[0]["detail"]["run_id"]

        row = stores.schedules._data["s-runid"]  # type: ignore[attr-defined]
        assert row.last_run_id == run_id
        recorded = asyncio.run(store.get("s-runid"))
        assert recorded is not None and recorded.last_run_id == run_id
    finally:
        stores.schedules._data.pop("s-runid", None)  # type: ignore[attr-defined]


# --- #265: `POST /{id}/run` fires for real, or refuses -----------------------


def _with_store(monkeypatch: pytest.MonkeyPatch, store: Any) -> None:
    from services.scheduler import _ScheduleRunner

    monkeypatch.setattr(_ScheduleRunner, "_canonical_store", staticmethod(lambda: store))


def test_a_manual_run_creates_a_run_and_records_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoint used to stamp `last_run` and stop: no Run, no cursor,
    nothing counted. That is the receipt-for-work-that-never-started defect
    #231 removed from the tick path, still live on the route."""
    import stores
    from services.scheduler import fire_now

    from maistro.scheduling import InMemoryScheduleStore

    _register("sched-manual")
    stub = _bounded_stub("s-man", "sched-manual")
    stores.schedules._data["s-man"] = stub  # type: ignore[attr-defined]
    store = InMemoryScheduleStore()
    _with_store(monkeypatch, store)
    before = len(stores.audit_log)
    try:
        run_id = asyncio.run(fire_now("s-man"))
        assert run_id

        runs = _schedule_runs("s-man", since=before)
        assert [r["detail"]["run_id"] for r in runs] == [run_id]

        row = stores.schedules._data["s-man"]  # type: ignore[attr-defined]
        assert row.last_run_id == run_id, "the stamp now names the Run behind it"
        assert row.last_run is not None

        recorded = asyncio.run(store.get("s-man"))
        assert recorded is not None
        assert recorded.runs_so_far == 1, "a manual fire is a fire, and counts"
        assert recorded.last_run_id == run_id
    finally:
        stores.schedules._data.pop("s-man", None)  # type: ignore[attr-defined]


def test_a_manual_run_that_cannot_start_leaves_no_stamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refusing is the whole point: the caller asked for work to start and it
    did not, so the schedule must not claim otherwise."""
    import stores
    from services.scheduler import ScheduleNotFireable, fire_now

    from maistro.scheduling import InMemoryScheduleStore

    stub = _bounded_stub("s-man-fail", "tpl-not-registered")
    stores.schedules._data["s-man-fail"] = stub  # type: ignore[attr-defined]
    _with_store(monkeypatch, InMemoryScheduleStore())
    try:
        with pytest.raises(ScheduleNotFireable):
            asyncio.run(fire_now("s-man-fail"))
        row = stores.schedules._data["s-man-fail"]  # type: ignore[attr-defined]
        assert row.last_run is None
        assert row.last_run_id is None
    finally:
        stores.schedules._data.pop("s-man-fail", None)  # type: ignore[attr-defined]


def test_a_manual_run_respects_the_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """`max_runs` bounds every firing, not only the scheduled ones."""
    import stores
    from services.scheduler import ScheduleNotFireable, fire_now

    from maistro.scheduling import InMemoryScheduleStore

    _register("sched-manual-bound")
    stub = _bounded_stub("s-man-bound", "sched-manual-bound", max_runs=1)
    stores.schedules._data["s-man-bound"] = stub  # type: ignore[attr-defined]
    store = InMemoryScheduleStore()
    _with_store(monkeypatch, store)
    before = len(stores.audit_log)
    try:
        asyncio.run(fire_now("s-man-bound"))
        with pytest.raises(ScheduleNotFireable, match="all 1 of its runs"):
            asyncio.run(fire_now("s-man-bound"))
        assert len(_schedule_runs("s-man-bound", since=before)) == 1
    finally:
        stores.schedules._data.pop("s-man-bound", None)  # type: ignore[attr-defined]


def test_a_manual_run_of_a_targetless_schedule_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stores
    from services.scheduler import ScheduleNotFireable, fire_now

    from maistro.scheduling import InMemoryScheduleStore

    stores.schedules._data["s-man-none"] = _schedule_stub("s-man-none", None)  # type: ignore[attr-defined]
    _with_store(monkeypatch, InMemoryScheduleStore())
    try:
        with pytest.raises(ScheduleNotFireable, match="no mission template"):
            asyncio.run(fire_now("s-man-none"))
    finally:
        stores.schedules._data.pop("s-man-none", None)  # type: ignore[attr-defined]


def test_a_manual_run_of_an_unknown_schedule_is_refused() -> None:
    from services.scheduler import ScheduleNotFireable, fire_now

    with pytest.raises(ScheduleNotFireable, match="does not exist"):
        asyncio.run(fire_now("s-nope"))


# --- #265: the HTTP surface --------------------------------------------------


def test_a_schedule_can_be_created_with_a_zone_and_a_bound(admin_client: Any) -> None:
    """AC: both are expressible through the product surface. Neither was."""
    created = admin_client.post(
        "/v1/schedules",
        json={
            "name": "nightly",
            "cron_expression": "0 9 * * *",
            "mission_template_id": "tpl",
            "timezone": "America/Chicago",
            "max_runs": 3,
        },
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    try:
        fetched = admin_client.get(f"/v1/schedules/{sid}").json()
        assert fetched["timezone"] == "America/Chicago"
        assert fetched["max_runs"] == 3
        assert fetched["last_run_id"] is None
    finally:
        admin_client.delete(f"/v1/schedules/{sid}")


def test_a_create_that_omits_them_behaves_as_it_always_did(admin_client: Any) -> None:
    """The columns are additive: an existing client sends neither and gets an
    unbounded schedule evaluated in UTC, exactly as before."""
    created = admin_client.post(
        "/v1/schedules",
        json={"name": "legacy", "cron_expression": "0 9 * * *", "mission_template_id": "tpl"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    try:
        assert body["timezone"] == "UTC"
        assert body["max_runs"] is None
        assert body["last_run_id"] is None
    finally:
        admin_client.delete(f"/v1/schedules/{body['id']}")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timezone", "Mars/Olympus_Mons"),
        ("timezone", "definitely not a zone"),
        ("max_runs", 0),
        ("max_runs", -1),
    ],
)
def test_an_unusable_zone_or_bound_is_refused_at_the_boundary(
    admin_client: Any, field: str, value: Any
) -> None:
    """422 here, not a 500 and not a silent accept.

    The `/v1/schedules` row is a separate model that stores what it is given.
    An unreadable value would be accepted and then raise inside
    `_as_definition` on *every* tick, where `_tick` catches it and logs a
    warning — a schedule that never fires and reports `enabled: true` forever.
    """
    body = {"name": "bad", "cron_expression": "0 9 * * *", "mission_template_id": "tpl"}
    body[field] = value
    response = admin_client.post("/v1/schedules", json=body)
    assert response.status_code == 422, response.text


def test_the_zone_and_bound_can_be_updated(admin_client: Any) -> None:
    created = admin_client.post(
        "/v1/schedules",
        json={"name": "movable", "cron_expression": "0 9 * * *", "mission_template_id": "tpl"},
    )
    sid = created.json()["id"]
    try:
        updated = admin_client.put(
            f"/v1/schedules/{sid}", json={"timezone": "Europe/Berlin", "max_runs": 2}
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["timezone"] == "Europe/Berlin"
        assert updated.json()["max_runs"] == 2

        # A partial update that names neither leaves both alone -- this
        # endpoint's `exclude_none=True` contract, stated on the body model.
        renamed = admin_client.put(f"/v1/schedules/{sid}", json={"name": "renamed"})
        assert renamed.json()["timezone"] == "Europe/Berlin"
        assert renamed.json()["max_runs"] == 2
    finally:
        admin_client.delete(f"/v1/schedules/{sid}")


def test_an_update_to_an_unusable_zone_is_refused(admin_client: Any) -> None:
    created = admin_client.post(
        "/v1/schedules",
        json={"name": "keeper", "cron_expression": "0 9 * * *", "mission_template_id": "tpl"},
    )
    sid = created.json()["id"]
    try:
        assert (
            admin_client.put(f"/v1/schedules/{sid}", json={"timezone": "Nope/Nope"}).status_code
            == 422
        )
        assert admin_client.get(f"/v1/schedules/{sid}").json()["timezone"] == "UTC"
    finally:
        admin_client.delete(f"/v1/schedules/{sid}")


def test_a_manual_run_that_cannot_fire_is_a_conflict_not_a_stamp(admin_client: Any) -> None:
    """AC: the endpoint no longer leaves the schedule claiming a fire with no
    Run behind it. `tpl` is not a registered DAG, so nothing can start."""
    created = admin_client.post(
        "/v1/schedules",
        json={"name": "manual", "cron_expression": "0 9 * * *", "mission_template_id": "tpl"},
    )
    sid = created.json()["id"]
    try:
        response = admin_client.post(f"/v1/schedules/{sid}/run")
        assert response.status_code == 409, response.text

        after = admin_client.get(f"/v1/schedules/{sid}").json()
        assert after["last_run"] is None, "no receipt for work that never started"
        assert after["last_run_id"] is None
    finally:
        admin_client.delete(f"/v1/schedules/{sid}")


def test_a_manual_run_of_an_unknown_schedule_is_still_a_404(admin_client: Any) -> None:
    assert admin_client.post("/v1/schedules/does-not-exist/run").status_code == 404


def test_an_explicit_null_leaves_the_field_alone(admin_client: Any) -> None:
    """`{"timezone": null}` is a real request, distinct from omitting the key:
    pydantic runs the validator for an explicit null and not for an absent
    field. Both must mean "leave alone" — this endpoint's `exclude_none=True`
    contract — rather than 422 on a zone that is not a zone.
    """
    created = admin_client.post(
        "/v1/schedules",
        json={
            "name": "nullable",
            "cron_expression": "0 9 * * *",
            "mission_template_id": "tpl",
            "timezone": "Europe/Berlin",
            "max_runs": 5,
        },
    )
    sid = created.json()["id"]
    try:
        updated = admin_client.put(
            f"/v1/schedules/{sid}", json={"timezone": None, "max_runs": None}
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["timezone"] == "Europe/Berlin"
        assert updated.json()["max_runs"] == 5
    finally:
        admin_client.delete(f"/v1/schedules/{sid}")
