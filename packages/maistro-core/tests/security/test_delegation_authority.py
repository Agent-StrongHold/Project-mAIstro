"""Regression tests for host-authorized delegation envelopes (#845)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.agents.base import Agent
from maistro.security._types import AuthContext
from maistro.security.sentinel.authz_types import Principal, Tier
from maistro.security.sentinel.delegation import (
    DelegationGrant,
    DelegationRequest,
    InMemoryDelegationAuthority,
)
from maistro.security.sentinel.policy import Sentinel
from maistro.security.warden.detector import Warden
from maistro.types.agent import AgentIdentity, ReasoningResult


@dataclass
class _Clean:
    clean: bool = True
    flags: tuple[str, ...] = ()


class _Warden:
    async def scan(self, _text: str, _surface: str) -> _Clean:
        return _Clean()


class _Context:
    async def build(
        self, messages: list[dict[str, Any]], _identity: Any, **_: Any
    ) -> tuple[list[dict[str, Any]], list[int]]:
        return messages, []


class _Prompt:
    async def get(self, _name: str) -> str:
        return ""


class _Result:
    def __init__(self, result: ReasoningResult) -> None:
        self.result = result
        self.auth: Any = None
        self.calls = 0

    async def reason(
        self, _messages: Any, _model: str, _llm: Any, **kwargs: Any
    ) -> ReasoningResult:
        self.calls += 1
        self.auth = kwargs.get("auth")
        return self.result


def _grant(*, actions: frozenset[str]) -> DelegationGrant:
    return DelegationGrant(
        grant_id="grant-1",
        principal_id="low-agent",
        owner_id="owner-1",
        delegating_agent_id="low-agent",
        target_agent_id="writer",
        goal_id="goal-1",
        run_id="run-1",
        invocation_id="inv-1",
        scope="project-1",
        action="agent.delegate",
        actions=actions,
        artifact="delegate this exact task",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        granted_by="host-policy",
        provenance="human-approval:approval-1",
    )


def _request(*, actions: frozenset[str]) -> DelegationRequest:
    principal = Principal(
        id="low-agent",
        kind="agent",
        owner="owner-1",
        scopes=("project-1", "agent:low-agent"),
    )
    return DelegationRequest(
        principal=principal,
        owner_id="owner-1",
        delegating_agent_id="low-agent",
        target_agent_id="writer",
        goal_id="goal-1",
        run_id="run-1",
        invocation_id="inv-1",
        scope="project-1",
        action="agent.delegate",
        requested_actions=actions,
        artifact="delegate this exact task",
        requested_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_host_grant_returns_only_the_explicit_action_subset() -> None:
    authority = InMemoryDelegationAuthority([_grant(actions=frozenset({"read_file"}))])
    decision = await authority.authorize(
        _request(actions=frozenset({"read_file", "write_file"})), now=datetime.now(UTC)
    )

    assert decision.allowed is True
    assert decision.effective_actions == frozenset({"read_file"})
    assert decision.grant_id == "grant-1"


@pytest.mark.asyncio
async def test_an_approval_for_another_artifact_cannot_be_reused() -> None:
    authority = InMemoryDelegationAuthority([_grant(actions=frozenset({"read_file"}))])
    request = _request(actions=frozenset({"read_file"}))
    mismatched = request.__class__(**{**request.__dict__, "artifact": "different task"})

    decision = await authority.authorize(mismatched, now=datetime.now(UTC))

    assert decision.allowed is False
    assert "no host grant" in decision.reason


def test_auth_context_enforces_the_effective_subset() -> None:
    auth = AuthContext(
        user_id="owner-1",
        roles=frozenset({"user"}),
        delegated_actions=frozenset({"read_file"}),
        delegation_grant_id="grant-1",
    )
    table = {"read_file": frozenset({"user"}), "write_file": frozenset({"user"})}

    assert auth.can_use_tool("read_file", table) is True
    assert auth.can_use_tool("write_file", table) is False


def test_an_expired_delegated_grant_authorizes_no_tool() -> None:
    """Deliberation past the grant's expiry must not extend authority."""
    expired = AuthContext(
        user_id="owner-1",
        roles=frozenset({"user"}),
        delegated_actions=frozenset({"read_file"}),
        delegation_grant_id="grant-1",
        delegation_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    live = AuthContext(
        user_id="owner-1",
        roles=frozenset({"user"}),
        delegated_actions=frozenset({"read_file"}),
        delegation_grant_id="grant-1",
        delegation_expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    table = {"read_file": frozenset({"user"})}

    assert expired.can_use_tool("read_file", table) is False
    assert live.can_use_tool("read_file", table) is True


@pytest.mark.asyncio
async def test_execution_mode_requires_a_cleared_host_tier() -> None:
    principal = Principal(id="owner-1", kind="human", roles=("user",))
    default_sentinel = Sentinel(warden=Warden(), permission_table={}, allow_on_miss=True)
    assert (
        await default_sentinel.resolve_authorized_execution_mode(
            "graph.node.execute", principal, args={"node_id": "n1"}
        )
        == "blocked"
    )

    role_sentinel = Sentinel(
        warden=Warden(),
        permission_table={},
        tier_policy={("graph.node.execute", "user"): Tier.ROLE_AUTO},
        allow_on_miss=True,
    )
    assert (
        await role_sentinel.resolve_authorized_execution_mode(
            "graph.node.execute", principal, args={"node_id": "n1"}
        )
        == "async"
    )


def _shipped_composition_sentinel() -> Sentinel:
    """Sentinel composed exactly as ``create_container`` wires it."""
    from maistro.capabilities.bootstrap import default_capability_registry
    from maistro.container import _configure_host_tier_policy
    from maistro.security.permission_policy import build_permission_table
    from maistro.security.sentinel.permission_source import CapabilityPermissionSource

    table = build_permission_table(preset="none", permissions={})
    return Sentinel(
        warden=Warden(),
        permission_table=table,
        permission_source=CapabilityPermissionSource(
            base=table,
            capabilities=default_capability_registry(),
        ),
        tier_policy=_configure_host_tier_policy(),
    )


@pytest.mark.asyncio
async def test_the_shipped_composition_keeps_benign_graph_nodes_runnable() -> None:
    """Regression: the wired composition must not deny every node (#845).

    Graph node actions are synthetic, so the fail-closed tool table never
    names them; the shipped host tier record authorizes an authenticated
    human principal's benign node inline.
    """
    sentinel = _shipped_composition_sentinel()
    principal = Principal(id="u-1", kind="human", roles=("user",), scopes=("ws-1", "proj-1", "u-1"))
    assert (
        await sentinel.resolve_authorized_execution_mode(
            "graph.node.execute",
            principal,
            args={"node_id": "n1", "artifact": "task"},
            reversibility="irreversible",
            default=Tier.SELF_ELEVATION,
        )
        == "async"
    )


@pytest.mark.asyncio
async def test_an_anonymous_caller_cannot_run_graph_nodes() -> None:
    sentinel = _shipped_composition_sentinel()
    principal = Principal(id="anonymous", kind="human")
    assert (
        await sentinel.resolve_authorized_execution_mode(
            "graph.node.execute",
            principal,
            args={"node_id": "n1", "artifact": "task"},
            reversibility="irreversible",
            default=Tier.SELF_ELEVATION,
        )
        == "blocked"
    )


@pytest.mark.asyncio
async def test_an_untrusted_node_stays_blocked_under_the_shipped_composition() -> None:
    sentinel = _shipped_composition_sentinel()
    principal = Principal(id="u-1", kind="human", roles=("user",), scopes=("ws-1",))
    assert (
        await sentinel.resolve_authorized_execution_mode(
            "graph.node.untrusted",
            principal,
            args={"node_id": "n1", "artifact": "task"},
            reversibility="irreversible",
            default=Tier.BLOCKED,
        )
        == "blocked"
    )


@pytest.mark.asyncio
async def test_host_grant_allows_only_its_action_subset() -> None:
    authority = InMemoryDelegationAuthority([_grant(actions=frozenset({"read_file"}))])
    sentinel = Sentinel(warden=Warden(), permission_table={}, delegation_authority=authority)
    target_strategy = _Result(ReasoningResult(response="writer ran"))
    target = Agent(
        identity=AgentIdentity(name="writer", tools=("read_file", "write_file")),
        strategy=target_strategy,
        llm=object(),
        context_builder=_Context(),
        prompt_manager=_Prompt(),
        warden=_Warden(),
        sentinel=sentinel,
    )
    caller = Agent(
        identity=AgentIdentity(name="low-agent", sub_agents=("writer",)),
        strategy=_Result(
            ReasoningResult(delegate_to="writer", delegate_message="delegate this exact task")
        ),
        llm=object(),
        context_builder=_Context(),
        prompt_manager=_Prompt(),
        warden=_Warden(),
        sentinel=sentinel,
        agent_resolver={"writer": target}.get,
    )

    response = await caller.handle(
        [{"role": "user", "content": "delegate"}],
        AuthContext(user_id="owner-1", project_id="project-1"),
        session_id="goal-1",
        run_id="run-1",
        invocation_id="inv-1",
        delegation_scope="project-1",
    )

    assert response.content == "writer ran"
    assert target_strategy.auth.delegated_actions == frozenset({"read_file"})
    assert target_strategy.auth.delegation_grant_id == "grant-1"


@pytest.mark.asyncio
async def test_agent_manifest_cannot_delegate_without_host_grant() -> None:
    authority = InMemoryDelegationAuthority()
    sentinel = Sentinel(warden=Warden(), permission_table={}, delegation_authority=authority)
    target_strategy = _Result(ReasoningResult(response="writer ran"))
    target = Agent(
        identity=AgentIdentity(name="writer", tools=("write_file",)),
        strategy=target_strategy,
        llm=object(),
        context_builder=_Context(),
        prompt_manager=_Prompt(),
        warden=_Warden(),
        sentinel=sentinel,
    )
    caller = Agent(
        identity=AgentIdentity(
            name="low-agent", delegation_mode="allow_list", sub_agents=("writer",)
        ),
        strategy=_Result(
            ReasoningResult(delegate_to="writer", delegate_message="delegate this exact task")
        ),
        llm=object(),
        context_builder=_Context(),
        prompt_manager=_Prompt(),
        warden=_Warden(),
        sentinel=sentinel,
        agent_resolver={"writer": target}.get,
    )

    response = await caller.handle(
        [{"role": "user", "content": "delegate"}],
        AuthContext(user_id="owner-1", project_id="project-1"),
        session_id="goal-1",
        run_id="run-1",
        invocation_id="inv-1",
        delegation_scope="project-1",
    )

    assert response.content.startswith("Delegation refused:")
    assert target_strategy.calls == 0
