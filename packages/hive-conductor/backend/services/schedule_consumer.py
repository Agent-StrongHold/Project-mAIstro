"""Consumer cadence for admitted schedule Runs (#1243, ADR-082826-b601).

The configured scheduler producer (`services/scheduler.py`) hands its due
occurrences to `ScheduleRunAdmitter`, which admits each one straight to
`QUEUED` — "a schedule Run's admission IS its submission" (#251). ADR-082826-b601
fixes what executes such a Run — `Container.execute_admitted_runs`, plus
`Container.resume_parked_runs` for a yielded pause (SPEC-082926-a44e) — and
deliberately leaves the cadence to the product: "Products schedule the tick;
the library never starts work on import." No shipped process scheduled it, so
every admitted schedule Run sat `QUEUED` forever; the producer tick the
lifespan starts was admitting work nothing would ever execute.

This module is that product wiring. It is a cadence, not a second consumer:
every execution decision is still the Container's canonical tick, claimed by
the `QUEUED → RUNNING` transition, executed through the one
`ScheduleAttemptExecutor` spine. Without a wired core bridge there is no
canonical Run store in this process, so there is nothing to drain and the tick
is a no-op — the stub/demo path keeps the behavior it had, exactly like
`recover_stranded_dag_runs` returns 0 without a Container.

Disabling (`SCHEDULE_CONSUMER_INTERVAL_S <= 0`) is a loud degraded mode, and
the switch is loop-honoring: `consumer_disabled` is the one effective-interval
answer for every path that would execute admitted Runs — this cadence and the
producer scheduler's own tick drain (`_ScheduleRunner._tick`) alike — so the
off switch truly leaves admitted Runs QUEUED in this process. The producer
keeps admitting them, so a warning is logged at startup rather than leaving
silence that looks like a closed loop.

Each tick ensures the two halves are running as independent tasks (at most one
of each in flight) instead of awaiting them inline: node work inside a claimed
Run executes through the canonical `ScheduleAttemptExecutor` with no default
timeout, so an awaited drain would starve both `resume_parked_runs` and every
later cadence iteration behind one slow external integration (Codex P1,
#1260). The poll stays bounded; each half carries its own completion and
failure logs.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

logger = logging.getLogger("hive.schedule_consumer")

_task: asyncio.Task[None] | None = None
_drain_task: asyncio.Task[int] | None = None
_wake_task: asyncio.Task[int] | None = None

__all__ = [
    "consumer_disabled",
    "start_schedule_consumer",
    "stop_schedule_consumer",
    "tick_schedule_consumer",
]


def _interval_s() -> int:
    """The configured cadence, in seconds. <=0 means disabled."""
    from config import get_settings

    return int(get_settings().schedule_consumer_interval_s)


def consumer_disabled() -> bool:
    """The `SCHEDULE_CONSUMER_INTERVAL_S <= 0` off switch, read live.

    The one effective-interval answer shared by every path that would execute
    admitted schedule Runs — this cadence's start/loop and the producer
    scheduler's drain (`_ScheduleRunner._tick`) — so the switch means the same
    thing wherever work could start. Reading it per decision rather than once
    at start lets an operator disable a running process between ticks.
    """
    return _interval_s() <= 0


def _wired_container() -> Any:
    """The core Container behind the engine's AgentPort, or None.

    A None answer is the standalone/demo shape: without the bridge there is no
    canonical Run store in this process, so there is no admitted work to drain.
    Resolved per tick rather than captured at start, so a cadence that began
    before the bridge finished binding still finds it.
    """
    from services.engine import get_engine

    engine = get_engine()
    return getattr(getattr(engine, "agent_port", None), "container", None)


async def _drain_once(container: Any) -> int:
    """One drain half: execute admitted Runs, isolated on its own task.

    A failure is reported and answered as 0 — the next bounded tick spawns a
    fresh drain; a cancellation is shutdown and propagates.
    """
    try:
        drained = await container.execute_admitted_runs()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("schedule_consumer_drain_failed")
        return 0
    if drained:
        logger.info("schedule_consumer_drain drained=%d", drained)
    return drained


async def _wake_once(container: Any) -> int:
    """One wake half: resume parked Runs whose wait is over, on its own task.

    Same discipline as the drain half: the cadence never awaits this inline,
    so a slow resumed node cannot push later polls — and the resumptions they
    owe — into the same starvation the drain await had.
    """
    try:
        resumed = await container.resume_parked_runs()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("schedule_consumer_wake_failed")
        return 0
    if resumed:
        logger.info("schedule_consumer_wake resumed=%d", resumed)
    return resumed


async def tick_schedule_consumer() -> None:
    """Ensure both consumer halves are in flight against the wired Container.

    Returns without awaiting either half: each half runs in its own task, at
    most one drain and one wake at a time (their claims — the atomic
    `QUEUED → RUNNING` transition and the parked-run claim — are the canonical
    mutexes, and serializing each half avoids wasted churn), so node work
    inside a claimed Run cannot starve the sibling half or a later cadence
    iteration. The halves answer different questions about the same store, so
    one failing never silences the other; the next bounded tick retries
    whichever has finished. Without a Container this is a no-op: nothing was
    admitted onto a canonical spine here, so there is nothing to consume.
    """
    global _drain_task, _wake_task
    container = _wired_container()
    if container is None:
        return
    if _drain_task is None or _drain_task.done():
        _drain_task = asyncio.create_task(
            _drain_once(container), name="hive-schedule-consumer-drain"
        )
    if _wake_task is None or _wake_task.done():
        _wake_task = asyncio.create_task(_wake_once(container), name="hive-schedule-consumer-wake")


async def _run() -> None:
    while True:
        try:
            await tick_schedule_consumer()
        except asyncio.CancelledError:
            raise
        except Exception:
            # E.g. the engine was never started in this process. The cadence is
            # a process-lifetime task; one bad lookup must not kill it, and the
            # next tick re-reads whatever the process is wired with then.
            logger.exception("schedule_consumer_tick_failed")
        if consumer_disabled():
            # Disabled between ticks: park until cancelled rather than spin.
            # `stop` remains the way out; the startup warning already said the
            # producer above this cadence is still admitting.
            await asyncio.Event().wait()
        await asyncio.sleep(_interval_s())


async def start_schedule_consumer() -> None:
    """Start one process-local consumer cadence. Idempotent.

    Called from `EngineService.start`, beside `start_dag_recovery`, so the
    cadence begins only once the core bridge has attempted to establish the
    canonical Run store the Container ticks read.
    """
    global _task
    if _task is not None and not _task.done():
        return
    if consumer_disabled():
        logger.warning(
            "schedule_consumer_disabled — SCHEDULE_CONSUMER_INTERVAL_S <= 0; "
            "admitted schedule Runs will stay QUEUED in this process"
        )
        return
    _task = asyncio.create_task(_run(), name="hive-schedule-consumer")
    logger.info("schedule_consumer_started")


async def stop_schedule_consumer() -> None:
    """Cancel and join the cadence and its in-flight halves on Engine shutdown.

    Cancelling a half mid-execution is the documented process-loss shape: the
    Run stays claimed behind its leased Attempt and ordinary recovery owns it.
    """
    global _task, _drain_task, _wake_task
    tasks = (_task, _drain_task, _wake_task)
    _task = None
    _drain_task = None
    _wake_task = None
    for task in tasks:
        if task is None:
            continue
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
