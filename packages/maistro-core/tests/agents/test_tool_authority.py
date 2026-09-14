"""Invocation-boundary tests for Agent tool capability envelopes."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.agents.base import Agent
from maistro.agents.strategies.react import ReactStrategy, _find_tool_schema
from maistro.agents.tool_authority import ToolAuthority, ToolAuthorityError, ToolSchemaError
from maistro.testing.faux_provider import FauxProvider, FauxResponse
from maistro.types.agent import AgentIdentity


async def test_model_selected_tool_without_declared_schema_is_denied_before_executor() -> None:
    calls: list[str] = []

    async def executor(name: str, _args: dict[str, Any]) -> str:
        calls.append(name)
        return "executed"

    provider = FauxProvider()
    provider.seed_tool_call("not_declared", {})
    provider.seed(FauxResponse(content="done"))
    result = await ReactStrategy().reason(
        [{"role": "user", "content": "do it"}],
        "model",
        provider,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "read",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        tool_executor=executor,
    )

    assert calls == []
    assert "no tool schema" in result.tool_history[0]["result"]


async def test_agent_callback_is_narrowed_to_identity_tools() -> None:
    calls: list[str] = []

    async def executor(name: str, _args: dict[str, Any]) -> str:
        calls.append(name)
        return "ok"

    identity = AgentIdentity(name="agent", tools=("read_file",))
    agent = Agent(
        identity=identity,
        strategy=object(),
        llm=None,
        context_builder=None,
        prompt_manager=None,
        warden=None,
        tool_executor=executor,
    )

    assert await agent._governed_tool_executor("read_file", {}) == "ok"
    assert "not in the Agent" in await agent._governed_tool_executor("github", {})
    assert calls == ["read_file"]


def test_effective_tool_set_is_declaration_intersect_host_policy() -> None:
    authority = ToolAuthority(("read_file", "github"), host_tools=("read_file",))

    authority.check("read_file", {})
    with pytest.raises(ToolAuthorityError):
        authority.check("github", {})


def test_write_scope_narrows_declared_write_tool() -> None:
    authority = ToolAuthority(("write_file",), write_scopes=("src/**",))

    authority.check("write_file", {"path": "src/module.py"})
    with pytest.raises(ToolAuthorityError):
        authority.check("write_file", {"path": "docs/README.md"})


def test_write_scope_rejects_traversal_before_glob_matching() -> None:
    authority = ToolAuthority(("write_file",), write_scopes=("**",))

    with pytest.raises(ToolAuthorityError):
        authority.check("write_file", {"path": "src/../secrets.txt"})


def test_current_host_policy_can_only_narrow_declarations() -> None:
    authority = ToolAuthority(("read_file", "github"))

    narrowed = authority.narrowed(("read_file",))
    narrowed.check("read_file", {})
    with pytest.raises(ToolAuthorityError):
        narrowed.check("github", {})


def test_agent_resolves_host_policy_at_invocation_time() -> None:
    identity = AgentIdentity(name="agent", tools=("read_file", "github"))
    agent = Agent(
        identity=identity,
        strategy=object(),
        llm=None,
        context_builder=None,
        prompt_manager=None,
        warden=None,
        host_tools=lambda _auth: ("read_file",),
    )

    effective = agent._authority_for(object())
    assert effective.allowed_tools == ("read_file",)


def test_missing_schema_is_typed_configuration_error() -> None:
    with pytest.raises(ToolSchemaError):
        _find_tool_schema([], "missing")
