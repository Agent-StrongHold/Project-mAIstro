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

Disabling (`SCHEDULE_CONSUMER_INTERVAL_S <= 0`) is a loud degraded mode: the
producer keeps admitting QUEUED Runs that nothing will execute, so a warning is
logged at startup rather than leaving silence that looks like a closed loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

logger = logging.getLogger("hive.schedule_consumer")

_task: asyncio.Task[None] | None = None

__all__ = ["start_schedule_consumer", "stop_schedule_consumer", "tick_schedule_consumer"]


def _interval_s() -> int:
    """The configured cadence, in seconds. <=0 means disabled."""
    from config import get_settings

    return int(get_settings().schedule_consumer_interval_s)


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


async def tick_schedule_consumer() -> tuple[int, int]:
    """Run both consumer halves once against the wired Container.

    Returns ``(drained, resumed)``. Without a Container this is ``(0, 0)``:
    nothing was admitted onto a canonical spine here, so there is nothing to
    consume. The halves are isolated within a tick — the drain and the wake
    answer different questions about the same store, so one failing must not
    silence the other; the next bounded tick retries whichever failed.
    """
    container = _wired_container()
    if container is None:
        return 0, 0
    drained = 0
    resumed = 0
    try:
        drained = await container.execute_admitted_runs()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("schedule_consumer_drain_failed")
    try:
        resumed = await container.resume_parked_runs()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("schedule_consumer_wake_failed")
    return drained, resumed


async def _run() -> None:
    while True:
        try:
            drained, resumed = await tick_schedule_consumer()
            if drained or resumed:
                logger.info("schedule_consumer_tick drained=%d resumed=%d", drained, resumed)
        except asyncio.CancelledError:
            raise
        except Exception:
            # E.g. the engine was never started in this process. The cadence is
            # a process-lifetime task; one bad lookup must not kill it, and the
            # next tick re-reads whatever the process is wired with then.
            logger.exception("schedule_consumer_tick_failed")
        if _interval_s() <= 0:
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
    if _interval_s() <= 0:
        logger.warning(
            "schedule_consumer_disabled — SCHEDULE_CONSUMER_INTERVAL_S <= 0; "
            "admitted schedule Runs will stay QUEUED in this process"
        )
        return
    _task = asyncio.create_task(_run(), name="hive-schedule-consumer")
    logger.info("schedule_consumer_started")


async def stop_schedule_consumer() -> None:
    """Cancel and join the consumer cadence during Engine shutdown."""
    global _task
    task = _task
    _task = None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
