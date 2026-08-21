"""Tests for maistro.observability.proxy — recording proxies, replay mode, writer."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.observability.proxy import (
    BoundedRecordWriter,
    LLMRequest,
    LLMResponse,
    RecordingLLMClient,
    RecordingToolDispatcher,
    ReplayableLLMClient,
    ReplayableToolDispatcher,
    ToolCall,
    ToolResult,
    TraceContext,
    create_replay_proxies,
    observability_record_dropped,
)
from maistro.observability.replay import (
    InMemoryRecordStore,
    RecordWriteError,
    ReplayDivergenceError,
    ReplayEvent,
    canonical_request_hash,
)
from maistro.observability.tiers import PIIDetector, SensitivityTier, UnexpectedPIIError


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[LLMRequest] = []

    async def call(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return LLMResponse(content=f"echo:{request.messages[-1]['content']}", model=request.model)


class FakeTools:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def call(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(output={"tool": tool_call.name, "ok": True})


class PoisonedClient:
    """Raises if the real world is ever touched during replay."""

    async def call(self, request: Any) -> Any:
        raise AssertionError("real inner client invoked during replay")


def build_recording_stack(
    store: InMemoryRecordStore | None = None,
    tier: SensitivityTier = SensitivityTier.NORMAL,
    pii_detector: PIIDetector | None = None,
) -> tuple[RecordingLLMClient, RecordingToolDispatcher, InMemoryRecordStore, BoundedRecordWriter]:
    store = store or InMemoryRecordStore()
    writer = BoundedRecordWriter(store)
    ctx = TraceContext(trace_id="trace-1", span_id="span-1")
    llm = RecordingLLMClient(FakeLLM(), ctx, writer, tier=tier, pii_detector=pii_detector)
    tools = RecordingToolDispatcher(FakeTools(), ctx, writer, tier=tier, pii_detector=pii_detector)
    return llm, tools, store, writer


def req(text: str) -> LLMRequest:
    return LLMRequest(model="m1", messages=[{"role": "user", "content": text}])


async def run_orchestration(llm: RecordingLLMClient, tools: RecordingToolDispatcher) -> list[Any]:
    """Small orchestration path: 2 LLM calls, 3 tool calls, interleaved."""
    out: list[Any] = []
    out.append(await llm.call(req("plan")))
    out.append(await tools.call(ToolCall(name="search", args={"q": "x"})))
    out.append(await tools.call(ToolCall(name="read", args={"path": "/a"})))
    out.append(await llm.call(req("synthesize")))
    out.append(await tools.call(ToolCall(name="write", args={"path": "/b"})))
    return out


class TestProtocolConformance:
    def test_proxies_satisfy_replayable_protocols(self) -> None:
        llm, tools, _, _ = build_recording_stack()
        assert isinstance(llm, ReplayableLLMClient)
        assert isinstance(tools, ReplayableToolDispatcher)


class TestRecording:
    @pytest.mark.ac("SPEC-070226-2b70/AC-1")
    async def test_events_carry_trace_span_and_monotonic_shared_seq(self) -> None:
        llm, tools, store, writer = build_recording_stack()
        await run_orchestration(llm, tools)
        await writer.flush()

        events = await store.events_for_trace("trace-1")
        assert len(events) == 5
        assert [e.seq for e in events] == [0, 1, 2, 3, 4]
        assert [e.kind for e in events] == ["llm", "tool", "tool", "llm", "tool"]
        assert all(e.trace_id == "trace-1" and e.span_id == "span-1" for e in events)

    @pytest.mark.ac("SPEC-070226-2b70/AC-1")
    async def test_request_hash_is_canonical_sha256(self) -> None:
        llm, _, store, writer = build_recording_stack()
        request = req("hello")
        await llm.call(request)
        await writer.flush()
        [event] = await store.events_for_trace("trace-1")
        assert event.request_hash == canonical_request_hash(
            {"model": "m1", "messages": [{"role": "user", "content": "hello"}], "params": {}}
        )

    @pytest.mark.ac("SPEC-070226-2b70/AC-2")
    async def test_replay_iterator_yields_recorded_events(self) -> None:
        llm, tools, _, writer = build_recording_stack()
        await run_orchestration(llm, tools)
        await writer.flush()
        events = [e async for e in llm.replay("trace-1")]
        assert [e.seq for e in events] == [0, 1, 2, 3, 4]

    @pytest.mark.ac("SPEC-070226-2b70/AC-7")
    async def test_pii_detector_runs_on_normal_tier(self) -> None:
        detector = PIIDetector(mode="dev")
        llm, _, _, _ = build_recording_stack(pii_detector=detector)
        with pytest.raises(UnexpectedPIIError):
            await llm.call(req("contact carol@example.com"))

    @pytest.mark.ac("SPEC-070226-2b70/AC-7")
    async def test_pii_detector_prod_redacts_stored_payload(self) -> None:
        detector = PIIDetector(mode="prod")
        llm, _, store, writer = build_recording_stack(pii_detector=detector)
        await llm.call(req("contact carol@example.com"))
        await writer.flush()
        [event] = await store.events_for_trace("trace-1")
        assert "carol@example.com" not in str(event.payload)

    @pytest.mark.ac("SPEC-070226-2b70/AC-7")
    async def test_pii_detector_skipped_on_sensitive_tier(self) -> None:
        detector = PIIDetector(mode="dev")
        llm, _, store, _writer = build_recording_stack(
            tier=SensitivityTier.SENSITIVE, pii_detector=detector
        )
        await llm.call(req("contact carol@example.com"))  # must not raise
        [event] = await store.events_for_trace("trace-1")
        assert event.payload is None


class TestReplayMode:
    @pytest.mark.ac("SPEC-070226-2b70/AC-3")
    async def test_replay_serves_recorded_responses_without_real_client(self) -> None:
        llm, tools, store, writer = build_recording_stack()
        recorded = await run_orchestration(llm, tools)
        await writer.flush()

        r_llm, r_tools = create_replay_proxies(store, replay_source="trace-1")
        # Poison the inner clients: replay must never touch them.
        r_llm._inner = PoisonedClient()
        r_tools._inner = PoisonedClient()
        assert r_llm.in_replay_mode and r_tools.in_replay_mode

        replayed = await run_orchestration(r_llm, r_tools)
        assert replayed == recorded

    @pytest.mark.ac("SPEC-070226-2b70/AC-4")
    async def test_replay_divergence_on_changed_request(self) -> None:
        llm, tools, store, writer = build_recording_stack()
        await run_orchestration(llm, tools)
        await writer.flush()

        r_llm, _ = create_replay_proxies(store, replay_source="trace-1")
        r_llm._inner = PoisonedClient()
        with pytest.raises(ReplayDivergenceError) as exc_info:
            await r_llm.call(req("a different plan"))
        assert exc_info.value.seq == 0
        assert exc_info.value.recorded_hash != exc_info.value.attempted_hash

    @pytest.mark.ac("SPEC-070226-2b70/AC-4")
    async def test_replay_divergence_on_kind_swap(self) -> None:
        llm, tools, store, writer = build_recording_stack()
        await run_orchestration(llm, tools)
        await writer.flush()

        _, r_tools = create_replay_proxies(store, replay_source="trace-1")
        r_tools._inner = PoisonedClient()
        # Recorded seq 0 is an LLM call; attempting a tool call first diverges.
        with pytest.raises(ReplayDivergenceError):
            await r_tools.call(ToolCall(name="search", args={"q": "x"}))

    @pytest.mark.ac("SPEC-070226-2b70/AC-1")
    async def test_replay_shares_cursor_across_llm_and_tool_proxies(self) -> None:
        llm, tools, store, writer = build_recording_stack()
        await run_orchestration(llm, tools)
        await writer.flush()

        r_llm, r_tools = create_replay_proxies(store, replay_source="trace-1")
        r_llm._inner = PoisonedClient()
        r_tools._inner = PoisonedClient()
        await r_llm.call(req("plan"))
        # Cursor advanced past seq 0 for both proxies; next must be the tool call.
        result = await r_tools.call(ToolCall(name="search", args={"q": "x"}))
        assert result.output == {"tool": "search", "ok": True}


class TestBoundedRecordWriter:
    @pytest.mark.ac("SPEC-070226-2b70/AC-9")
    async def test_normal_overflow_drops_and_increments_counter(self) -> None:
        class SlowStore(InMemoryRecordStore):
            async def record(self, event: ReplayEvent) -> None:
                await asyncio.sleep(3600)

        writer = BoundedRecordWriter(SlowStore(), buffer_size=2)
        ctx = TraceContext("t", "s")

        def ev(seq: int) -> ReplayEvent:
            return ReplayEvent(
                trace_id="t",
                span_id="s",
                seq=seq,
                kind="llm",
                request_hash="0" * 64,
                payload={},
                tier=SensitivityTier.NORMAL,
            )

        before = sum(v["value"] for v in observability_record_dropped.collect()) or 0.0
        # Buffer size 2; drain task is stuck in the slow store, so the 4th+ submits drop.
        for i in range(6):
            await writer.submit(ev(i))
        after = sum(v["value"] for v in observability_record_dropped.collect())
        assert after >= before + 3
        assert ctx.next_seq() == 0  # unrelated sanity: fresh context starts at 0
        writer._drain_task.cancel()  # type: ignore[union-attr]

    @pytest.mark.ac("SPEC-070226-2b70/AC-9")
    async def test_normal_submit_never_blocks(self) -> None:
        class SlowStore(InMemoryRecordStore):
            async def record(self, event: ReplayEvent) -> None:
                await asyncio.sleep(3600)

        writer = BoundedRecordWriter(SlowStore(), buffer_size=1)
        event = ReplayEvent("t", "s", 0, "llm", "0" * 64, {}, SensitivityTier.NORMAL)
        for _ in range(100):
            async with asyncio.timeout(1):
                await writer.submit(event)
        writer._drain_task.cancel()  # type: ignore[union-attr]

    @pytest.mark.ac("SPEC-070226-2b70/AC-9")
    async def test_sensitive_write_never_silently_dropped(self) -> None:
        class FailingStore(InMemoryRecordStore):
            async def record(self, event: ReplayEvent) -> None:
                await asyncio.sleep(3600)

        writer = BoundedRecordWriter(FailingStore(), blocking_budget_s=0.01)
        event = ReplayEvent("t", "s", 0, "llm", "0" * 64, None, SensitivityTier.SENSITIVE)
        with pytest.raises(RecordWriteError):
            await writer.submit(event)

    @pytest.mark.ac("SPEC-070226-2b70/AC-9")
    async def test_secret_write_within_budget_succeeds(self) -> None:
        store = InMemoryRecordStore()
        writer = BoundedRecordWriter(store)
        event = ReplayEvent("t", "s", 0, "llm", "0" * 64, None, SensitivityTier.SECRET)
        await writer.submit(event)
        assert len(await store.events_for_trace("t")) == 1

    @pytest.mark.ac("SPEC-070226-2b70/AC-9")
    async def test_flush_persists_buffered_normal_events(self) -> None:
        store = InMemoryRecordStore()
        writer = BoundedRecordWriter(store)
        event = ReplayEvent("t", "s", 0, "llm", "0" * 64, {"request": {}}, SensitivityTier.NORMAL)
        await writer.submit(event)
        await writer.aclose()
        assert len(await store.events_for_trace("t")) == 1
