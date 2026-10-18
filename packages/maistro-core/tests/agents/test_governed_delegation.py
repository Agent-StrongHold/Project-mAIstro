"""Tail delegation shares canonical execution, never a logical model effect."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from tests._admitted_model_fixture import setup

from maistro.agents.base import Agent
from maistro.agents.context_builder import ContextBuilder
from maistro.agents.strategies.delegate import DelegateStrategy
from maistro.agents.strategies.direct import DirectStrategy
from maistro.capabilities.invocation import InvocationStatus
from maistro.capabilities.model_chat import GovernedLLMClient
from maistro.http import set_test_transport
from maistro.observability.correlation import bind_execution_context
from maistro.prompts.store import InMemoryPromptManager
from maistro.security._types import AuthContext
from maistro.security.warden.detector import Warden
from maistro.types.agent import AgentIdentity, ReasoningResult


class _ModelThenDelegate:
    def __init__(self, handoffs: dict[str, tuple[str, str]], *, stream: bool = False) -> None:
        self.stream = stream
        self.handoffs = handoffs
        self.answers: list[tuple[str, str]] = []

    async def reason(
        self, messages: list[dict[str, Any]], model: str, llm: Any, **kwargs: Any
    ) -> ReasoningResult:
        if self.stream:
            chunks = [chunk async for chunk in llm.stream(messages, model)]
            answer = "".join(
                choice["delta"].get("content", "")
                for chunk in chunks
                for choice in chunk.get("choices", [])
            )
        else:
            body = await llm.complete(messages, model)
            answer = body["choices"][0]["message"]["content"]
        prompt = next(
            str(message["content"]) for message in reversed(messages) if message["role"] == "user"
        )
        self.answers.append((prompt, answer))
        target, delegated_prompt = self.handoffs.get(prompt, ("", ""))
        return ReasoningResult(
            response=answer,
            done=not target,
            delegate_to=target or None,
            delegate_message=delegated_prompt or None,
        )


def _agent(name: str, strategy: Any, llm: Any, roster: dict[str, Agent]) -> Agent:
    agent = Agent(
        AgentIdentity(name=name, model="request-alias"),
        strategy,
        llm=llm,
        context_builder=ContextBuilder(),
        prompt_manager=InMemoryPromptManager(),
        warden=Warden(),
        agent_resolver=roster.get,
    )
    roster[name] = agent
    return agent


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("chain", [("parent", "child"), ("same", "same"), ("a", "b", "a")])
async def test_model_before_delegation_has_distinct_effects_and_replays(
    chain: tuple[str, ...], stream: bool
) -> None:
    s = await setup()
    llm = GovernedLLMClient(s.calls)
    prompts = [f"request at step {depth}" for depth in range(len(chain))]
    strategies = {name: _ModelThenDelegate({}, stream=stream) for name in chain}
    for depth, name in enumerate(chain[:-1]):
        strategies[name].handoffs[prompts[depth]] = (chain[depth + 1], prompts[depth + 1])
    roster: dict[str, Agent] = {}
    for name, strategy in strategies.items():
        _agent(name, strategy, llm, roster)
    sent: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        prompt = next(
            message["content"]
            for message in reversed(payload["messages"])
            if message["role"] == "user"
        )
        sent.append(prompt)
        if payload.get("stream"):
            chunks = [
                {"choices": [{"index": 0, "delta": {"content": f"answer to {prompt}"}}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}},
            ]
            body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            return httpx.Response(200, content=(body + "data: [DONE]\n\n").encode())
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": f"answer to {prompt}"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
        )

    set_test_transport(httpx.MockTransport(transport))
    with bind_execution_context(
        run_id=s.identity[0], node_run_id=s.identity[1], attempt_id=s.identity[2]
    ):
        response = await roster[chain[0]].handle(
            [{"role": "user", "content": prompts[0]}],
            AuthContext(user_id="admitted-actor"),
            turn_id="a-domain-turn-not-the-run",
        )
        assert not response.failed, response.error
        assert response.content == f"answer to {prompts[-1]}"
        assert response.delegation_chain == chain[:-1]
        assert sent == prompts
        # Replaying the same tail-delegation chain reuses each corresponding
        # logical effect, including a second visit to the same declared Agent.
        replay = await roster[chain[0]].handle(
            [{"role": "user", "content": prompts[0]}],
            AuthContext(user_id="admitted-actor"),
            turn_id="a-domain-turn-not-the-run",
        )
        assert replay.content == response.content
        assert sent == prompts
    assert len(await s.runs.list_node_runs(s.identity[0])) == 1
    assert len(await s.runs.list_attempts(s.identity[1])) == 1
    for depth, name in enumerate(chain):
        (invocation,) = await s.effects.invocation_store.list_effect(
            run_id=s.identity[0],
            node_run_id=s.identity[1],
            binding_id="declared",
            effect_key=f"agent-llm:{name}:{depth}:1",
        )
        assert invocation.status is InvocationStatus.COMPLETED
        assert invocation.actor_id == "admitted-actor"
        assert invocation.attempt_id == s.identity[2]
        assert invocation.usage.input_units == 7
        assert invocation.usage.output_units == 3
        events = [
            event
            for event in s.effects.usage_log.events_for("request-alias")
            if event.invocation_id == invocation.invocation_id
        ]
        assert len(events) == 1
        assert (events[0].input_tokens, events[0].output_tokens) == (7, 3)
        assert strategies[name].answers.count((prompts[depth], f"answer to {prompts[depth]}")) == 2


async def test_builtin_delegate_chain_still_makes_one_leaf_call() -> None:
    s = await setup()
    llm = GovernedLLMClient(s.calls)
    roster: dict[str, Agent] = {}
    _agent("leaf", DirectStrategy(), llm, roster)
    _agent("middle", DelegateStrategy({}, default_agent="leaf"), llm, roster)
    outer = _agent("outer", DelegateStrategy({}, default_agent="middle"), llm, roster)
    with bind_execution_context(
        run_id=s.identity[0], node_run_id=s.identity[1], attempt_id=s.identity[2]
    ):
        response = await outer.handle(
            [{"role": "user", "content": "hello"}], AuthContext(user_id="admitted-actor")
        )
    assert response.content == "answer"
    assert response.delegation_chain == ("outer", "middle")
    assert len(s.sent) == 1
    assert json.loads(s.sent[0].content)["messages"][-1]["content"] == "hello"


async def test_clients_with_original_set_turn_signature_keep_working() -> None:
    calls: list[tuple[str, str]] = []

    class OriginalClient:
        def set_turn(self, *, agent_name: str) -> None:
            calls.append(("set", agent_name))

        def clear_turn(self) -> None:
            calls.append(("clear", ""))

        async def complete(self, messages: Any, model: str, **kwargs: Any) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "legacy client answer"}}]}

    llm = OriginalClient()
    roster: dict[str, Agent] = {}
    _agent("leaf", DirectStrategy(), llm, roster)
    outer = _agent("outer", DelegateStrategy({}, default_agent="leaf"), llm, roster)
    response = await outer.handle(
        [{"role": "user", "content": "hello"}], AuthContext(user_id="actor")
    )
    assert response.content == "legacy client answer"
    assert calls == [("set", "outer"), ("clear", ""), ("set", "leaf"), ("clear", "")]
