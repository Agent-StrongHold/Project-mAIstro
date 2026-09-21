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
