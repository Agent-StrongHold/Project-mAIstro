"""System recovery cadence for stranded canonical Hive DAG Runs (#835/#837).

This is not a scheduler and owns no execution lifecycle. It periodically asks
the canonical recovery seam to reconcile only Runs admitted by the legacy Hive
DAG adapter. The canonical Run, continuation, Attempt lease, and fence remain
the sole authorities for whether physical work may start.
"""

from __future__ import annotations

import asyncio
import logging

from services.canonical_dag_runner import recover_stranded_dag_runs

logger = logging.getLogger("hive.dag_recovery")
_INTERVAL_S = 10.0
_task: asyncio.Task[None] | None = None


async def _run() -> None:
    while True:
        try:
            recovered = await recover_stranded_dag_runs()
            if recovered:
                logger.info("legacy_dag_recovery recovered=%d", recovered)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Recovery must remain available after one malformed/temporarily
            # unavailable candidate. The canonical helper keeps invariant
            # failures visible to this boundary; this cadence logs them and
            # retries on the next bounded tick rather than killing the process.
            logger.exception("legacy_dag_recovery_tick_failed")
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
    try:
        await task
    except asyncio.CancelledError:
        pass


def recovery_running() -> bool:
    return _task is not None and not _task.done()


__all__ = ["recovery_running", "start_dag_recovery", "stop_dag_recovery"]
