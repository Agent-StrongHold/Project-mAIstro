"""SPEC-013: 1kHz Reactor Loop — event-driven runtime.

Replaces the heartbeat system with a high-throughput event loop. Events
are screened by the Bouncer, dispatched to registered handlers, and all
state mutations route through ``state_submit()`` onto the owning
``maistro.state.State`` singleton writer (#1178): the reactor never opens a
writer of its own.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sqlite3
import time
import warnings
from collections.abc import Awaitable, Callable
from typing import Any

from maistro.state import State

_REACTOR_LOG_MIGRATION = "CREATE TABLE IF NOT EXISTS reactor_log (event_name TEXT)"

logger = logging.getLogger(__name__)


class Reactor:
    """Event-driven reactor loop with Bouncer screening and state integration."""

    def __init__(
        self,
        handler_timeout_ms: int = 5000,
        grace_period_seconds: float = 5.0,
        max_queue_depth: int = 10000,
        state_db_path: str | None = None,
        state: State | None = None,
    ) -> None:
        self._handlers: dict[str, Callable[[Any], Awaitable[None]]] = {}
        self._bouncer: Callable[[Any], Awaitable[bool]] | None = None
        self._handler_timeout = handler_timeout_ms / 1000.0
        self._grace_period = grace_period_seconds
        self._max_queue_depth = max_queue_depth
        self._event_queue: asyncio.Queue[tuple[str, dict[str, Any]]] | None = None
        self._loop_task: asyncio.Task[None] | None = None
        self._running = False
        self._in_flight: set[asyncio.Task[None]] = set()
        self._alerts: list[str] = []
        self._cpu_samples: list[float] = []
        self._last_cpu_sample: tuple[float, float] = (0.0, 0.0)
        self._state = state
        self._owned_state_path = self._deprecated_state_path(state, state_db_path)
        self._intervals: dict[str, asyncio.Task[None]] = {}
        self._tick_count = 0

    @staticmethod
    def _deprecated_state_path(state: State | None, state_db_path: str | None) -> str | None:
        if state_db_path is None:
            return None
        if state is not None:
            raise ValueError(
                "Reactor takes either state= or the deprecated state_db_path=, not both: "
                "two State writers on one database is the split #1178 removed"
            )
        warnings.warn(
            "Reactor(state_db_path=...) is deprecated; pass the owning State via state=",
            DeprecationWarning,
            stacklevel=3,
        )
        return state_db_path

    @property
    def is_running(self) -> bool:
        return self._running

    def register_source(self, name: str, handler: Callable[[Any], Awaitable[None]]) -> None:
        self._handlers[name] = handler

    def set_bouncer(self, bouncer: Callable[[Any], Awaitable[bool]]) -> None:
        self._bouncer = bouncer

    async def start(self) -> None:
        if self._running:
            return
        if self._owned_state_path is not None:
            # A closed State cannot reopen its writer, so each start owns a fresh one.
            self._state = State(db_path=self._owned_state_path)
        if self._state is not None:
            try:
                self._state.run_migration("reactor_log_001", _REACTOR_LOG_MIGRATION)
            except Exception:
                self._release_owned_state()
                raise
        self._event_queue = asyncio.Queue(maxsize=self._max_queue_depth)
        self._running = True
        self._last_cpu_sample = time.monotonic(), os.times().user
        self._loop_task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        await self._cancel_intervals()
        await self._drain_in_flight()
        await self._cancel_loop()
        self._release_owned_state()

    def _release_owned_state(self) -> None:
        if self._owned_state_path is not None and self._state is not None:
            self._state.close()
            self._state = None

    async def _cancel_intervals(self) -> None:
        for task in self._intervals.values():
            task.cancel()
        for task in self._intervals.values():
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._intervals.clear()

    async def _drain_in_flight(self) -> None:
        if not self._event_queue:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                asyncio.gather(*self._in_flight, return_exceptions=True),
                timeout=self._grace_period,
            )
        for task in list(self._in_flight):
            if not task.done():
                task.cancel()
        if self._in_flight:
            await asyncio.gather(*self._in_flight, return_exceptions=True)

    async def _cancel_loop(self) -> None:
        if not self._loop_task:
            return
        self._loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._loop_task

    async def emit(self, source: str, data: dict[str, Any]) -> None:
        if self._event_queue is None:
            return
        try:
            self._event_queue.put_nowait((source, data))
        except asyncio.QueueFull:
            self._alerts.append(
                f"REACTOR_BACKPRESSURE_EVENT: source={source} queue_depth={self._max_queue_depth}"
            )
            await self._event_queue.put((source, data))

    def inject_interval(self, source: str, interval: float) -> None:
        async def ticker() -> None:
            try:
                while self._running:
                    await asyncio.sleep(interval)
                    if self._running:
                        await self.emit(source, {"tick": True})
            except asyncio.CancelledError:
                pass

        self._intervals[source] = asyncio.create_task(ticker())

    def cpu_usage_fraction(self) -> float:
        now = time.monotonic()
        user = os.times().user
        wall_elapsed = now - self._last_cpu_sample[0]
        if wall_elapsed < 0.01:
            return 0.0
        cpu_elapsed = user - self._last_cpu_sample[1]
        self._last_cpu_sample = (now, user)
        return min(cpu_elapsed / wall_elapsed, 1.0)

    def state_submit(self, fn: Callable[[sqlite3.Connection], None]) -> None:
        if self._state is not None:
            self._state.submit(fn)

    def state_query(self, sql: str) -> list[tuple[Any, ...]]:
        if self._state is None:
            return []
        reader = self._state.open_reader()
        try:
            return reader.execute(sql).fetchall()
        finally:
            reader.close()

    def alerts(self) -> list[str]:
        return list(self._alerts)

    async def _loop(self) -> None:
        assert self._event_queue is not None
        try:
            while self._running:
                try:
                    source, data = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
                except TimeoutError:
                    continue

                self._tick_count += 1

                if self._bouncer is not None:
                    try:
                        allowed = await self._bouncer(data)
                        if not allowed:
                            continue
                    except Exception:
                        logger.exception("Bouncer error, dropping event")
                        continue

                handler = self._handlers.get(source)
                if handler is None:
                    continue

                task = asyncio.create_task(self._run_handler(source, handler, data))
                self._in_flight.add(task)
                task.add_done_callback(self._in_flight.discard)
        except asyncio.CancelledError:
            pass

    async def _run_handler(
        self,
        source: str,
        handler: Callable[[Any], Awaitable[None]],
        data: dict[str, Any],
    ) -> None:
        try:
            await asyncio.wait_for(handler(data), timeout=self._handler_timeout)
        except TimeoutError:
            logger.warning("Handler %s timed out", source)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Handler %s failed", source)
