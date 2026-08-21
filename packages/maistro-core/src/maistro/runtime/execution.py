"""Execution mechanics boundary for MAIstro.

Python remains authoritative for run, graph, agent, tool, policy, and persistence
semantics. This module owns only substitutable execution mechanics: bounded
concurrency, cancellation propagation, deadline enforcement, event sequencing,
and the measurements needed to decide whether any hot path ever merits a native
implementation.

The runtime deliberately treats ``work_item``, ``execution_context``, and emitted
events as opaque values. Domain interpretation belongs to callers.

Governed by ADR-081426-1f7c / SPEC-081426-1f7c.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

ExecutionCallable = Callable[[Any, Any], Awaitable[Any]]
EventSink = Callable[["RuntimeEventEnvelope"], Awaitable[None]]


class RuntimeDeadlineExceeded(TimeoutError):
    """The Runtime-owned physical execution deadline expired."""

    def __init__(self, execution_id: str) -> None:
        super().__init__(f"Runtime deadline exceeded for execution {execution_id!r}")
        self.execution_id = execution_id


@dataclass(frozen=True, slots=True)
class RuntimeEventEnvelope:
    """Runtime-assigned sequence metadata around an opaque domain event."""

    sequence: int
    emitted_at: datetime
    event: Any


@dataclass(frozen=True, slots=True)
class RuntimeMetrics:
    """Snapshot of execution mechanics and migration-trigger measurements."""

    executions_started: int
    executions_completed: int
    executions_failed: int
    executions_cancelled: int
    executions_timed_out: int
    active_executions: int
    active_slots: int
    peak_concurrency: int
    max_concurrency: int
    scheduling_wait_seconds_total: float
    scheduling_wait_seconds_last: float
    events_emitted: int
    event_sequence: int
    event_loop_lag_ms_last: float
    process_cpu_seconds: float
    max_rss_bytes: int | None


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    """Small health surface suitable for API/observability adapters."""

    implementation: str
    healthy: bool
    active_executions: int
    active_slots: int
    max_concurrency: int


@runtime_checkable
class ExecutionRuntime(Protocol):
    """Substitutable boundary for execution mechanics.

    Implementations must not interpret graph, run, agent, or tool semantics.
    Work and context are passed opaquely to the injected ``executor`` callable.
    ``execution_id`` identifies one physical execution, normally an Attempt.

    Governed by ``ADR-081426-1f7c`` / ``SPEC-081426-1f7c``.
    """

    async def execute(
        self,
        work_item: Any,
        execution_context: Any,
        *,
        execution_id: str,
        executor: ExecutionCallable,
        timeout_s: float | None = None,
    ) -> Any:
        """Execute opaque domain work under runtime mechanics."""
        ...

    async def cancel(self, execution_id: str) -> bool:
        """Request cancellation of an active or slot-waiting execution."""
        ...

    async def emit(self, event: Any) -> RuntimeEventEnvelope:
        """Assign a monotonically increasing sequence and publish an event."""
        ...

    async def acquire_slot(self, execution_id: str) -> float:
        """Acquire bounded-concurrency capacity and return wait time in seconds."""
        ...

    def release_slot(self, execution_id: str) -> None:
        """Release capacity held by ``execution_id``."""
        ...

    def metrics(self) -> RuntimeMetrics:
        """Return a point-in-time metrics snapshot."""
        ...

    def health(self) -> RuntimeHealth:
        """Return implementation health without exposing domain state."""
        ...

    async def sample_event_loop_lag(self, interval_s: float = 0.01) -> float:
        """Measure event-loop scheduling lag in milliseconds."""
        ...


class PythonExecutionRuntime:
    """Pure-Python implementation of :class:`ExecutionRuntime`.

    This implementation is intentionally small. It is the reference semantics
    for any future native kernel and therefore avoids graph-specific branching.
    """

    def __init__(
        self,
        *,
        max_concurrency: int = 32,
        event_sink: EventSink | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self._max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._event_sink = event_sink
        self._event_lock = asyncio.Lock()
        self._active: dict[str, asyncio.Task[Any]] = {}
        self._slot_waiters: set[str] = set()
        self._slot_holders: set[str] = set()

        self._executions_started = 0
        self._executions_completed = 0
        self._executions_failed = 0
        self._executions_cancelled = 0
        self._executions_timed_out = 0
        self._peak_concurrency = 0
        self._scheduling_wait_seconds_total = 0.0
        self._scheduling_wait_seconds_last = 0.0
        self._events_emitted = 0
        self._event_sequence = 0
        self._event_loop_lag_ms_last = 0.0

    def _validate_execution_request(
        self,
        execution_id: str,
        timeout_s: float | None,
    ) -> asyncio.Task[Any]:
        if not execution_id:
            raise ValueError("execution_id is required")
        if execution_id in self._active:
            raise ValueError(f"execution_id already active: {execution_id}")
        if timeout_s is not None and timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")

        task = asyncio.current_task()
        if task is None:  # pragma: no cover - asyncio always supplies one here
            raise RuntimeError("execute() requires an asyncio task")
        return task

    async def execute(
        self,
        work_item: Any,
        execution_context: Any,
        *,
        execution_id: str,
        executor: ExecutionCallable,
        timeout_s: float | None = None,
    ) -> Any:
        task = self._validate_execution_request(execution_id, timeout_s)

        self._active[execution_id] = task
        self._executions_started += 1
        slot_acquired = False
        timeout_context: asyncio.Timeout | None = None
        try:
            if timeout_s is None:
                await self.acquire_slot(execution_id)
                slot_acquired = True
                result = await executor(work_item, execution_context)
            else:
                timeout_context = asyncio.timeout(timeout_s)
                async with timeout_context:
                    await self.acquire_slot(execution_id)
                    slot_acquired = True
                    result = await executor(work_item, execution_context)

            self._executions_completed += 1
            return result
        except asyncio.CancelledError:
            self._executions_cancelled += 1
            raise
        except TimeoutError as exc:
            if timeout_context is not None and timeout_context.expired():
                self._executions_timed_out += 1
                raise RuntimeDeadlineExceeded(execution_id) from exc
            self._executions_failed += 1
            raise
        except Exception:
            self._executions_failed += 1
            raise
        finally:
            self._active.pop(execution_id, None)
            if slot_acquired:
                self.release_slot(execution_id)

    async def cancel(self, execution_id: str) -> bool:
        task = self._active.get(execution_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def emit(self, event: Any) -> RuntimeEventEnvelope:
        async with self._event_lock:
            self._event_sequence += 1
            envelope = RuntimeEventEnvelope(
                sequence=self._event_sequence,
                emitted_at=datetime.now(UTC),
                event=event,
            )
            self._events_emitted += 1

        if self._event_sink is not None:
            await self._event_sink(envelope)
        return envelope

    async def acquire_slot(self, execution_id: str) -> float:
        if execution_id in self._slot_holders or execution_id in self._slot_waiters:
            raise ValueError(f"execution_id already acquiring or holds a slot: {execution_id}")

        self._slot_waiters.add(execution_id)
        started = time.perf_counter()
        try:
            await self._semaphore.acquire()
        finally:
            self._slot_waiters.discard(execution_id)

        wait_s = time.perf_counter() - started
        self._slot_holders.add(execution_id)
        self._scheduling_wait_seconds_last = wait_s
        self._scheduling_wait_seconds_total += wait_s
        self._peak_concurrency = max(self._peak_concurrency, len(self._slot_holders))
        return wait_s

    def release_slot(self, execution_id: str) -> None:
        if execution_id not in self._slot_holders:
            raise ValueError(f"execution_id does not hold a slot: {execution_id}")
        self._slot_holders.remove(execution_id)
        self._semaphore.release()

    def metrics(self) -> RuntimeMetrics:
        return RuntimeMetrics(
            executions_started=self._executions_started,
            executions_completed=self._executions_completed,
            executions_failed=self._executions_failed,
            executions_cancelled=self._executions_cancelled,
            executions_timed_out=self._executions_timed_out,
            active_executions=len(self._active),
            active_slots=len(self._slot_holders),
            peak_concurrency=self._peak_concurrency,
            max_concurrency=self._max_concurrency,
            scheduling_wait_seconds_total=self._scheduling_wait_seconds_total,
            scheduling_wait_seconds_last=self._scheduling_wait_seconds_last,
            events_emitted=self._events_emitted,
            event_sequence=self._event_sequence,
            event_loop_lag_ms_last=self._event_loop_lag_ms_last,
            process_cpu_seconds=_process_cpu_seconds(),
            max_rss_bytes=_max_rss_bytes(),
        )

    def health(self) -> RuntimeHealth:
        return RuntimeHealth(
            implementation=type(self).__name__,
            healthy=True,
            active_executions=len(self._active),
            active_slots=len(self._slot_holders),
            max_concurrency=self._max_concurrency,
        )

    async def sample_event_loop_lag(self, interval_s: float = 0.01) -> float:
        if interval_s < 0:
            raise ValueError("interval_s must be >= 0")
        loop = asyncio.get_running_loop()
        started = loop.time()
        await asyncio.sleep(interval_s)
        elapsed = loop.time() - started
        lag_ms = max(0.0, elapsed - interval_s) * 1000.0
        self._event_loop_lag_ms_last = lag_ms
        return lag_ms


def _process_cpu_seconds() -> float:
    times = os.times()
    return float(times.user + times.system)


def _max_rss_bytes() -> int | None:
    """Best-effort process max RSS without adding a runtime dependency."""
    try:
        import resource
    except ImportError:  # pragma: no cover - Windows
        return None

    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if raw < 0:
        return None
    # Linux reports KiB; macOS reports bytes.
    return raw if sys.platform == "darwin" else raw * 1024


__all__ = [
    "EventSink",
    "ExecutionCallable",
    "ExecutionRuntime",
    "PythonExecutionRuntime",
    "RuntimeDeadlineExceeded",
    "RuntimeEventEnvelope",
    "RuntimeHealth",
    "RuntimeMetrics",
]
