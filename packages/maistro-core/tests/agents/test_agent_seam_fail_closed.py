"""Tool authorization fails closed at the Agent seam and in standalone strategies (#1165).

A tool call that reaches the effect boundary with no Sentinel or no caller
identity is denied, never executed unauthorized. Each case drives the shipped
path: ``Agent.handle`` (and ``Container.route_request``) with a FauxProvider
emitting a tool call and a recording tool executor, and the ReAct / Artificer
strategies called standalone (``security_pipeline`` off).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from maistro.agents.artificer import strategy as artificer_module
from maistro.agents.artificer.strategy import ArtificerStrategy
from maistro.agents.base import Agent
from maistro.agents.context_builder import ContextBuilder
from maistro.agents.strategies.react import ReactStrategy
from maistro.prompts.store import InMemoryPromptManager
from maistro.security._types import AuthContext
from maistro.security.sentinel.policy import Sentinel
from maistro.security.warden.detector import Warden
from maistro.testing.faux_provider import FauxProvider, FauxResponse
from maistro.testing.harness import create_test_environment
from maistro.types.agent import AgentIdentity

_DENIED = "Error: Permission denied for tool 'lookup'"
_RAW = "raw lookup result"
_AUTH = AuthContext(user_id="u1", roles=frozenset({"operator"}), org_id="org-1")
_NO_SENTINEL = object()


async def _no_sleep(_seconds: float) -> None:
    return None


class _RecordingTool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        self.calls.append((tool_name, dict(tool_args)))
        return _RAW


def _provider() -> FauxProvider:
    provider = FauxProvider()
    provider.seed_tool_call("lookup", {"id": "42"})
    provider.seed(FauxResponse(content="done"))
    return provider


def _tool_results(provider: FauxProvider) -> list[str]:
    return [m["content"] for m in provider.call_log[-1]["messages"] if m.get("role") == "tool"]


def _agent(
    sentinel: Any, tool: _RecordingTool, provider: FauxProvider, name: str = "seam"
) -> Agent:
    warden = Warden()
    return Agent(
        identity=AgentIdentity(name=name, model="faux://test-model", tools=("lookup",)),
        strategy=ReactStrategy(),
        llm=provider,
        context_builder=ContextBuilder(),
        prompt_manager=InMemoryPromptManager(),
        warden=warden,
        sentinel=sentinel,
        tool_executor=tool,
    )


def _sentinel(table: dict[str, frozenset[str]]) -> Sentinel:
    return Sentinel(warden=Warden(), permission_table=table)


@pytest.mark.parametrize(
    ("sentinel", "auth"),
    [
        (_NO_SENTINEL, _AUTH),
        ("grant", None),
        ("empty", _AUTH),
        ("deny", _AUTH),
    ],
    ids=["no-sentinel", "no-auth", "empty-table", "explicit-deny"],
)
async def test_agent_denies_tool_without_authorization(sentinel: Any, auth: Any) -> None:
    tables = {
        "grant": {"lookup": frozenset({"operator"})},
        "empty": {},
        "deny": {"lookup": frozenset({"admin"})},
    }
    built = None if sentinel is _NO_SENTINEL else _sentinel(tables[sentinel])
    tool = _RecordingTool()
    provider = _provider()

    await _agent(built, tool, provider).handle(
        messages=[{"role": "user", "content": "Look up 42."}], auth=auth
    )

    assert tool.calls == []
    assert _tool_results(provider) == [_DENIED]


async def test_agent_executes_tool_on_explicit_role_grant() -> None:
    tool = _RecordingTool()
    provider = _provider()

    await _agent(_sentinel({"lookup": frozenset({"operator"})}), tool, provider).handle(
        messages=[{"role": "user", "content": "Look up 42."}], auth=_AUTH
    )

    assert tool.calls == [("lookup", {"id": "42"})]
    assert _tool_results(provider) == [_RAW]


async def test_route_request_without_auth_cannot_execute_tools() -> None:
    provider = _provider()
    env = create_test_environment(provider=provider)
    tool = _RecordingTool()
    agent = _agent(env.container.sentinel, tool, provider, name="lookup_agent")
    env.container.agents["lookup_agent"] = agent
    env.container.intent_registry.register("lookup_agent", "lookup_agent")

    await env.container.route_request(
        [{"role": "user", "content": "Look up 42."}], intent_hint="lookup_agent"
    )

    assert tool.calls == []
    assert _tool_results(provider) == [_DENIED]


def _standalone(name: str, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, FauxProvider]:
    provider = FauxProvider()
    if name == "artificer":
        monkeypatch.setattr(artificer_module, "asyncio", SimpleNamespace(sleep=_no_sleep))
        provider.seed(FauxResponse(content="1. Look up the record."))
        provider.seed_tool_call("lookup", {"id": "42"})
        provider.seed(FauxResponse(content="done"))
        return ArtificerStrategy(), provider
    provider.seed_tool_call("lookup", {"id": "42"})
    provider.seed(FauxResponse(content="done"))
    return ReactStrategy(), provider


@pytest.mark.parametrize("strategy_name", ["react", "artificer"])
@pytest.mark.parametrize(
    ("table", "auth", "executed"),
    [
        (None, _AUTH, False),
        ({"lookup": frozenset({"operator"})}, None, False),
        ({}, _AUTH, False),
        ({"lookup": frozenset({"admin"})}, _AUTH, False),
        ({"lookup": frozenset({"operator"})}, _AUTH, True),
    ],
    ids=["no-sentinel", "no-auth", "empty-table", "explicit-deny", "explicit-grant"],
)
async def test_standalone_strategy_fails_closed(
    strategy_name: str,
    table: dict[str, frozenset[str]] | None,
    auth: Any,
    executed: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy, provider = _standalone(strategy_name, monkeypatch)
    tool = _RecordingTool()

    await strategy.reason(
        [{"role": "user", "content": "Look up 42."}],
        "faux://test-model",
        provider,
        tools=[{"type": "function", "function": {"name": "lookup", "parameters": {}}}],
        tool_executor=tool,
        warden=Warden(),
        sentinel=None if table is None else _sentinel(table),
        auth=auth,
    )

    assert (tool.calls == [("lookup", {"id": "42"})]) is executed
    assert _tool_results(provider) == [_RAW if executed else _DENIED]
