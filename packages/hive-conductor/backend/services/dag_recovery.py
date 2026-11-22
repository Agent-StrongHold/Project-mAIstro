"""System recovery cadence for stranded and due canonical Hive DAG Runs (#835/#837, #62).

This is not a scheduler and owns no execution lifecycle. It periodically asks
the canonical recovery seam to reconcile only Runs admitted by the legacy Hive
DAG adapter or, as durable Graphs, by the schedule-fired registered-DAG path:
bootstrap recovery for QUEUED admissions stranded around checkpoint 1, and
timed wakeup for continuations whose persisted ``resume_at`` has elapsed. The
canonical Run, continuation, Attempt lease, and fence remain the sole
authorities for whether physical work may start.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from services.canonical_dag_runner import recover_stranded_dag_runs, wake_due_dag_runs
from services.registered_dag_recovery import (
    recover_stranded_registered_dag_runs,
    wake_due_registered_dag_runs,
)

logger = logging.getLogger("hive.dag_recovery")
_INTERVAL_S = 10.0
_task: asyncio.Task[None] | None = None


async def _tick_half(name: str, counted: str, half: Callable[[], Awaitable[int]]) -> None:
    try:
        count = await half()
        if count:
            logger.info("%s %s=%d", name, counted, count)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Recovery must remain available after one malformed/temporarily
        # unavailable candidate, and one half failing must not silence the
        # others in the same tick. The canonical seams keep invariant failures
        # visible to this boundary; the cadence logs them and retries on the
        # next bounded tick rather than killing the process.
        logger.exception("%s_tick_failed", name)


async def _run() -> None:
    while True:
        await _tick_half("legacy_dag_recovery", "recovered", recover_stranded_dag_runs)
        await _tick_half("legacy_dag_wakeup", "resumed", wake_due_dag_runs)
        await _tick_half(
            "registered_dag_recovery", "recovered", recover_stranded_registered_dag_runs
        )
        await _tick_half("registered_dag_wakeup", "resumed", wake_due_registered_dag_runs)
        await asyncio.sleep(_INTERVAL_S)


def start_dag_recovery() -> None:
    """Start one process-local recovery tick. Idempotent."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_run(), name="hive-legacy-dag-recovery")


async def stop_dag_recovery() -> None:
    """Cancel and join the recovery tick during Engine shutdown."""
    global _task
    task = _task
    _task = None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


__all__ = ["start_dag_recovery", "stop_dag_recovery"]
