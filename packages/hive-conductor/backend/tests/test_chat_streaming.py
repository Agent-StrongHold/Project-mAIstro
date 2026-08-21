"""Tests for token-by-token chat streaming.

Covers the one genuinely fiddly piece — assembling OpenAI streaming ``tool_calls``
fragments (`_ToolCallAccumulator`) — plus two end-to-end passes of the streaming
generator against a fake LLM port: content-only, and tool-call→answer.
"""

from __future__ import annotations

from typing import Any

from adapters.llm_http import _responses_event_to_chunk
from models.schemas import ChatCompletionRequest
from services.chat_completion import _ToolCallAccumulator, run_chat_completion_streaming

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
