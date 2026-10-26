"""#290: the scheduler and its timezone database are visible health signals.

The shipped image resolves every schedule zone — including ``UTC`` — through
``zoneinfo.ZoneInfo``, and the lifespan swallows ``start_scheduler`` failure
by design: a zone-less image used to look healthy while scheduling was
silently down. These tests pin the repair: scheduler liveness and tz-database
resolution are reported by both probes, a broken zone database degrades
/health with an actionable diagnostic, and readiness carries the same checks
without leaving its api+workspace keys.
"""

from __future__ import annotations

import contextlib
import zoneinfo
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_scheduler_singleton():
    import services.scheduler as sched

    prev_runner, prev_error = sched._runner, sched._start_error
    sched._runner, sched._start_error = None, None
    yield
    if sched._runner is not None:
        sched.stop_scheduler()
    sched._runner, sched._start_error = prev_runner, prev_error


# --- services.scheduler.scheduler_status -------------------------------------


def test_scheduler_status_reports_never_started() -> None:
    import services.scheduler as sched

    status = sched.scheduler_status()
    assert status["running"] is False
    assert status["error"] is None


async def test_scheduler_status_running_with_live_loop() -> None:
    """A started scheduler reports a live loop task and no error.

    Runs the real ``start_scheduler`` on the test's event loop: without a
    canonical container (the in-memory store context this suite runs in)
    the loop's first action is stamping ``_last_check`` and then sleeping
    until the next sweep, so the status read below sees the same live-task
    state production presents between sweeps.
    """
    import asyncio
    from datetime import datetime

    import services.scheduler as sched

    sched.start_scheduler()
    try:
        # Yield so the loop task takes its first slice: run() stamps
        # _last_check before its first awaited sweep sleep.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        status = sched.scheduler_status()
        assert status["running"] is True
        assert status["error"] is None
        assert "last_tick_at" in status
        datetime.fromisoformat(status["last_tick_at"])  # a real instant
    finally:
        task = sched._runner.task if sched._runner is not None else None
        sched.stop_scheduler()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def test_scheduler_start_failure_is_recorded_and_reraised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A swallowed lifespan start leaves an actionable trace in status."""
    import services.scheduler as sched

    def _explode() -> None:
        raise RuntimeError("boom while wiring stores")

    monkeypatch.setattr(sched, "_ScheduleRunner", _explode)
    with pytest.raises(RuntimeError, match="boom"):
        sched.start_scheduler()
    status = sched.scheduler_status()
    assert status["running"] is False
    assert status["error"] == "RuntimeError: boom while wiring stores"


def test_scheduler_status_reports_crashed_loop_task() -> None:
    """A loop task that finished with an exception is not reported as running.

    `scheduler_status` only inspects the task synchronously, so a completed
    stand-in exercises the same `done()/exception()` read the real crashed
    task presents.
    """
    import services.scheduler as sched

    runner = sched._ScheduleRunner()
    runner.task = SimpleNamespace(  # type: ignore[assignment]
        done=lambda: True,
        exception=lambda: RuntimeError("loop exploded"),
    )
    sched._runner = runner
    status = sched.scheduler_status()
    assert status["running"] is False
    assert status["error"] is not None and "loop exploded" in status["error"]


# --- timezone database probe -------------------------------------------------


def test_timezone_probe_available_records_source() -> None:
    from routes.health import _timezone_database_state

    state = _timezone_database_state()
    assert state["status"] == "available"
    assert state["error"] is None
    assert state["source"]


def test_timezone_probe_unavailable_when_zone_database_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No zone database at all: UTC itself fails, and the probe says so."""
    from routes import health as health_module

    def _no_zones(key: str) -> None:
        raise zoneinfo.ZoneInfoNotFoundError(f"No time zone found with key {key}")

    monkeypatch.setattr(health_module, "_probe_zoneinfo", _no_zones)
    state = health_module._timezone_database_state()
    assert state["status"] == "unavailable"
    assert "UTC" in state["error"]
    assert "tzdata" in state["error"]  # the actionable fix is named


