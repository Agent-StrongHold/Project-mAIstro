"""Tests that the delegate reasoning strategy actually delegates.

Pins the contract described in the delegation bug report:

- ``Agent.handle()`` must honor ``ReasoningResult.delegate_to`` by invoking the
  resolved sub-agent and returning *its* non-empty response (not an empty
  string from the delegating agent).
- ``classified_task_type`` must be threaded from ``handle()`` into the strategy
  so the intent routing table in ``DelegateStrategy`` is actually used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maistro.agents.base import Agent
from maistro.agents.strategies.delegate import DelegateStrategy
from maistro.types.agent import AgentIdentity, AgentResponse


@dataclass
class _Verdict:
    clean: bool = True
    flags: tuple[str, ...] = ()


class _FakeWarden:
    async def scan(self, _text: str, _surface: str) -> _Verdict:
        return _Verdict()


class _FakeContextBuilder:
    async def build(
        self, messages: list[dict[str, Any]], _identity: Any, **_kwargs: Any
    ) -> tuple[list[dict[str, Any]], list[int]]:
        return messages, []


class _FakePromptManager:
    async def get(self, _name: str) -> str:
        return ""


class _RecordingStrategy:
    """A leaf strategy that records the kwargs it was called with."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: Any,
        **kwargs: Any,
    ) -> Any:
        from maistro.types.agent import ReasoningResult

        self.calls.append({"messages": messages, "model": model, **kwargs})
        return ReasoningResult(response=self.response, done=True)


def _make_agent(
    name: str,
    strategy: Any,
    *,
    agent_resolver: Any = None,
) -> Agent:
    identity = AgentIdentity(name=name, model="test-model")
    return Agent(
        identity=identity,
        strategy=strategy,
        llm=object(),
        context_builder=_FakeContextBuilder(),
        prompt_manager=_FakePromptManager(),
        warden=_FakeWarden(),
        agent_resolver=agent_resolver,
    )


class _Auth:
    user_id = "u1"
    org_id = ""
    team_id = ""


class TestDelegation:
    async def test_routes_by_task_type_and_returns_delegate_response(self) -> None:
        """code -> mason: handle() must return mason's non-empty response."""
        registry: dict[str, Agent] = {}
        mason = _make_agent("mason", _RecordingStrategy("def add(): ..."))
        registry["mason"] = mason

        delegate_strategy = DelegateStrategy(routing_table={"code": "mason"}, default_agent="mason")
        coordinator = _make_agent(
            "coordinator",
            delegate_strategy,
            agent_resolver=registry.get,
        )
        registry["coordinator"] = coordinator

        result = await coordinator.handle(
            messages=[{"role": "user", "content": "write me a function"}],
            auth=_Auth(),
            classified_task_type="code",
        )

        assert isinstance(result, AgentResponse)
        assert result.content == "def add(): ..."
        assert result.agent_name == "mason"

    async def test_classified_task_type_threaded_to_strategy(self) -> None:
        """The default 'chat' must not silently shadow the real task type."""
        registry: dict[str, Agent] = {}
        ranger = _make_agent("ranger", _RecordingStrategy("search results"))
        registry["ranger"] = ranger

        # Only 'search' is routed; 'code' would fall through to default.
        delegate_strategy = DelegateStrategy(routing_table={"search": "ranger"}, default_agent="")
        coordinator = _make_agent("coordinator", delegate_strategy, agent_resolver=registry.get)

        result = await coordinator.handle(
            messages=[{"role": "user", "content": "find the docs"}],
            auth=_Auth(),
            classified_task_type="search",
        )

        assert result.content == "search results"
        assert result.agent_name == "ranger"

    async def test_no_route_and_no_default_returns_gracefully(self) -> None:
        """When nothing matches and there is no default, do not crash."""
        registry: dict[str, Agent] = {}
        delegate_strategy = DelegateStrategy(routing_table={}, default_agent="")
        coordinator = _make_agent("coordinator", delegate_strategy, agent_resolver=registry.get)

        result = await coordinator.handle(
            messages=[{"role": "user", "content": "hello"}],
            auth=_Auth(),
            classified_task_type="chat",
        )

        # No target resolved -> empty content, but the delegating agent answers.
        assert isinstance(result, AgentResponse)
        assert result.agent_name == "coordinator"
        assert result.content == ""


class TestTheDelegationChainIsRecorded:
    """Who was asked, not only who answered (#225, ADR-082426-6201).

    An in-agent delegation is deliberately *not* a NodeRun — the delegate is
    chosen by a strategy at runtime, from data the Graph never saw, and a
    NodeRun projects a Node in the Graph. So the chain is recorded on the
    answer instead, which is the whole of what the decision costs and the whole
    of what pays for it.

    Before this, `_delegate` returned the delegate's response wholesale and the
    agent that was actually asked appeared nowhere — including on the Attempt,
    which #223 taught to record the handling agent.
    """

    async def test_the_delegator_is_named_on_the_answer(self) -> None:
        registry: dict[str, Agent] = {}
        registry["mason"] = _make_agent("mason", _RecordingStrategy("def add(): ..."))
        coordinator = _make_agent(
            "coordinator",
            DelegateStrategy(routing_table={"code": "mason"}, default_agent="mason"),
            agent_resolver=registry.get,
        )

        result = await coordinator.handle(
            messages=[{"role": "user", "content": "write me a function"}],
            auth=_Auth(),
            classified_task_type="code",
        )

        assert result.agent_name == "mason"
        assert result.delegation_chain == ("coordinator",)

    async def test_the_chain_is_outermost_first_however_deep_it_went(self) -> None:
        """Each level prepends on the way back out, so a reader gets the order
        the delegation happened in rather than the order it unwound."""
        registry: dict[str, Agent] = {}
        registry["mason"] = _make_agent("mason", _RecordingStrategy("done"))
        registry["middle"] = _make_agent(
            "middle",
            DelegateStrategy(routing_table={"code": "mason"}, default_agent="mason"),
            agent_resolver=registry.get,
        )
        outer = _make_agent(
            "outer",
            DelegateStrategy(routing_table={"code": "middle"}, default_agent="middle"),
            agent_resolver=registry.get,
        )

        result = await outer.handle(
            messages=[{"role": "user", "content": "go"}],
            auth=_Auth(),
            classified_task_type="code",
        )

        assert result.content == "done"
        assert result.agent_name == "mason"
        assert result.delegation_chain == ("outer", "middle")

    async def test_a_turn_that_delegates_to_nobody_carries_an_empty_chain(self) -> None:
        """The overwhelming majority of turns. An empty tuple rather than a
        one-element chain naming the agent that answered: the field records who
        *delegated*, and reading it as a list of participants would make every
        ordinary turn look like a delegation of depth one."""
        registry: dict[str, Agent] = {}
        coordinator = _make_agent(
            "coordinator",
            DelegateStrategy(routing_table={}, default_agent=""),
            agent_resolver=registry.get,
        )

        result = await coordinator.handle(
            messages=[{"role": "user", "content": "hello"}],
            auth=_Auth(),
            classified_task_type="chat",
        )

        assert result.agent_name == "coordinator"
        assert result.delegation_chain == ()
