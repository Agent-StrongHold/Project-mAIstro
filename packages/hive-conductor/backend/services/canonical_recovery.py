"""System cadence for the engine Container's canonical recovery ticks (#62).

``maistro-core`` exposes its recovery sweeps as bounded, idempotent,
operator-scheduled ticks and never starts them itself (ADR-019). Hive is the
operator: this cadence ticks the three that had no production caller, so
expired Attempt leases (task and #1170 chat) are reclaimed, chat admissions
stranded before their first NodeRun are compensated, and ``RESUME_ON_ELAPSED``
pauses get a timer waker. Ticks are at least ``_INTERVAL_S`` apart: a slow
resume delays the next one rather than overlapping it. It owns no lifecycle; the Container's Run, Attempt
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
#: How long shutdown waits for an in-flight tick before cancelling it. Core
#: records a cancelled Attempt as a *requested* cancellation, which terminalizes
#: its NodeRun, so cancelling a resume mid-node would turn a graceful restart
#: into a permanent CANCELLED where a crash would only have parked the Run.
_STOP_GRACE_S = 30.0
_task: asyncio.Task[None] | None = None
_stopping: asyncio.Event | None = None


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


async def tick_canonical_recovery(stopping: asyncio.Event | None = None) -> None:
    """Run each recovery half once against the booted Container, if any.

    Once ``stopping`` is set no further half starts, so shutdown only ever
    waits for the half already running.
    """
    container = _container()
    if container is None:
        return
    for name, half in _halves(container):
        if stopping is not None and stopping.is_set():
            return
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


async def _run(stopping: asyncio.Event) -> None:
    while not stopping.is_set():
        await tick_canonical_recovery(stopping)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stopping.wait(), timeout=_INTERVAL_S)


def start_canonical_recovery() -> None:
    """Start one process-local recovery cadence. Idempotent."""
    global _task, _stopping
    if _task is not None and not _task.done():
        return
    _stopping = asyncio.Event()
    _task = asyncio.create_task(_run(_stopping), name="hive-canonical-recovery")


async def stop_canonical_recovery() -> None:
    """Drain, then join, the recovery cadence during Engine shutdown.

    The in-flight half is allowed to finish within ``_STOP_GRACE_S``; only a
    tick still running past that is cancelled.
    """
    global _task, _stopping
    task, stopping = _task, _stopping
    _task = _stopping = None
    if task is None or task.done():
        return
    if task.get_loop() is not asyncio.get_running_loop():
        # Started on a loop that is no longer running (an engine restarted on a
        # fresh loop); there is nothing left on it to drain or join.
        task.cancel()
        return
    if stopping is not None:
        stopping.set()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=_STOP_GRACE_S)
    except asyncio.CancelledError:
        if not task.cancelled():
            raise
    except TimeoutError:
        logger.warning(
            "canonical_recovery tick still running after %.0fs; cancelling it", _STOP_GRACE_S
        )
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


__all__ = ["start_canonical_recovery", "stop_canonical_recovery", "tick_canonical_recovery"]
