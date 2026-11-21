"""#2315 — ToolGuardrail on the Workspace Agent tool path."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from maistro.agents.base import Agent
from maistro.security.guardrail import GuardrailAction, GuardrailThresholds, ToolGuardrail
from maistro.types.agent import AgentIdentity


class _Auth:
    user_id = "u1"


def _identity(*tools: str) -> AgentIdentity:
    return AgentIdentity(
        name="guardrail-agent",
        description="test",
        tools=tuple(tools),
    )


def _agent() -> Agent:
    sentinel = MagicMock()
    sentinel.pre_call = AsyncMock(return_value=MagicMock(allowed=True, repaired_data=None))
    sentinel.post_call = AsyncMock(side_effect=lambda _name, result, _auth, **_kw: result)
    return Agent(
        identity=_identity("read_file"),
        strategy=MagicMock(),
        llm=MagicMock(),
        context_builder=MagicMock(),
        prompt_manager=MagicMock(),
        warden=MagicMock(),
        sentinel=sentinel,
        tool_executor=AsyncMock(return_value="ok"),
    )


def _read_file_defs() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]


@pytest.mark.asyncio
async def test_agent_stores_guardrail_thresholds_not_shared_history() -> None:
    agent = _agent()
    assert isinstance(agent._tool_guardrail_thresholds, GuardrailThresholds)


@pytest.mark.asyncio
async def test_guardrail_blocks_exact_repeat_before_dispatch() -> None:
    guardrail = ToolGuardrail(GuardrailThresholds(warn_after=1, block_after=2))
    for _ in range(2):
        guardrail.record("read_file", {"path": "/tmp/x"}, result="ok")
    agent = _agent()
    agent._tool_executor = AsyncMock(side_effect=AssertionError("must not dispatch"))

    result = await agent._authorize_and_invoke(
        "read_file",
        {"path": "/tmp/x"},
        _Auth(),
        _read_file_defs(),
        tool_guardrail=guardrail,
    )
    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert "identical" in result.lower() or "guardrail" in result.lower()
    agent._tool_executor.assert_not_awaited()


@pytest.mark.asyncio
async def test_guardrail_records_successful_dispatch() -> None:
    guardrail = ToolGuardrail()
    agent = _agent()
    result = await agent._authorize_and_invoke(
        "read_file",
        {"path": "/tmp/y"},
        _Auth(),
        _read_file_defs(),
        tool_guardrail=guardrail,
    )
    assert result == "ok"
    assert len(guardrail.history) == 1
    assert guardrail.history[0].tool_name == "read_file"
    post = guardrail.check("read_file", {"path": "/tmp/y"})
    assert post.action in {GuardrailAction.ALLOW, GuardrailAction.WARN}


@pytest.mark.asyncio
async def test_post_call_same_tool_failure_block_latches_for_next_dispatch() -> None:
    """Codex P2: record() BLOCK must stop later rounds, not only exact repeats."""
    guardrail = ToolGuardrail(
        GuardrailThresholds(same_tool_failure_warn=1, same_tool_failure_block=2)
    )
    agent = _agent()
    agent._tool_executor = AsyncMock(return_value="Error: boom")
    # block_after=2 prior failures → third recorded failure latches BLOCK.
    for path in ("/a", "/b", "/c"):
        await agent._authorize_and_invoke(
            "read_file",
            {"path": path},
            _Auth(),
            _read_file_defs(),
            tool_guardrail=guardrail,
        )
    assert guardrail.check("read_file", {"path": "/probe"}).action is GuardrailAction.BLOCK
    agent._tool_executor = AsyncMock(side_effect=AssertionError("must not dispatch"))
    blocked = await agent._authorize_and_invoke(
        "read_file",
        {"path": "/different"},
        _Auth(),
        _read_file_defs(),
        tool_guardrail=guardrail,
    )
    assert blocked.startswith("Error:")
    assert "fail" in blocked.lower() or "guardrail" in blocked.lower()
    agent._tool_executor.assert_not_awaited()


@pytest.mark.asyncio
async def test_governed_executor_isolates_guardrail_per_execution() -> None:
    """Codex P1: long-lived Agents must not share loop history across turns."""
    agent = _agent()
    agent._tool_executor = AsyncMock(return_value="ok")
    first = agent._governed_tool_executor(_read_file_defs(), {"auth": _Auth()})
    second = agent._governed_tool_executor(_read_file_defs(), {"auth": _Auth()})
    from maistro.types.tool import ToolCall

    for _ in range(3):
        await first.execute_tool_call(ToolCall(id="1", name="read_file", arguments={"path": "/x"}))
    # Second execution starts fresh — identical args are not yet blocked.
    out = await second.execute_tool_call(
        ToolCall(id="2", name="read_file", arguments={"path": "/x"})
    )
    assert out == "ok"
