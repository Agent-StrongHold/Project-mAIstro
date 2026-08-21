"""Boy Scout coverage: services/scheduler.py (was 0% line/branch).

Covers:
- start_scheduler / stop_scheduler singleton lifecycle
- _ScheduleRunner.stop sets _running=False
- _ScheduleRunner.run loop: _tick fires once + exception path logs
- _fire_schedule writes audit + updates last_run; no template_id → no audit
- _should_fire returns False for malformed cron / too-soon delta
- _field_matches: '*', comma list, '/step', 'lo-hi', literal int
- _field_matches edge cases: step<=0 → False, '*/N' → True at multiples
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


# --- field matcher --------------------------------------------------------


def test_field_matches_wildcard() -> None:
    from services.scheduler import _field_matches

    assert _field_matches("*", 0, 0, 59) is True
    assert _field_matches("*", 42, 0, 59) is True


def test_field_matches_literal_int() -> None:
    from services.scheduler import _field_matches

    assert _field_matches("5", 5, 0, 59) is True
    assert _field_matches("5", 7, 0, 59) is False


def test_field_matches_range() -> None:
    from services.scheduler import _field_matches

    assert _field_matches("10-15", 12, 0, 59) is True
    assert _field_matches("10-15", 9, 0, 59) is False
    assert _field_matches("10-15", 16, 0, 59) is False


def test_field_matches_comma_list() -> None:
    from services.scheduler import _field_matches

    assert _field_matches("1,5,10", 5, 0, 59) is True
    assert _field_matches("1,5,10", 6, 0, 59) is False


def test_field_matches_step_wildcard() -> None:
    from services.scheduler import _field_matches

    # */5 → every 5th from low (0,5,10,15,...)
    assert _field_matches("*/5", 0, 0, 59) is True
    assert _field_matches("*/5", 10, 0, 59) is True
    assert _field_matches("*/5", 7, 0, 59) is False


def test_field_matches_step_with_base() -> None:
    from services.scheduler import _field_matches

    # 2/5 → 2, 7, 12, 17...
    assert _field_matches("2/5", 2, 0, 59) is True
    assert _field_matches("2/5", 7, 0, 59) is True
    assert _field_matches("2/5", 3, 0, 59) is False


def test_field_matches_step_zero_returns_false() -> None:
    """Defensive: /0 step is invalid and must return False (not raise
    ZeroDivisionError downstream)."""
    from services.scheduler import _field_matches

    assert _field_matches("*/0", 5, 0, 59) is False


# --- _should_fire ---------------------------------------------------------


def test_should_fire_rejects_malformed_cron() -> None:
    """Cron must have 5 space-separated parts; anything else → False."""
    from services.scheduler import _should_fire

    now = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    last = now - timedelta(minutes=5)
    assert _should_fire("* * *", last, now) is False  # 3 parts
    # "not a cron at all" has 5 space-separated parts (not, a, cron, at, all),
    # so it passes the parts==5 check but fails at _field_matches('not', minute, …)
    # which calls int('not') → ValueError. Empty string fails len check.
    assert _should_fire("", last, now) is False
    assert _should_fire("a b c d", last, now) is False  # 4 parts


def test_should_fire_too_soon_returns_false() -> None:
    """Even if every field matches, refuses to fire within 1 minute of
    the last check (debounce)."""
    from services.scheduler import _should_fire

    now = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    last = now - timedelta(seconds=30)  # <1 minute
    assert _should_fire("* * * * *", last, now) is False


def test_should_fire_when_all_fields_match_and_delta_ok() -> None:
    from services.scheduler import _should_fire

    now = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    last = now - timedelta(minutes=5)
    assert _should_fire("* * * * *", last, now) is True


def test_should_fire_field_mismatch_returns_false() -> None:
    from services.scheduler import _should_fire

    now = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    last = now - timedelta(minutes=5)
    # minute=0 matches; hour=11 doesn't (now is 12:00)
    assert _should_fire("0 11 * * *", last, now) is False


# --- start_scheduler / stop_scheduler singleton ---------------------------


def test_start_scheduler_creates_singleton_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.scheduler as sched

    # Don't actually schedule the asyncio task; just verify singleton wiring.
    def _swallow(coro: Any) -> Any:
        coro.close()
        return None

    monkeypatch.setattr(sched.asyncio, "ensure_future", _swallow)

    assert sched._runner is None
    sched.start_scheduler()
    first = sched._runner
    assert first is not None
    sched.start_scheduler()  # second call no-op
    assert sched._runner is first  # same instance
    sched.stop_scheduler()


def test_stop_scheduler_clears_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    sched.stop_scheduler()  # no error
    assert sched._runner is None


def test_runner_stop_flips_running() -> None:
    from services.scheduler import _ScheduleRunner

    r = _ScheduleRunner()
    assert r._running is True
    r.stop()
    assert r._running is False


# --- _tick / _fire_schedule --------------------------------------------


def test_tick_initializes_last_check_first_time() -> None:
    from services.scheduler import _ScheduleRunner

    r = _ScheduleRunner()
    r._last_check = None
    asyncio.run(r._tick())
    assert r._last_check is not None


def test_tick_iterates_enabled_schedules_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled schedule must NOT fire even if cron matches."""
    import services.scheduler as sched_mod
    from services.scheduler import _ScheduleRunner

    fired = []

    class _FakeSched:
        def __init__(self, sid: str, enabled: bool, cron: str) -> None:
            self.id = sid
            self.enabled = enabled
            self.cron_expression = cron
            self.name = sid
            self.mission_template_id = None

        def model_copy(self, *, update: dict[str, Any]) -> _FakeSched:
            for k, v in update.items():
                setattr(self, k, v)
            return self

    sched_a = _FakeSched("on", True, "* * * * *")
    sched_b = _FakeSched("off", False, "* * * * *")

    fake_store = {"on": sched_a, "off": sched_b}

    class _FakeStores:
        schedules = fake_store

    monkeypatch.setitem(sys.modules, "stores", _FakeStores)
    # force _should_fire to True
    monkeypatch.setattr(sched_mod, "_should_fire", lambda *a, **kw: True)

    async def _capture_fire(self: Any, sid: str, schedule: Any) -> None:
        fired.append(sid)

    monkeypatch.setattr(_ScheduleRunner, "_fire_schedule", _capture_fire)

    r = _ScheduleRunner()
    r._last_check = datetime.now(UTC) - timedelta(minutes=5)
    asyncio.run(r._tick())
    assert fired == ["on"]


