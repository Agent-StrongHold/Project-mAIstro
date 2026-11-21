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


def _agent(*, guardrail: ToolGuardrail | None = None) -> Agent:
    sentinel = MagicMock()
    sentinel.pre_call = AsyncMock(return_value=MagicMock(allowed=True, repaired_data=None))
    return Agent(
        identity=_identity("read_file"),
        strategy=MagicMock(),
        llm=MagicMock(),
        context_builder=MagicMock(),
        prompt_manager=MagicMock(),
        warden=MagicMock(),
        sentinel=sentinel,
        tool_executor=AsyncMock(return_value="ok"),
        tool_guardrail=guardrail,
    )


@pytest.mark.asyncio
async def test_agent_defaults_to_tool_guardrail() -> None:
    agent = _agent()
    assert isinstance(agent._tool_guardrail, ToolGuardrail)


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
async def test_guardrail_blocks_exact_repeat_before_dispatch() -> None:
    guardrail = ToolGuardrail(GuardrailThresholds(warn_after=1, block_after=2))
    # Seed history as if prior identical calls already ran.
    for _ in range(2):
        guardrail.record("read_file", {"path": "/tmp/x"}, result="ok")
    agent = _agent(guardrail=guardrail)
    agent._tool_executor = AsyncMock(side_effect=AssertionError("must not dispatch"))

    result = await agent._authorize_and_invoke(
        "read_file", {"path": "/tmp/x"}, _Auth(), _read_file_defs()
    )
    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert "identical" in result.lower() or "guardrail" in result.lower()
    agent._tool_executor.assert_not_awaited()


@pytest.mark.asyncio
async def test_guardrail_records_successful_dispatch() -> None:
    guardrail = ToolGuardrail()
    agent = _agent(guardrail=guardrail)
    result = await agent._authorize_and_invoke(
        "read_file", {"path": "/tmp/y"}, _Auth(), _read_file_defs()
    )
    assert result == "ok"
    assert len(guardrail.history) == 1
    assert guardrail.history[0].tool_name == "read_file"
    post = guardrail.check("read_file", {"path": "/tmp/y"})
    assert post.action in {GuardrailAction.ALLOW, GuardrailAction.WARN}
