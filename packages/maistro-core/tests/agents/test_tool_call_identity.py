"""Provider tool identity survives the real Agent authorization and strategy loops."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from maistro.agents.artificer import strategy as artificer_module
from maistro.agents.artificer.strategy import ArtificerStrategy
from maistro.agents.base import Agent
from maistro.agents.context_builder import ContextBuilder
from maistro.agents.strategies.delegate import DelegateStrategy
from maistro.agents.strategies.react import ReactStrategy
from maistro.agents.tool_dispatch import ToolCallExecutor, dispatch_tool_call
from maistro.prompts.store import InMemoryPromptManager
from maistro.security._types import AuthContext
from maistro.security.sentinel.policy import Sentinel
from maistro.security.warden.detector import Warden
from maistro.testing.faux_provider import FauxProvider, FauxResponse, ToolCallDef
from maistro.types.agent import AgentIdentity
from maistro.types.tool import ToolCall

_CALLER = AuthContext(user_id="operator", roles=frozenset({"operator"}))


async def _no_sleep(_seconds: float) -> None:
    return None


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[ToolCall, str, int, int]] = []
        self.legacy_calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, name: str, args: dict[str, Any]) -> str:
        self.legacy_calls.append((name, args))
        return "legacy result"

    async def execute_tool_call(
        self,
        call: ToolCall,
        *,
        agent_name: str,
        delegation_depth: int,
        tool_round: int,
    ) -> str:
        self.calls.append((call, agent_name, delegation_depth, tool_round))
        return "hook result"


def _agent(
    strategy_name: str,
    executor: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str = "searcher",
    grant: bool = True,
    traced: bool = False,
) -> tuple[Agent, FauxProvider]:
    strategy: ReactStrategy | ArtificerStrategy
    provider = FauxProvider()
    if strategy_name == "artificer":
        monkeypatch.setattr(artificer_module, "asyncio", SimpleNamespace(sleep=_no_sleep))
        strategy = ArtificerStrategy()
        provider.seed(FauxResponse(content="1. Search twice."))
    else:
        strategy = ReactStrategy()
    for query in ("first", "second"):
        provider.seed(
            FauxResponse(
                tool_calls=[ToolCallDef("lookup", {"query": query}, call_id="provider/reused:id")]
            )
        )
    provider.seed(FauxResponse(content="done"))
    warden = Warden()
    agent = Agent(
        identity=AgentIdentity(name=name, model="faux://test-model", tools=("lookup",)),
        strategy=strategy,
        llm=provider,
        context_builder=ContextBuilder(),
        prompt_manager=InMemoryPromptManager(),
        warden=warden,
        sentinel=Sentinel(
            warden=warden,
            permission_table={"lookup": frozenset({"operator" if grant else "admin"})},
        ),
        tool_executor=executor,
        tracer=MagicMock() if traced else None,
    )
    return agent, provider


@pytest.mark.parametrize("strategy_name", ["react", "artificer"])
@pytest.mark.parametrize(("agent_name", "depth"), [("searcher", 0), ("delegate", 2)])
@pytest.mark.parametrize("traced", [False, True])
async def test_real_loops_preserve_provider_id_agent_depth_and_response_round(
    strategy_name: str,
    agent_name: str,
    depth: int,
    traced: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = _RecordingExecutor()
    agent, provider = _agent(strategy_name, executor, monkeypatch, name=agent_name, traced=traced)

    response = await agent.handle(
        [{"role": "user", "content": "Search twice."}],
        _CALLER,
        _delegation_depth=depth,
    )

    assert response.content.endswith("done")
    assert executor.legacy_calls == []
    assert executor.calls == [
        (ToolCall("provider/reused:id", "lookup", {"query": "first"}), agent_name, depth, 0),
        (ToolCall("provider/reused:id", "lookup", {"query": "second"}), agent_name, depth, 1),
    ]
    assert provider.call_count == (4 if strategy_name == "artificer" else 3)

    # A new Attempt that repeats these provider calls carries the same logical
    # identity. It must not pick up a process-local execution counter.
    provider.reset()
    await agent.handle(
        [{"role": "user", "content": "Search twice."}], _CALLER, _delegation_depth=depth
    )
    assert executor.calls[2:] == executor.calls[:2]


@pytest.mark.parametrize("strategy_name", ["react", "artificer"])
async def test_agent_denial_precedes_identity_hook(
    strategy_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor = _RecordingExecutor()
    agent, provider = _agent(strategy_name, executor, monkeypatch, grant=False)

    await agent.handle([{"role": "user", "content": "Search twice."}], _CALLER)

    assert executor.calls == []
    assert executor.legacy_calls == []
    assert [
        message["content"]
        for message in provider.call_log[-1]["messages"]
        if message.get("role") == "tool"
    ] == ["Error: Permission denied for tool 'lookup'"] * 2


@pytest.mark.parametrize("strategy_name", ["react", "artificer"])
@pytest.mark.parametrize("mock_executor", [False, True])
async def test_ordinary_two_argument_executors_keep_their_contract(
    strategy_name: str, mock_executor: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(name: str, args: dict[str, Any]) -> str:
        calls.append((name, args))
        return "legacy result"

    executor = AsyncMock(side_effect=execute) if mock_executor else execute
    agent, _ = _agent(strategy_name, executor, monkeypatch)

    response = await agent.handle([{"role": "user", "content": "Search twice."}], _CALLER)

    assert response.content.endswith("done")
    assert calls == [("lookup", {"query": "first"}), ("lookup", {"query": "second"})]


async def test_agent_overrides_supplied_identity_and_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = _RecordingExecutor()
    agent, _ = _agent("react", executor, monkeypatch, name="trusted-agent")
    governed = agent._governed_tool_executor(
        None, {"auth": _CALLER, "delegation_depth": 99}, delegation_depth=2
    )
    call = ToolCall("provider-id", "lookup", {"agent_name": "forged", "delegation_depth": 99})

    await dispatch_tool_call(governed, call, agent_name="forged", delegation_depth=99, tool_round=3)

    assert executor.calls == [(call, "trusted-agent", 2, 3)]
    assert executor.legacy_calls == []


async def test_real_delegation_passes_child_name_and_incremented_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = _RecordingExecutor()
    child, _ = _agent("react", executor, monkeypatch, name="child")
    parent = Agent(
        identity=AgentIdentity(name="parent", model="faux://test-model"),
        strategy=DelegateStrategy(routing_table={}, default_agent="child"),
        llm=FauxProvider(),
        context_builder=ContextBuilder(),
        prompt_manager=InMemoryPromptManager(),
        warden=Warden(),
        agent_resolver={"child": child},
    )

    result = await parent.handle([{"role": "user", "content": "Search twice."}], _CALLER)

    assert result.content == "done"
    assert [(name, depth, round_num) for _, name, depth, round_num in executor.calls] == [
        ("child", 1, 0),
        ("child", 1, 1),
    ]


async def test_legacy_adapter_does_not_invent_provider_identity() -> None:
    calls: list[tuple[ToolCall, str, int, int]] = []

    async def execute(call: ToolCall, name: str, depth: int, round_num: int) -> str:
        calls.append((call, name, depth, round_num))
        return "result"

    executor = ToolCallExecutor(execute)

    assert await executor("lookup", {"query": "first"}) == "result"
    assert await executor("lookup", {"query": "first"}) == "result"
    assert calls == [(ToolCall("", "lookup", {"query": "first"}), "", 0, 0)] * 2


async def test_authorization_repairs_arguments_without_changing_provider_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = _RecordingExecutor()
    agent, _ = _agent("react", executor, monkeypatch)
    agent._sentinel = SimpleNamespace(
        pre_call=AsyncMock(
            return_value=SimpleNamespace(allowed=True, repaired_data={"query": "safe"})
        ),
        post_call=AsyncMock(return_value="safe result"),
    )
    governed = agent._governed_tool_executor(None, {"auth": _CALLER}, delegation_depth=1)

    result = await governed.execute_tool_call(
        ToolCall("provider-id", "lookup", {"query": 1}), tool_round=2
    )

    assert result == "safe result"
    assert executor.calls == [
        (ToolCall("provider-id", "lookup", {"query": "safe"}), "searcher", 1, 2)
    ]


async def test_noncallable_optional_hook_preserves_legacy_dispatch():
    class LegacyExecutor:
        execute_tool_call = object()

        async def __call__(self, name, args):
            return {"name": name, "args": args}

    result = await dispatch_tool_call(
        LegacyExecutor(), ToolCall(id="original-id", name="lookup", arguments={"query": "term"})
    )
    assert result == {"name": "lookup", "args": {"query": "term"}}
