"""Behavioral proof that available sub-agents do not force decomposition (#47)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maistro.agents.base import Agent
from maistro.types.agent import AgentIdentity, ReasoningResult


@dataclass(frozen=True)
class _Verdict:
    clean: bool = True
    flags: tuple[str, ...] = ()


class _Warden:
    async def scan(self, _text: str, _surface: str) -> _Verdict:
        return _Verdict()


class _ContextBuilder:
    async def build(
        self, messages: list[dict[str, Any]], _identity: AgentIdentity, **_kwargs: Any
    ) -> tuple[list[dict[str, Any]], list[int]]:
        return messages, []


class _PromptManager:
    pass


class _Strategy:
    def __init__(self, result: ReasoningResult) -> None:
        self.result = result
        self.calls = 0

    async def reason(
        self,
        _messages: list[dict[str, Any]],
        _model: str,
        _llm: Any,
        **_kwargs: Any,
    ) -> ReasoningResult:
        self.calls += 1
        return self.result


class _Auth:
    user_id = "u1"
    org_id = "org-1"
    team_id = "team-1"


def _agent(
    *,
    name: str,
    strategy: _Strategy,
    delegation_mode: str = "none",
    sub_agents: tuple[str, ...] = (),
    resolver: Any = None,
) -> Agent:
    return Agent(
        identity=AgentIdentity(
            name=name,
            model="test-model",
            delegation_mode=delegation_mode,
            sub_agents=sub_agents,
        ),
        strategy=strategy,
        llm=object(),
        context_builder=_ContextBuilder(),
        prompt_manager=_PromptManager(),
        warden=_Warden(),
        agent_resolver=resolver,
    )


async def test_available_sub_agent_is_not_forced_without_actor_request() -> None:
    """Capability to delegate does not itself decompose an ordinary turn.

    The coordinator is explicitly configured for sub-agent delegation and the
    target resolves successfully. Its reasoning strategy nevertheless answers
    locally and does not request ``delegate_to``. The target must remain idle.
    Existing delegation tests cover the positive half: when the strategy does
    request ``delegate_to``, the resolved target is invoked.
    """
    sub_strategy = _Strategy(ReasoningResult(response="sub should not run", done=True))
    sub_agent = _agent(name="sub", strategy=sub_strategy)
    coordinator_strategy = _Strategy(
        ReasoningResult(response="coordinator answered", done=True)
    )
    coordinator = _agent(
        name="coordinator",
        strategy=coordinator_strategy,
        delegation_mode="sub_agents",
        sub_agents=("sub",),
        resolver={"sub": sub_agent}.get,
    )

    response = await coordinator.handle(
        messages=[{"role": "user", "content": "answer if you can"}],
        auth=_Auth(),
    )

    assert response.content == "coordinator answered"
    assert response.agent_name == "coordinator"
    assert coordinator_strategy.calls == 1
    assert sub_strategy.calls == 0
