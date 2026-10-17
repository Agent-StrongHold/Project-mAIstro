"""System recovery cadence for stranded and due canonical Evolve Runs (#1064).

This is not a scheduler and owns no execution lifecycle. It periodically asks
the canonical recovery seam to reconcile only Runs admitted by the Evolve
adapter (``services.evolution_graph``): bootstrap recovery for QUEUED
admissions stranded around checkpoint 1, and timed wakeup for continuations
whose persisted ``resume_at`` has elapsed. The canonical Run, continuation,
Attempt lease, and fence remain the sole authorities for whether physical
work may start; this cadence only asks them to look again.

Before this module existed, a process lost after admitting an Evolve Run left
it QUEUED or RUNNING forever -- nothing in this app ever looked at it again.
Mirrors ``services.dag_recovery`` structurally; kept as a separate module
(rather than folded into it) because Evolve's node resolver has real
domain-state prerequisites that the legacy DAG resolver does not, and because
that resolver already documents its own recovery-vs-block trade-off in
``services.evolution_graph._recovery_resolver``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from services.evolution_graph import recover_stranded_evolution_runs, wake_due_evolution_runs

logger = logging.getLogger("hive.evolution_recovery")
_INTERVAL_S = 10.0
_task: asyncio.Task[None] | None = None


async def _run() -> None:
    while True:
        try:
            recovered = await recover_stranded_evolution_runs()
            if recovered:
                logger.info("evolution_recovery recovered=%d", recovered)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Recovery must remain available after one malformed/temporarily
            # unavailable candidate. The canonical helper keeps invariant
            # failures visible to this boundary; this cadence logs them and
            # retries on the next bounded tick rather than killing the process.
            logger.exception("evolution_recovery_tick_failed")
        try:
            woken = await wake_due_evolution_runs()
            if woken:
                logger.info("evolution_wakeup resumed=%d", woken)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Same discipline as the bootstrap half: one bad candidate must not
            # silence the tick or the other half. The canonical seam re-raises
            # only for a record still due after failing; the next tick retries.
            logger.exception("evolution_wakeup_tick_failed")
        await asyncio.sleep(_INTERVAL_S)


def start_evolution_recovery() -> None:
    """Start one process-local recovery tick. Idempotent."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_run(), name="hive-evolution-recovery")


async def stop_evolution_recovery() -> None:
    """Cancel and join the recovery tick during Engine shutdown."""
    global _task
    task = _task
    _task = None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


__all__ = ["start_evolution_recovery", "stop_evolution_recovery"]
