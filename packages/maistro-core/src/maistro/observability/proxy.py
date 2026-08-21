"""Replayable LLM/tool proxies with tiered recording (ADR-055 / SPEC-070226-2b70).

``RecordingLLMClient`` and ``RecordingToolDispatcher`` wrap an injected inner
client/dispatcher, record every call as a
:class:`~maistro.observability.replay.ReplayEvent` (trace/span ids, per-trace
monotonic seq shared across both kinds), and — when constructed with a
``replay_session`` (from ``replay_source=trace_id``) — serve recorded responses
without ever touching the inner client.

Writes go through :class:`BoundedRecordWriter`:
- ``normal`` tier: async best-effort with a bounded buffer; overflow drops the
  record and increments ``observability_record_dropped`` — the hot path never
  blocks.
- ``sensitive``/``secret``: never dropped silently — written with a blocking
  budget (default 100ms); a miss raises
  :class:`~maistro.observability.replay.RecordWriteError`.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable

from maistro.observability.metrics import registry
from maistro.observability.replay import (
    RecordStore,
    RecordWriteError,
    ReplayEvent,
    ReplaySession,
    canonical_request_hash,
)
from maistro.observability.tiers import PIIDetector, SensitivityTier

observability_record_dropped = registry.counter(
    "observability_record_dropped",
    "Normal-tier replay records dropped due to writer buffer overflow",
)


# ─── Call shapes ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LLMRequest:
    model: str
    messages: list[dict[str, Any]]
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    output: Any
    error: str | None = None


# ─── Protocols ────────────────────────────────────────────────────────────────


class LLMClient(Protocol):
    """The inner (real) LLM client wrapped by the recording proxy."""

    async def call(self, request: LLMRequest) -> LLMResponse: ...


class ToolDispatcher(Protocol):
    """The inner (real) tool dispatcher wrapped by the recording proxy."""

    async def call(self, tool_call: ToolCall) -> ToolResult: ...


@runtime_checkable
class ReplayableLLMClient(Protocol):
    async def call(self, request: LLMRequest) -> LLMResponse: ...

    def replay(self, trace_id: str) -> AsyncIterator[ReplayEvent]: ...


@runtime_checkable
class ReplayableToolDispatcher(Protocol):
    async def call(self, tool_call: ToolCall) -> ToolResult: ...

    def replay(self, trace_id: str) -> AsyncIterator[ReplayEvent]: ...


# ─── Trace context (shared per-trace monotonic seq) ───────────────────────────


class TraceContext:
    """Carries the active ADR-037 trace/span ids and allocates the per-trace seq.

    Share one instance between the LLM proxy and the tool proxy of a trace so
    ``seq`` is monotonic across both kinds.
    """

    def __init__(self, trace_id: str, span_id: str) -> None:
        self.trace_id = trace_id
        self.span_id = span_id
        self._counter = itertools.count()

    def next_seq(self) -> int:
        return next(self._counter)


# ─── Bounded-buffer async writer ──────────────────────────────────────────────


class BoundedRecordWriter:
    """Async writer with a bounded buffer for normal-tier records.

    ``normal`` events are enqueued best-effort (overflow → drop + counter);
    ``sensitive``/``secret`` events are written synchronously with a time budget
    and raise :class:`RecordWriteError` on failure — never silently dropped.
    """

    def __init__(
        self,
        store: RecordStore,
        buffer_size: int = 10_000,
        blocking_budget_s: float = 0.1,
    ) -> None:
        self.store = store
        self._queue: asyncio.Queue[ReplayEvent] = asyncio.Queue(maxsize=buffer_size)
        self._blocking_budget_s = blocking_budget_s
        self._drain_task: asyncio.Task[None] | None = None

    def _ensure_drain_task(self) -> None:
        if self._drain_task is None or self._drain_task.done():
            self._drain_task = asyncio.get_running_loop().create_task(self._drain())

    async def _drain(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self.store.record(event)
            finally:
                self._queue.task_done()

    async def submit(self, event: ReplayEvent) -> None:
        if event.tier is SensitivityTier.NORMAL:
            self._ensure_drain_task()
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                observability_record_dropped.inc()
            return
        # sensitive/secret: blocking write within budget, never dropped silently
        try:
            async with asyncio.timeout(self._blocking_budget_s):
                await self.store.record(event)
        except TimeoutError as exc:
            raise RecordWriteError(
                f"{event.tier}-tier record (trace={event.trace_id} seq={event.seq}) "
                f"missed the {self._blocking_budget_s * 1000:.0f}ms write budget"
            ) from exc

    async def flush(self) -> None:
        """Wait for all buffered normal-tier records to be persisted."""
        await self._queue.join()

    async def aclose(self) -> None:
        await self.flush()
        if self._drain_task is not None:
            self._drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._drain_task
            self._drain_task = None


# ─── Recording proxies ────────────────────────────────────────────────────────


class _RecordingProxyBase:
    def __init__(
        self,
        inner: Any,
        context: TraceContext,
        writer: BoundedRecordWriter,
        *,
        tier: SensitivityTier = SensitivityTier.NORMAL,
        pii_detector: PIIDetector | None = None,
        replay_session: ReplaySession | None = None,
    ) -> None:
        self._inner = inner
        self._context = context
        self._writer = writer
        self._tier = tier
        self._pii_detector = pii_detector
        self._replay_session = replay_session

    @property
    def in_replay_mode(self) -> bool:
        return self._replay_session is not None

    async def _record(
        self, kind: str, request_args: dict[str, Any], response: dict[str, Any]
    ) -> None:
        payload: dict[str, Any] | None = {"request": request_args, "response": response}
        if self._tier is SensitivityTier.NORMAL and self._pii_detector is not None:
            payload = self._pii_detector.inspect(payload or {})
        event = ReplayEvent(
            trace_id=self._context.trace_id,
            span_id=self._context.span_id,
            seq=self._context.next_seq(),
            kind=kind,  # type: ignore[arg-type]
            request_hash=canonical_request_hash(request_args),
            payload=payload,
            tier=self._tier,
        )
        await self._writer.submit(event)

    async def _replay_events(self, trace_id: str) -> AsyncIterator[ReplayEvent]:
        for event in await self._writer.store.events_for_trace(trace_id):
            yield event

    def replay(self, trace_id: str) -> AsyncIterator[ReplayEvent]:
        """Yield the recorded events for ``trace_id`` in original seq order."""
        return self._replay_events(trace_id)


class RecordingLLMClient(_RecordingProxyBase):
    """Substrate-owned LLM proxy: records every call; replays without the inner client."""

    async def call(self, request: LLMRequest) -> LLMResponse:
        request_args = asdict(request)
        if self.in_replay_mode and self._replay_session is not None:
            response = await self._replay_session.next_response("llm", request_args)
            return LLMResponse(**response)
        inner: LLMClient = self._inner
        result = await inner.call(request)
        await self._record("llm", request_args, asdict(result))
        return result


class RecordingToolDispatcher(_RecordingProxyBase):
    """Substrate-owned tool proxy: records every call; replays without the inner dispatcher."""

    async def call(self, tool_call: ToolCall) -> ToolResult:
        request_args = asdict(tool_call)
        if self.in_replay_mode and self._replay_session is not None:
            response = await self._replay_session.next_response("tool", request_args)
            return ToolResult(**response)
        inner: ToolDispatcher = self._inner
        result = await inner.call(tool_call)
        await self._record("tool", request_args, asdict(result))
        return result


def create_replay_proxies(
    store: RecordStore,
    replay_source: str,
) -> tuple[RecordingLLMClient, RecordingToolDispatcher]:
    """Build LLM + tool proxies in replay mode for a recorded trace.

    The returned proxies share one :class:`ReplaySession` cursor (per-trace seq
    spans both kinds) and have no usable inner client — the real world is never
    invoked during replay.
    """
    session = ReplaySession(store, replay_source)
    writer = BoundedRecordWriter(store)
    context = TraceContext(trace_id=replay_source, span_id="replay")
    llm = RecordingLLMClient(None, context, writer, replay_session=session)
    tools = RecordingToolDispatcher(None, context, writer, replay_session=session)
    return llm, tools


__all__ = [
    "BoundedRecordWriter",
    "LLMClient",
    "LLMRequest",
    "LLMResponse",
    "RecordingLLMClient",
    "RecordingToolDispatcher",
    "ReplayableLLMClient",
    "ReplayableToolDispatcher",
    "ToolCall",
    "ToolDispatcher",
    "ToolResult",
    "TraceContext",
    "create_replay_proxies",
    "observability_record_dropped",
]
