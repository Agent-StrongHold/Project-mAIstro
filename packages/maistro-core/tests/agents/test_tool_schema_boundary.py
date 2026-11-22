"""The shared Agent boundary refuses unknown schemas, even for custom strategies."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from maistro.agents.base import Agent
from maistro.agents.context_builder import ContextBuilder
from maistro.prompts.store import InMemoryPromptManager
from maistro.security._types import AuthContext
from maistro.security.sentinel.audit import InMemoryAuditLog
from maistro.security.warden.detector import Warden
from maistro.testing.faux_provider import FauxProvider
from maistro.types.agent import AgentIdentity, ReasoningResult


class _CallingStrategy:
    def __init__(self, arguments: dict[str, Any], *, forge_schema: bool = False) -> None:
        self.arguments = arguments
        self.forge_schema = forge_schema
        self.exposed: list[str] = []

    async def reason(self, *_args: Any, **kwargs: Any) -> ReasoningResult:
        tools = kwargs["tools"]
        self.exposed = [tool["function"]["name"] for tool in tools or []]
        if tools is None:
            tools = kwargs["tools"] = []
        if self.forge_schema:
            # A strategy's writable model exposure is not the host contract.
            if tools:
                parameters = tools[0]["function"]["parameters"]
                parameters.clear()
                parameters.update({"type": "object"})
            else:
                tools.append(
                    {
                        "type": "function",
                        "function": {"name": "lookup", "parameters": {"type": "object"}},
                    }
                )
        result = await kwargs["tool_executor"]("lookup", self.arguments)
        return ReasoningResult(response=result)


def _agent(
    strategy: _CallingStrategy,
    schema: Any,
    *,
    registered: bool = True,
    repaired_data: dict[str, Any] | None = None,
) -> tuple[Agent, Any, Any, InMemoryAuditLog]:
    backend = AsyncMock(return_value="backend ran")
    sentinel = SimpleNamespace(
        pre_call=AsyncMock(return_value=SimpleNamespace(allowed=True, repaired_data=repaired_data)),
        post_call=AsyncMock(side_effect=lambda _name, result, _auth, **_kwargs: result),
    )
    definition = SimpleNamespace(name="lookup", description="Host lookup", parameters=schema)
    registry = SimpleNamespace(get=lambda _name: definition if registered else None)
    audit = InMemoryAuditLog()
    return (
        Agent(
            identity=AgentIdentity(name="schema-test", model="faux://test", tools=("lookup",)),
            strategy=strategy,
            llm=FauxProvider(),
            context_builder=ContextBuilder(),
            prompt_manager=InMemoryPromptManager(),
            warden=Warden(),
            sentinel=sentinel,
            tool_executor=backend,
            tool_registry=registry,
            audit_log=audit,
        ),
        backend,
        sentinel,
        audit,
    )


_CALLER = AuthContext(user_id="operator", org_id="org-1", roles=frozenset({"operator"}))


@pytest.mark.parametrize("schema", [None, {}, [], {"type": "string"}, {"type": "typo"}])
async def test_custom_strategy_cannot_dispatch_without_host_object_schema(schema: Any) -> None:
    strategy = _CallingStrategy({"query": "unconstrained"})
    agent, backend, sentinel, audit = _agent(strategy, schema)

    response = await agent.handle([{"role": "user", "content": "lookup"}], _CALLER)

    backend.assert_not_awaited()
    sentinel.pre_call.assert_not_awaited()
    assert "no schema" in response.content
    page = await audit.get_page(org_id="org-1", denied=True)
    assert len(page.records) == 1
    entry = page.records[0][1]
    assert entry.tool_name == "lookup"
    assert entry.agent_id == "schema-test"
    assert entry.detail == "no schema registered for requested tool"


async def test_unknown_tool_is_not_exposed_and_cannot_be_forged_by_strategy() -> None:
    strategy = _CallingStrategy({}, forge_schema=True)
    agent, backend, sentinel, _audit = _agent(strategy, None, registered=False)

    response = await agent.handle([{"role": "user", "content": "lookup"}], _CALLER)

    assert strategy.exposed == []
    backend.assert_not_awaited()
    sentinel.pre_call.assert_not_awaited()
    assert "no schema" in response.content


async def test_strategy_cannot_mutate_nested_host_schema_to_widen_arguments() -> None:
    strategy = _CallingStrategy({"query": 123}, forge_schema=True)
    agent, backend, _sentinel, audit = _agent(
        strategy,
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    )

    for _turn in range(2):
        response = await agent.handle([{"role": "user", "content": "lookup"}], _CALLER)
        assert "invalid arguments" in response.content

    backend.assert_not_awaited()
    assert len((await audit.get_page(org_id="org-1", denied=True)).records) == 2


@pytest.mark.parametrize("repaired", [{"query": 42}, {}])
async def test_materialized_repaired_arguments_are_revalidated(repaired: dict[str, Any]) -> None:
    agent, backend, sentinel, _audit = _agent(
        _CallingStrategy({"query": "original"}),
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        repaired_data=repaired,
    )

    response = await agent.handle([{"role": "user", "content": "lookup"}], _CALLER)

    sentinel.pre_call.assert_awaited_once()
    backend.assert_not_awaited()
    assert "invalid arguments" in response.content


@pytest.mark.parametrize("repaired", [None, {"query": "repaired"}])
async def test_valid_host_schema_and_valid_repairs_still_dispatch(repaired: Any) -> None:
    agent, backend, sentinel, audit = _agent(
        _CallingStrategy({"query": "original"}),
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        repaired_data=repaired,
    )

    response = await agent.handle([{"role": "user", "content": "lookup"}], _CALLER)

    assert response.content == "backend ran"
    sentinel.pre_call.assert_awaited_once()
    backend.assert_awaited_once_with(
        "lookup", repaired if repaired is not None else {"query": "original"}
    )
    assert (await audit.get_page(org_id="org-1", denied=True)).records == []


async def test_explicit_host_no_argument_schema_is_not_missing() -> None:
    agent, backend, _sentinel, _audit = _agent(
        _CallingStrategy({}), {"type": "object", "properties": {}, "additionalProperties": False}
    )

    response = await agent.handle([{"role": "user", "content": "lookup"}], _CALLER)

    assert response.content == "backend ran"
    backend.assert_awaited_once_with("lookup", {})
