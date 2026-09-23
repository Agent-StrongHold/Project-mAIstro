"""System cadence for the engine Container's canonical recovery ticks (#62).

``maistro-core`` exposes its recovery sweeps as bounded, idempotent,
operator-scheduled ticks and never starts them itself (ADR-019). Hive is the
operator: this cadence ticks the three that had no production caller, so
expired Attempt leases (task and #1170 chat) are reclaimed, chat admissions
stranded before their first NodeRun are compensated, and ``RESUME_ON_ELAPSED``
pauses get a timer waker. It owns no lifecycle; the Container's Run, Attempt
lease and fence decide what each tick may do. ``execute_admitted_runs`` stays
with the schedule runner, and legacy DAG recovery with ``dag_recovery``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from services.dag_agents import _container

logger = logging.getLogger("hive.canonical_recovery")
_INTERVAL_S = 10.0
_LIMIT = 100
_task: asyncio.Task[None] | None = None


def _halves(container: Any) -> tuple[tuple[str, Callable[[], Awaitable[int]]], ...]:
    return (
        (
            "abandoned_attempts",
            lambda: container.recover_abandoned_attempts(limit=_LIMIT),
        ),
        (
            "stranded_chat_admissions",
            lambda: container.recover_stranded_chat_admissions(limit=_LIMIT),
        ),
        ("parked_runs", lambda: container.resume_parked_runs(limit=_LIMIT)),
    )


async def tick_canonical_recovery() -> None:
    """Run each recovery half once against the booted Container, if any."""
    container = _container()
    if container is None:
        return
    for name, half in _halves(container):
        try:
            settled = await half()
            if settled:
                logger.info("canonical_recovery %s=%d", name, settled)
        except asyncio.CancelledError:
            raise
        except Exception:
            # One half failing -- a store outage, an invariant violation, or a
            # recovery Event that could not be delivered -- must not silence the
            # other halves or the cadence; the next tick retries idempotently.
            logger.exception("canonical_recovery_%s_tick_failed", name)


async def _run() -> None:
    while True:
        await tick_canonical_recovery()
        await asyncio.sleep(_INTERVAL_S)


def start_canonical_recovery() -> None:
    """Start one process-local recovery cadence. Idempotent."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_run(), name="hive-canonical-recovery")


async def stop_canonical_recovery() -> None:
    """Cancel and join the recovery cadence during Engine shutdown."""
    global _task
    task = _task
    _task = None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


__all__ = ["start_canonical_recovery", "stop_canonical_recovery", "tick_canonical_recovery"]
