"""Cadence proof for the Evolve recovery driver (#1064).

Mirrors ``test_dag_recovery.py``'s cadence tests for the legacy DAG driver:
the cadence itself owns no execution lifecycle, only ticking the canonical
recovery seam and surviving one bad tick without dying.
"""

from __future__ import annotations

import asyncio
import logging

import pytest


@pytest.mark.asyncio
async def test_recovery_cadence_starts_ticks_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.evolution_recovery as recovery_driver

    ticked = asyncio.Event()

    async def _recover() -> int:
        ticked.set()
        return 0

    await recovery_driver.stop_evolution_recovery()
    monkeypatch.setattr(recovery_driver, "recover_stranded_evolution_runs", _recover)
    monkeypatch.setattr(recovery_driver, "wake_due_evolution_runs", _recover)
    monkeypatch.setattr(recovery_driver, "_INTERVAL_S", 3600.0)

    recovery_driver.start_evolution_recovery()
    await asyncio.wait_for(ticked.wait(), timeout=1.0)
    assert recovery_driver._task is not None
    assert not recovery_driver._task.done()

    await recovery_driver.stop_evolution_recovery()
    assert recovery_driver._task is None


@pytest.mark.asyncio
async def test_recovery_cadence_survives_a_failing_tick_and_logs_recoveries(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One malformed candidate must not kill the cadence, and a productive
    tick is reported, not swallowed."""
    import services.evolution_recovery as recovery_driver

    ticks = {"count": 0}
    recovered = asyncio.Event()

    async def _tick() -> int:
        ticks["count"] += 1
        if ticks["count"] == 1:
            raise ValueError("malformed candidate")
        recovered.set()
        return 4

    async def _noop() -> int:
        return 0

    await recovery_driver.stop_evolution_recovery()
    monkeypatch.setattr(recovery_driver, "recover_stranded_evolution_runs", _tick)
    monkeypatch.setattr(recovery_driver, "wake_due_evolution_runs", _noop)
    monkeypatch.setattr(recovery_driver, "_INTERVAL_S", 0.001)

    recovery_driver.start_evolution_recovery()
    with caplog.at_level(logging.INFO, logger="hive.evolution_recovery"):
        await asyncio.wait_for(recovered.wait(), timeout=5.0)

    assert any("evolution_recovery_tick_failed" in r.message for r in caplog.records)
    assert any("recovered=4" in r.message for r in caplog.records)

    await recovery_driver.stop_evolution_recovery()
    assert recovery_driver._task is None


@pytest.mark.asyncio
async def test_recovery_cadence_survives_a_failing_wakeup_tick_and_logs_resumptions(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Mirrors the bootstrap-recovery cadence test above, for the timed-wakeup
    half: one malformed wakeup candidate must not kill the cadence either
    (own except/log, independent of the bootstrap half's), and a productive
    wakeup tick is reported, not swallowed."""
    import services.evolution_recovery as recovery_driver

    ticks = {"count": 0}
    resumed = asyncio.Event()

    async def _noop() -> int:
        return 0

    async def _tick() -> int:
        ticks["count"] += 1
        if ticks["count"] == 1:
            raise ValueError("malformed wakeup candidate")
        resumed.set()
        return 2

    await recovery_driver.stop_evolution_recovery()
    monkeypatch.setattr(recovery_driver, "recover_stranded_evolution_runs", _noop)
    monkeypatch.setattr(recovery_driver, "wake_due_evolution_runs", _tick)
    monkeypatch.setattr(recovery_driver, "_INTERVAL_S", 0.001)

    recovery_driver.start_evolution_recovery()
    with caplog.at_level(logging.INFO, logger="hive.evolution_recovery"):
        await asyncio.wait_for(resumed.wait(), timeout=5.0)

    assert any("evolution_wakeup_tick_failed" in r.message for r in caplog.records)
    assert any("resumed=2" in r.message for r in caplog.records)

    await recovery_driver.stop_evolution_recovery()
    assert recovery_driver._task is None


@pytest.mark.asyncio
async def test_run_propagates_cancellation_from_bootstrap_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``CancelledError`` surfacing from the bootstrap-recovery half (the
    tick's own await being cancelled, e.g. by ``stop_evolution_recovery``
    tearing down the task mid-call) must propagate out of ``_run`` rather
    than being swallowed by the broad ``except Exception`` below it --
    otherwise cancellation could never actually stop the cadence."""
    import services.evolution_recovery as recovery_driver

    async def _cancel() -> int:
        raise asyncio.CancelledError()

    async def _noop() -> int:
        return 0

    monkeypatch.setattr(recovery_driver, "recover_stranded_evolution_runs", _cancel)
    monkeypatch.setattr(recovery_driver, "wake_due_evolution_runs", _noop)

    with pytest.raises(asyncio.CancelledError):
        await recovery_driver._run()


@pytest.mark.asyncio
async def test_run_propagates_cancellation_from_wakeup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same discipline as the bootstrap half, for the timed-wakeup half: its
    own ``CancelledError`` guard must also re-raise rather than fall through
    to the wakeup half's ``except Exception``."""
    import services.evolution_recovery as recovery_driver

    async def _noop() -> int:
        return 0

    async def _cancel() -> int:
        raise asyncio.CancelledError()

    monkeypatch.setattr(recovery_driver, "recover_stranded_evolution_runs", _noop)
    monkeypatch.setattr(recovery_driver, "wake_due_evolution_runs", _cancel)

    with pytest.raises(asyncio.CancelledError):
        await recovery_driver._run()


@pytest.mark.asyncio
async def test_starting_the_recovery_cadence_twice_keeps_one_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution_recovery as recovery_driver

    async def _noop() -> int:
        return 0

    await recovery_driver.stop_evolution_recovery()
    monkeypatch.setattr(recovery_driver, "recover_stranded_evolution_runs", _noop)
    monkeypatch.setattr(recovery_driver, "wake_due_evolution_runs", _noop)
    monkeypatch.setattr(recovery_driver, "_INTERVAL_S", 3600.0)

    recovery_driver.start_evolution_recovery()
    first_task = recovery_driver._task
    recovery_driver.start_evolution_recovery()
    assert recovery_driver._task is first_task

    await recovery_driver.stop_evolution_recovery()
    assert recovery_driver._task is None
