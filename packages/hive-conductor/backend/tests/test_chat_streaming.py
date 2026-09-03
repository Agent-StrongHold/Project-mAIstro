"""Tests for token-by-token chat streaming.

Covers the one genuinely fiddly piece — assembling OpenAI streaming ``tool_calls``
fragments (`_ToolCallAccumulator`) — plus two end-to-end passes of the streaming
generator against a fake LLM port: content-only, and tool-call→answer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pytest
from adapters.llm_http import _responses_event_to_chunk
from models.schemas import ChatCompletionRequest
from services.chat_completion import (
    _complete_turn,
    _stream_turn,
    _ToolCallAccumulator,
    run_chat_completion_streaming,
)

# --------------------------------------------------------------------------- #
# _ToolCallAccumulator — pure fragment assembly (no I/O)
# --------------------------------------------------------------------------- #


def test_accumulator_single_call_assembled_from_fragments() -> None:
    acc = _ToolCallAccumulator()
    # id + name arrive first; arguments stream in pieces across later deltas.
    acc.add_deltas(
        [
            {
                "index": 0,
                "id": "call_1",
                "type": "function",
                "function": {"name": "poll_jira", "arguments": ""},
            }
        ]
    )
    acc.add_deltas([{"index": 0, "function": {"arguments": '{"sprint"'}}])
    acc.add_deltas([{"index": 0, "function": {"arguments": ": 1}"}}])

    out = acc.finalize()
    assert len(out) == 1
    assert out[0]["id"] == "call_1"
    assert out[0]["function"]["name"] == "poll_jira"
    assert out[0]["function"]["arguments"] == '{"sprint": 1}'


def test_accumulator_multiple_calls_tracked_by_index() -> None:
    acc = _ToolCallAccumulator()
    acc.add_deltas(
        [
            {"index": 0, "id": "a", "function": {"name": "t0", "arguments": "{}"}},
            {"index": 1, "id": "b", "function": {"name": "t1", "arguments": ""}},
        ]
    )
    acc.add_deltas([{"index": 1, "function": {"arguments": '{"x":2}'}}])

    out = acc.finalize()
    assert [c["id"] for c in out] == ["a", "b"]  # finalize() is ordered by index
    assert out[0]["function"]["arguments"] == "{}"
    assert out[1]["function"]["name"] == "t1"
    assert out[1]["function"]["arguments"] == '{"x":2}'


def test_accumulator_later_deltas_may_omit_id_and_name() -> None:
    acc = _ToolCallAccumulator()
    acc.add_deltas([{"index": 0, "id": "x", "function": {"name": "foo", "arguments": "a"}}])
    acc.add_deltas([{"index": 0, "function": {"arguments": "b"}}])  # no id / name this time

    out = acc.finalize()
    assert out[0]["id"] == "x"
    assert out[0]["function"]["name"] == "foo"
    assert out[0]["function"]["arguments"] == "ab"


def test_accumulator_empty_and_none_are_safe() -> None:
    acc = _ToolCallAccumulator()
    assert not acc  # __bool__ is False when empty
    acc.add_deltas([])
    acc.add_deltas(None)  # type: ignore[arg-type]  # tolerate a missing tool_calls key
    assert not acc
    assert acc.finalize() == []


# --------------------------------------------------------------------------- #
# run_chat_completion_streaming — end-to-end against a fake LLM port
# --------------------------------------------------------------------------- #


class _FakeLLM:
    """Scripted LLM port: each call to ``stream()`` plays back the next turn."""

    def __init__(self, turns: list[list[dict[str, Any]]]) -> None:
        self._turns = [list(t) for t in turns]

    async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
        return {"choices": [{"message": {"role": "assistant", "content": ""}}]}

    async def stream(self, req: ChatCompletionRequest):
        chunks = self._turns.pop(0) if self._turns else []
        for c in chunks:
            yield c


def _content(text: str, finish: str | None = None) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": text}, "finish_reason": finish}]}


def _reasoning(text: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"reasoning_content": text}, "finish_reason": None}]}


def _tool_frag(
    index: int, *, id: str | None = None, name: str | None = None, args: str = ""
) -> dict[str, Any]:
    fn: dict[str, Any] = {}
    if name:
        fn["name"] = name
    if args:
        fn["arguments"] = args
    delta: dict[str, Any] = {"index": index, "function": fn}
    if id:
        delta["id"] = id
    return {"choices": [{"delta": {"tool_calls": [delta]}, "finish_reason": None}]}


def _finish(reason: str) -> dict[str, Any]:
    return {"choices": [{"delta": {}, "finish_reason": reason}]}


async def _collect(agen) -> list[dict[str, Any]]:
    return [event async for event in agen]


async def test_streaming_content_only_emits_deltas_then_done(monkeypatch) -> None:
    monkeypatch.setattr("services.chat_completion._build_system_prompt", lambda uid: "SYS")
    monkeypatch.setattr(
        "services.chat_completion.build_llm_port",
        lambda: _FakeLLM([[_content("Hel"), _content("lo"), _finish("stop")]]),
    )

    req = ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}], model="test-model")
    events = await _collect(run_chat_completion_streaming(req, user_id=""))

    deltas = [e["content"] for e in events if e["type"] == "delta"]
    assert deltas == ["Hel", "lo"]  # streamed token-by-token, in order
    assert not any(e["type"] == "tool_call" for e in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "Hello"  # full text also in the terminal event


async def test_streaming_tool_call_then_streamed_answer(monkeypatch) -> None:
    monkeypatch.setattr("services.chat_completion._build_system_prompt", lambda uid: "SYS")

    async def fake_exec(tool_name: str, args: dict[str, Any], user_id: str) -> dict[str, Any]:
        assert tool_name == "check_blockers"
        assert args == {"sprint": 1}  # arguments correctly reassembled from fragments
        return {"ok": True}

    monkeypatch.setattr("services.chat_completion._execute_tool", fake_exec)

    turns = [
        # turn 1: the model assembles a tool call across fragments, then stops to call it
        [
            _tool_frag(0, id="call_1", name="check_blockers"),
            _tool_frag(0, args='{"sprint"'),
            _tool_frag(0, args=": 1}"),
            _finish("tool_calls"),
        ],
        # turn 2: with the tool result in context, it streams the final answer
        [_content("All "), _content("clear"), _finish("stop")],
    ]
    monkeypatch.setattr("services.chat_completion.build_llm_port", lambda: _FakeLLM(turns))

    req = ChatCompletionRequest(
        messages=[{"role": "user", "content": "blockers?"}], model="test-model"
    )
    events = await _collect(run_chat_completion_streaming(req, user_id=""))

    types = [e["type"] for e in events]
    assert "tool_call" in types and "tool_result" in types

    tc_evt = next(e for e in events if e["type"] == "tool_call")
    assert tc_evt["tool"] == "check_blockers"
    assert tc_evt["args"] == {"sprint": 1}

    deltas = [e["content"] for e in events if e["type"] == "delta"]
    assert "".join(deltas) == "All clear"
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "All clear"


class _CaptureTelemetry:
    """A TelemetryPort stub whose spans record what crossed the boundary.

    The chat path holds the port (not the concrete adapter) since #63 wired
    it, so tests patch the seam the way a deployment swaps the backend.
    """

    def __init__(self, sink: Any) -> None:
        self._sink = sink

    def trace(self, **kwargs: Any) -> Any:
        return self._sink(kwargs.pop("name", "telemetry.operation"), **kwargs)

    def generation(self, **kwargs: Any) -> Any:
        return self._sink(kwargs.pop("name", "telemetry.operation"), **kwargs)


async def test_streaming_telemetry_call_sites_are_content_free(monkeypatch) -> None:
    credential_probe = "".join(("sk-", "live_ABCDE", "FGHIJKLMNO", "PQRSTUVWXY", "Z123456"))
    traces: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    @contextmanager
    def capture_trace(
        name: str,
        **kwargs: Any,
    ) -> Generator[dict[str, Any], None, None]:
        context: dict[str, Any] = {}
        traces.append((name, kwargs, context))
        yield context

    monkeypatch.setattr("services.chat_completion.telemetry", _CaptureTelemetry(capture_trace))
    monkeypatch.setattr("services.chat_completion._build_system_prompt", lambda uid: "SYS")

    async def fake_exec(tool_name: str, args: dict[str, Any], user_id: str) -> dict[str, Any]:
        assert args == {"api_key": credential_probe}
        return {"credential_echo": credential_probe}

    monkeypatch.setattr("services.chat_completion._execute_tool", fake_exec)
    turns = [
        [
            _tool_frag(0, id="call_1", name="check_blockers"),
            _tool_frag(0, args=f'{{"api_key":"{credential_probe}"}}'),
            _finish("tool_calls"),
        ],
        [_content(f"Answer without echoing {credential_probe}"), _finish("stop")],
    ]
    monkeypatch.setattr("services.chat_completion.build_llm_port", lambda: _FakeLLM(turns))
    req = ChatCompletionRequest(
        messages=[{"role": "user", "content": f"use {credential_probe}"}],
        model="test-model",
    )

    await _collect(run_chat_completion_streaming(req, user_id="private-user@example.com"))

    assert [name for name, _kwargs, _context in traces] == [
        "chat_completion",
        "tool_call",
        "chat_completion",
    ]
    assert [kwargs["metadata"] for _name, kwargs, _context in traces] == [
        {"iteration": 0, "streaming": True},
        {"iteration": 0, "tool_name": "check_blockers"},
        {"iteration": 1, "streaming": True},
    ]
    assert all(kwargs["model"] == "test-model" for _name, kwargs, _context in traces)
    assert all("private-user@example.com" not in repr(kwargs) for _name, kwargs, _ in traces)
    tool_kwargs = traces[1][1]
    assert "check_blockers" in tool_kwargs["allowed_tool_names"]
    assert credential_probe not in repr(traces)
    assert "private-user@example.com" not in repr(traces)


async def test_stream_span_measures_first_model_await_and_closes_before_yield(
    monkeypatch,
) -> None:
    active = False
    timeline: list[str] = []

    @contextmanager
    def capture_trace(
        name: str,
        **_kwargs: Any,
    ) -> Generator[dict[str, Any], None, None]:
        nonlocal active
        assert name == "chat_completion"
        assert not active
        active = True
        timeline.append("span_enter")
        try:
            yield {}
        finally:
            active = False
            timeline.append("span_exit")

    class _MeasuredLLM:
        async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
            raise AssertionError("content stream should not fall back")

        async def stream(self, req: ChatCompletionRequest):
            assert active, "the concrete first provider await is measured"
            timeline.append("first_provider_event")
            yield _content("first")
            assert not active, "the span closed before resuming after the first chunk"
            timeline.append("stream_resumed")
            yield _content("second")

    monkeypatch.setattr("services.chat_completion.telemetry", _CaptureTelemetry(capture_trace))
    monkeypatch.setattr("services.chat_completion._build_system_prompt", lambda uid: "SYS")
    monkeypatch.setattr("services.chat_completion.build_llm_port", _MeasuredLLM)
    req = ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}], model="model")
    stream = run_chat_completion_streaming(req)

    assert (await anext(stream))["type"] == "status"
    first_delta = await anext(stream)
    assert first_delta == {"type": "delta", "content": "first"}
    assert not active
    assert timeline == ["span_enter", "first_provider_event", "span_exit"]

    await stream.aclose()
    assert not active


async def test_stream_turn_exits_when_provider_stream_is_empty(monkeypatch) -> None:
    traces: list[tuple[str, dict[str, Any]]] = []

    @contextmanager
    def capture_trace(name: str, **kwargs: Any) -> Generator[dict[str, Any], None, None]:
        traces.append((name, kwargs))
        yield {}

    monkeypatch.setattr("services.chat_completion.telemetry", _CaptureTelemetry(capture_trace))
    req = ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}], model="test-model")
    content_out: list[str] = []
    events = [
        event
        async for event in _stream_turn(
            _FakeLLM([[]]),
            req,
            None,
            content_out,
            model="test-model",
            allowed_models=("test-model",),
            iteration=0,
        )
    ]

    assert events == []
    assert content_out == []
    assert traces == [
        (
            "chat_completion",
            {
                "model": "test-model",
                "allowed_models": ("test-model",),
                "metadata": {"iteration": 0, "streaming": True},
            },
        )
    ]


async def test_complete_turn_uses_non_streaming_telemetry_span(monkeypatch) -> None:
    traces: list[tuple[str, dict[str, Any]]] = []

    @contextmanager
    def capture_trace(name: str, **kwargs: Any) -> Generator[dict[str, Any], None, None]:
        traces.append((name, kwargs))
        yield {}

    class _CompleteLLM:
        async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "done"}}]}

    monkeypatch.setattr("services.chat_completion.telemetry", _CaptureTelemetry(capture_trace))
    req = ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}], model="test-model")
    out = await _complete_turn(
        _CompleteLLM(),
        req,
        model="test-model",
        allowed_models=("test-model",),
        iteration=2,
    )

    assert out["choices"][0]["message"]["content"] == "done"
    assert traces == [
        (
            "chat_completion",
            {
                "model": "test-model",
                "allowed_models": ("test-model",),
                "metadata": {"iteration": 2, "streaming": False},
            },
        )
    ]


async def test_streaming_falls_back_to_complete_on_stream_error(monkeypatch) -> None:
    monkeypatch.setattr("services.chat_completion._build_system_prompt", lambda uid: "SYS")

    class _BrokenStream:
        def __aiter__(self) -> _BrokenStream:
            return self

        async def __anext__(self) -> dict[str, Any]:
            raise RuntimeError("stream broken")

    class _FailStreamLLM:
        async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "recovered via complete"}}]}

        def stream(self, req: ChatCompletionRequest) -> _BrokenStream:
            return _BrokenStream()

    monkeypatch.setattr("services.chat_completion.build_llm_port", lambda: _FailStreamLLM())
    req = ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}], model="test-model")
    events = await _collect(run_chat_completion_streaming(req))

    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "recovered via complete"


async def test_streaming_falls_back_to_complete_when_stream_yields_nothing(
    monkeypatch,
) -> None:
    monkeypatch.setattr("services.chat_completion._build_system_prompt", lambda uid: "SYS")

    class _EmptyThenCompleteLLM(_FakeLLM):
        async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "from non-streaming"}}]}

    monkeypatch.setattr(
        "services.chat_completion.build_llm_port",
        lambda: _EmptyThenCompleteLLM([[]]),
    )
    req = ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}], model="test-model")
    events = await _collect(run_chat_completion_streaming(req))

    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "from non-streaming"


async def test_streaming_retries_non_streaming_when_tool_leaked_as_text(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("services.chat_completion._build_system_prompt", lambda uid: "SYS")

    class _LeakyLLM:
        def __init__(self) -> None:
            self.complete_calls = 0

        async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
            self.complete_calls += 1
            return {"choices": [{"message": {"content": "structured answer"}}]}

        async def stream(self, req: ChatCompletionRequest):
            yield _content("Please poll_jira for my tasks")
            yield _finish("stop")

    llm = _LeakyLLM()
    monkeypatch.setattr("services.chat_completion.build_llm_port", lambda: llm)
    req = ChatCompletionRequest(
        messages=[{"role": "user", "content": "tasks?"}], model="test-model"
    )

    with caplog.at_level("WARNING"):
        events = await _collect(run_chat_completion_streaming(req))

    assert llm.complete_calls == 1
    assert "Model leaked tool calls as text" in caplog.text
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "structured answer"


async def test_streaming_final_synthesis_uses_non_streaming_span(monkeypatch) -> None:
    traces: list[tuple[str, dict[str, Any]]] = []

    @contextmanager
    def capture_trace(name: str, **kwargs: Any) -> Generator[dict[str, Any], None, None]:
        traces.append((name, kwargs))
        yield {}

    monkeypatch.setattr("services.chat_completion.telemetry", _CaptureTelemetry(capture_trace))
    monkeypatch.setattr("services.chat_completion._build_system_prompt", lambda uid: "SYS")

    async def fake_exec(tool_name: str, args: dict[str, Any], user_id: str) -> dict[str, Any]:
        return {"ok": True}

    monkeypatch.setattr("services.chat_completion._execute_tool", fake_exec)

    tool_turn = [
        _tool_frag(0, id="call_1", name="poll_jira"),
        _tool_frag(0, args="{}"),
        _finish("tool_calls"),
    ]

    class _FiveToolLoopLLM:
        async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "final synthesis answer"}}]}

        async def stream(self, req: ChatCompletionRequest):
            for chunk in tool_turn:
                yield chunk

    monkeypatch.setattr("services.chat_completion.build_llm_port", lambda: _FiveToolLoopLLM())
    req = ChatCompletionRequest(messages=[{"role": "user", "content": "loop"}], model="test-model")
    events = await _collect(run_chat_completion_streaming(req))

    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "final synthesis answer"
    final_traces = [kwargs for name, kwargs in traces if name == "chat_completion"]
    assert final_traces[-1]["metadata"] == {"iteration": 5, "streaming": False}


async def test_stream_span_closes_when_first_model_await_is_cancelled(
    monkeypatch,
) -> None:
    active = False
    provider_await_started = asyncio.Event()

    @contextmanager
    def capture_trace(
        name: str,
        **_kwargs: Any,
    ) -> Generator[dict[str, Any], None, None]:
        nonlocal active
        assert name == "chat_completion"
        active = True
        try:
            yield {}
        finally:
            active = False

    class _BlockingLLM:
        async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
            raise AssertionError("cancelled stream should not fall back")

        async def stream(self, req: ChatCompletionRequest):
            provider_await_started.set()
            await asyncio.Event().wait()
            yield _content("unreachable")

    monkeypatch.setattr("services.chat_completion.telemetry", _CaptureTelemetry(capture_trace))
    monkeypatch.setattr("services.chat_completion._build_system_prompt", lambda uid: "SYS")
    monkeypatch.setattr("services.chat_completion.build_llm_port", _BlockingLLM)
    req = ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}], model="model")
    stream = run_chat_completion_streaming(req)

    assert (await anext(stream))["type"] == "status"
    next_event = asyncio.create_task(anext(stream))
    await provider_await_started.wait()
    assert active

    next_event.cancel()
    with pytest.raises(asyncio.CancelledError):
        await next_event
    assert not active


# --------------------------------------------------------------------------- #
# Lane #1 — reasoning/thinking streaming (reasoning_content -> thinking events)
# --------------------------------------------------------------------------- #


async def test_streaming_emits_thinking_from_reasoning_content(monkeypatch) -> None:
    monkeypatch.setattr("services.chat_completion._build_system_prompt", lambda uid: "SYS")
    monkeypatch.setattr(
        "services.chat_completion.build_llm_port",
        lambda: _FakeLLM([[_reasoning("Let me think"), _content("Answer"), _finish("stop")]]),
    )

    req = ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}], model="test-model")
    events = await _collect(run_chat_completion_streaming(req, user_id=""))

    assert [e["content"] for e in events if e["type"] == "thinking"] == ["Let me think"]
    assert [e["content"] for e in events if e["type"] == "delta"] == ["Answer"]
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "Answer"


# --------------------------------------------------------------------------- #
# Lane #2 — Responses-API event normalization (pure)
# --------------------------------------------------------------------------- #


def test_responses_event_normalization() -> None:
    text = _responses_event_to_chunk({"type": "response.output_text.delta", "delta": "Hi"})
    assert text["choices"][0]["delta"]["content"] == "Hi"

    reasoning = _responses_event_to_chunk(
        {"type": "response.reasoning_summary_text.delta", "delta": "hmm"}
    )
    assert reasoning["choices"][0]["delta"]["reasoning_content"] == "hmm"

    done = _responses_event_to_chunk({"type": "response.completed"})
    assert done["choices"][0]["finish_reason"] == "stop"

    # events we don't surface (item bookkeeping, empty deltas) collapse to None
    assert _responses_event_to_chunk({"type": "response.output_item.added"}) is None
    assert _responses_event_to_chunk({"type": "response.output_text.delta", "delta": ""}) is None
