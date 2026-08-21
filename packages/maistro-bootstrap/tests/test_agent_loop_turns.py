"""TurnRunner's inner tool budget: exhausting `max_turns` is an internal stop,
not the model finishing — so `execute_turn` must hand back the accumulated
transcript for the caller to resume from. Without it, callers can only restart
cold or (worse) echo the "(max turns reached)" sentinel to the model as its own
words, which makes any model believe it announced running out of budget and
quit — observed live as every cycle ending "agent made no change".
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from maistro_bootstrap.builders.agent_loop import AgentLoopConfig, TurnRunner
from maistro_bootstrap.builders.session import BuilderSession


class _FakeSession:
    """Just enough BuilderSession surface for TurnRunner: records assistant adds.

    Tool dispatch is exercised via an unknown tool name, which `_dispatch_tool`
    answers without touching the session — no sandbox needed.
    """

    sandbox = None  # dereferenced by _dispatch_tool; unused for unknown tools

    def __init__(self) -> None:
        self.assistant_adds: list[str] = []

    def add_assistant(self, content: str) -> None:
        self.assistant_adds.append(content)


class _AlwaysToolLLM:
    """Returns a tool_use block on every call and records each messages list."""

    def __init__(self) -> None:
        self.seen: list[list[dict[str, Any]]] = []
        self.n = 0

    def __call__(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: Any = None,
        max_tokens: Any = None,
    ) -> dict[str, Any]:
        self.seen.append([dict(m) for m in messages])
        self.n += 1
        return {
            "content": [
                {"type": "tool_use", "id": f"t{self.n}", "name": "no_such_tool", "input": {}}
            ],
            "stop_reason": "tool_use",
        }


def _runner(llm: Any, max_turns: int) -> TurnRunner:
    runner = TurnRunner(
        session=cast(BuilderSession, _FakeSession()),
        config=AgentLoopConfig(max_turns=max_turns, model="test-model"),
    )
    runner.set_llm(llm)
    return runner


@pytest.mark.asyncio
async def test_max_turns_returns_the_accumulated_transcript() -> None:
    llm = _AlwaysToolLLM()
    seed = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
    ]

    result = await _runner(llm, max_turns=3).execute_turn(messages=list(seed))

    assert result["stop_reason"] == "max_turns"
    transcript = result["messages"]
    # Seed preserved verbatim at the front...
    assert transcript[:2] == seed
    # ...then one assistant(tool_use) + user(tool_result) pair per inner turn.
    assert len(transcript) == 2 + 2 * 3
    assert transcript[2]["role"] == "assistant"
    assert transcript[3]["role"] == "user"
    assert transcript[3]["content"][0]["type"] == "tool_result"
    assert transcript[3]["content"][0]["tool_use_id"] == "t1"
    # The transcript ends on unanswered tool results — resumable as-is.
    assert transcript[-1]["role"] == "user"


@pytest.mark.asyncio
async def test_normal_stop_unchanged_no_transcript_needed() -> None:
    def stop_llm(
        messages: list[dict[str, Any]], *, tools: Any = None, max_tokens: Any = None
    ) -> dict[str, Any]:
        return {"content": "all done", "stop_reason": "stop"}

    result = await _runner(stop_llm, max_turns=3).execute_turn(
        messages=[{"role": "user", "content": "task"}]
    )

    assert result["stop_reason"] == "stop"
    assert result["content"] == "all done"