def test_timezone_probe_names_missing_pythontzpath(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The image pins PYTHONTZPATH at the venv wheel; a gap is diagnosed as such."""
    monkeypatch.setenv("PYTHONTZPATH", "/app/venv/lib/python3.13/site-packages/tzdata/zoneinfo")
    monkeypatch.setattr("os.path.isdir", lambda p: False)
    from routes.health import _timezone_database_state

    state = _timezone_database_state()
    assert state["status"] == "unavailable"
    assert "PYTHONTZPATH" in state["error"]
    assert "tzdata" in state["error"]


def test_timezone_probe_partial_database_must_not_pass_on_utc_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database that answers UTC but lost its regions is still broken."""
    from routes import health as health_module

    calls: list[str] = []

    def _half_database(key: str) -> None:
        calls.append(key)
        if key != "UTC":
            raise zoneinfo.ZoneInfoNotFoundError(f"No time zone found with key {key}")

    monkeypatch.setattr(health_module, "_probe_zoneinfo", _half_database)
    state = health_module._timezone_database_state()
    assert calls == ["UTC", "America/New_York"]
    assert state["status"] == "unavailable"


# --- endpoints ---------------------------------------------------------------


def test_health_degraded_when_zone_database_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    from routes import health as health_module

    monkeypatch.setattr(
        health_module,
        "_timezone_database_state",
        lambda: {
            "status": "unavailable",
            "source": "system:tzpath",
            "error": "no zone database found; zone resolution failed "
            "(ZoneInfoNotFoundError: 'No time zone found with key UTC'); "
            "schedules cannot fire. Install the tzdata wheel in the image "
            "or the OS tzdata package",
        },
    )
    data = client.get("/health").json()
    assert data["status"] == "ok"  # liveness is not readiness
    assert data["tz_database"]["status"] == "unavailable"
    assert "UTC" in data["tz_database"]["error"]
    assert data["degraded"] is True


def test_health_degraded_when_scheduler_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from routes import health as health_module

    monkeypatch.setattr(
        health_module,
        "_scheduler_state",
        lambda: {"running": False, "error": "RuntimeError: no event loop"},
    )
    data = client.get("/health").json()
    assert data["scheduler"]["running"] is False
    assert "no event loop" in data["scheduler"]["error"]
    assert data["degraded"] is True


def test_health_not_degraded_when_scheduler_and_zones_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from routes import health as health_module

    # Everything else the `degraded` fold reads must say healthy too — same
    # arrangement as test_api.py's not-degraded test — so the assertion is
    # specifically about the scheduler/tz signals, not the other probes.
    monkeypatch.setenv("LITELLM_API_BASE", "http://gateway.example")
    monkeypatch.setattr(
        health_module,
        "_memory_decay_state",
        lambda: {"enabled": True, "state": "running"},
    )
    monkeypatch.setattr(health_module, "_log_redaction_active", lambda: True)
    monkeypatch.setattr(
        health_module,
        "_scheduler_state",
        lambda: {"running": True, "error": None, "last_tick_at": "2026-01-01T00:00:00+00:00"},
    )
    monkeypatch.setattr(
        health_module,
        "_timezone_database_state",
        lambda: {"status": "available", "source": "tzdata-wheel:2026.3", "error": None},
    )
    data = client.get("/health").json()
    assert data["scheduler"]["running"] is True
    assert data["tz_database"]["status"] == "available"
    assert data["tz_database"]["source"] == "tzdata-wheel:2026.3"
    assert data["degraded"] is False


def test_health_ready_carries_scheduler_and_tz_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Visible in `checks`/`warnings`, but ready keeps its own keys."""
    from routes import health as health_module

    monkeypatch.setattr(
        health_module,
        "_scheduler_state",
        lambda: {"running": True, "error": None},
    )
    monkeypatch.setattr(
        health_module,
        "_timezone_database_state",
        lambda: {
            "status": "unavailable",
            "source": "system:tzpath",
            "error": "zone resolution failed; schedules cannot fire",
        },
    )
    body = client.get("/health/ready")
    assert body.status_code == 200  # readiness stays keyed on api+workspace
    payload = body.json()
    assert payload["checks"]["tz_database"] is False
    assert payload["checks"]["scheduler"] is True
    assert payload["warnings"] == ["zone resolution failed; schedules cannot fire"]


def test_health_ready_warnings_empty_when_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    from routes import health as health_module

    monkeypatch.setattr(
        health_module,
        "_timezone_database_state",
        lambda: {"status": "available", "source": "tzdata-wheel:2026.3", "error": None},
    )
    payload = client.get("/health/ready").json()
    assert payload["checks"]["tz_database"] is True
    assert payload["warnings"] == []