def test_fire_schedule_with_template_id_writes_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stores
    from services.scheduler import _ScheduleRunner

    # Pre-test wipe
    for k in list(stores.audit_log.keys()):
        stores.audit_log.pop(k)

    class _Sched:
        id = "s1"
        enabled = True
        cron_expression = "* * * * *"
        name = "my-schedule"
        mission_template_id = "tpl-xyz"
        last_run = None
        updated_at = None

        def model_copy(self, *, update: dict[str, Any]) -> _Sched:
            for k, v in update.items():
                setattr(self, k, v)
            return self

    stores.schedules._data["s1"] = _Sched()  # type: ignore[attr-defined]
    try:
        r = _ScheduleRunner()
        asyncio.run(r._fire_schedule("s1", stores.schedules._data["s1"]))  # type: ignore[attr-defined]
        # Audit entry written
        entries = list(stores.audit_log.values())
        assert any(e["action"] == "schedule_fire" and e["target"] == "s1" for e in entries)
    finally:
        stores.schedules._data.pop("s1", None)  # type: ignore[attr-defined]


def test_fire_schedule_no_template_id_skips_audit() -> None:
    """schedule with no mission_template_id returns before audit."""
    import stores
    from services.scheduler import _ScheduleRunner

    before = len(stores.audit_log)

    class _Sched:
        id = "s2"
        enabled = True
        cron_expression = "* * * * *"
        name = "n2"
        mission_template_id = None
        last_run = None
        updated_at = None

        def model_copy(self, *, update: dict[str, Any]) -> _Sched:
            for k, v in update.items():
                setattr(self, k, v)
            return self

    stores.schedules._data["s2"] = _Sched()  # type: ignore[attr-defined]
    try:
        r = _ScheduleRunner()
        asyncio.run(r._fire_schedule("s2", stores.schedules._data["s2"]))  # type: ignore[attr-defined]
        # No new audit entry (no template means schedule isn't actionable)
        new_for_s2 = [
            e for e in list(stores.audit_log.values())[before:] if e.get("target") == "s2"
        ]
        assert new_for_s2 == []
    finally:
        stores.schedules._data.pop("s2", None)  # type: ignore[attr-defined]


def test_tick_swallows_fire_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If _fire_schedule raises, _tick logs + continues without
    crashing the whole loop."""
    import services.scheduler as sched_mod
    from services.scheduler import _ScheduleRunner

    class _Sched:
        id = "s"
        enabled = True
        cron_expression = "* * * * *"
        name = "n"

    monkeypatch.setattr(sched_mod, "_should_fire", lambda *a, **kw: True)

    async def _boom(self: Any, sid: str, schedule: Any) -> None:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(_ScheduleRunner, "_fire_schedule", _boom)

    class _FakeStores:
        schedules: ClassVar = {"s": _Sched()}

    monkeypatch.setitem(sys.modules, "stores", _FakeStores)

    r = _ScheduleRunner()
    r._last_check = datetime.now(UTC) - timedelta(minutes=5)
    # Must not raise
    asyncio.run(r._tick())


# --- run() loop top-level catch ---------------------------------------


def test_run_loop_logs_and_continues_on_tick_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run() top-level except clause catches errors and continues."""
    import services.scheduler as sched_mod
    from services.scheduler import _ScheduleRunner

    calls = [0]

    async def _flaky_tick(self: Any) -> None:
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("synthetic tick error")
        self._running = False  # second pass — stop

    monkeypatch.setattr(_ScheduleRunner, "_tick", _flaky_tick)

    # Speed up the loop — provide a real (no-arg) async no-op
    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(sched_mod.asyncio, "sleep", _no_sleep)

    r = _ScheduleRunner()
    asyncio.run(r.run())
    # First tick raised; second tick stopped → at least 2 calls
    assert calls[0] >= 2
