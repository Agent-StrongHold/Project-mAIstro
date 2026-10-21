"""Regression tests for host-authorized delegation envelopes (#845)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.agents.base import Agent
from maistro.security._types import AuthContext
from maistro.security.sentinel.audit import InMemoryAuditLog
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
        grant_ref="grant-1",
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


def test_host_grant_returns_only_the_explicit_action_subset() -> None:
    # Grants enter only through the host-owned mutation API; no AgentIdentity
    # or manifest field can provision one (#845).
    authority = InMemoryDelegationAuthority()
    authority.add_host_grant(_grant(actions=frozenset({"read_file"})))
    decision = authority.authorize(
        _request(actions=frozenset({"read_file", "write_file"})), now=datetime.now(UTC)
    )

    assert decision.allowed is True
    assert decision.effective_actions == frozenset({"read_file"})
    assert decision.grant_ref == "grant-1"
    assert decision.granted_by == "host-policy"


def test_an_approval_for_another_artifact_cannot_be_reused() -> None:
    authority = InMemoryDelegationAuthority()
    authority.add_host_grant(_grant(actions=frozenset({"read_file"})))
    request = _request(actions=frozenset({"read_file"}))
    mismatched = request.__class__(**{**request.__dict__, "artifact": "different task"})

    decision = authority.authorize(mismatched, now=datetime.now(UTC))

    assert decision.allowed is False
    assert "no host grant" in decision.reason


def test_auth_context_enforces_the_effective_subset() -> None:
    auth = AuthContext(
        user_id="owner-1",
        roles=frozenset({"user"}),
        delegated_actions=frozenset({"read_file"}),
    )
    table = {"read_file": frozenset({"user"}), "write_file": frozenset({"user"})}

    assert auth.can_use_tool("read_file", table) is True
    assert auth.can_use_tool("write_file", table) is False


def test_authorize_rejects_a_non_agent_principal() -> None:
    # The host-owned decision point only accepts an agent principal; a human
    # principal is not a delegated authority request.
    authority = InMemoryDelegationAuthority([_grant(actions=frozenset({"read_file"}))])
    request = replace(
        _request(actions=frozenset({"read_file"})),
        principal=Principal(id="owner-1", kind="human", owner="owner-1"),
    )

    decision = authority.authorize(request, now=datetime.now(UTC))

    assert decision.allowed is False
    assert decision.reason == "delegation principal must be an agent"


def test_authorize_rejects_an_owner_that_does_not_match_the_principal() -> None:
    authority = InMemoryDelegationAuthority([_grant(actions=frozenset({"read_file"}))])
    request = replace(
        _request(actions=frozenset({"read_file"})),
        owner_id="someone-else",
    )

    decision = authority.authorize(request, now=datetime.now(UTC))

    assert decision.allowed is False
    assert decision.reason == "delegation owner does not match principal"


def test_authorize_skips_an_expired_grant() -> None:
    # A grant that lapsed before the call must not authorize, and must not
    # short-circuit the search for a later valid one.
    expired = replace(
        _grant(actions=frozenset({"read_file"})),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    authority = InMemoryDelegationAuthority([expired])

    decision = authority.authorize(
        _request(actions=frozenset({"read_file"})), now=datetime.now(UTC)
    )

    assert decision.allowed is False
    assert decision.reason == "no host grant matches this delegation"


@pytest.mark.asyncio
async def test_authorize_delegation_without_configured_authority_is_refused() -> None:
    # A Sentinel with no host authority must refuse, never consult the
    # manifest roster as an implicit allow-list.
    sentinel = Sentinel(warden=Warden(), permission_table={})

    decision = await sentinel.authorize_delegation(
        principal=Principal(id="low-agent", kind="agent", owner="owner-1"),
        owner_id="owner-1",
        delegating_agent_id="low-agent",
        target_agent_id="writer",
        goal_id="goal-1",
        run_id="run-1",
        invocation_id="inv-1",
        scope="project-1",
        requested_actions=frozenset(),
        artifact="task",
    )

    assert decision.allowed is False
    assert decision.reason == "delegation authority is not configured"


def test_resolve_tier_returns_the_explicit_default_when_no_policy_matches() -> None:
    # `default` is the compatibility adapter's untrusted shape; the host tier
    # policy is empty, so the explicit default decides.
    sentinel = Sentinel(warden=Warden(), permission_table={}, tier_policy={})
    principal = Principal(id="u", kind="human", roles=("user",))

    assert (
        sentinel.resolve_tier("tool.x", principal, default=Tier.SELF_ELEVATION)
        is Tier.SELF_ELEVATION
    )


@pytest.mark.asyncio
async def test_pre_call_audit_names_the_host_grant_ref() -> None:
    # A delegated call's audit must name the host grant it rests on, not the
    # agent that asked for it.
    audit = InMemoryAuditLog()
    sentinel = Sentinel(
        warden=Warden(),
        permission_table={},
        allow_on_miss=True,
        audit_log=audit,
    )
    auth = AuthContext(
        user_id="owner-1",
        roles=frozenset({"user"}),
        delegation_grant_ref="grant-1",
    )

    verdict = await sentinel.pre_call("read_file", {}, auth, schema={})

    assert verdict.allowed is True
    assert audit._entries, "pre_call must write an audit entry"
    assert any("delegation_grant_ref=grant-1" in (entry.detail or "") for entry in audit._entries)


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
    assert target_strategy.auth.delegation_grant_ref == "grant-1"


@pytest.mark.asyncio
async def test_delegated_envelope_carries_the_grant_expiry() -> None:
    # #60 review: the envelope must carry the host's expiry so per-call
    # enforcement has something to validate against.
    expiry = datetime.now(UTC) + timedelta(minutes=5)
    grant = replace(_grant(actions=frozenset({"read_file"})), expires_at=expiry)
    authority = InMemoryDelegationAuthority([grant])
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

    await caller.handle(
        [{"role": "user", "content": "delegate"}],
        AuthContext(user_id="owner-1", project_id="project-1"),
        session_id="goal-1",
        run_id="run-1",
        invocation_id="inv-1",
        delegation_scope="project-1",
    )

    assert target_strategy.auth.delegation_expires_at == expiry


@pytest.mark.asyncio
async def test_pre_call_rejects_delegated_call_once_expired() -> None:
    # #60 review: expiry is re-checked on every tool call, not only when the
    # delegation begins; a lapsed grant no longer authorizes anything.
    sentinel = Sentinel(warden=Warden(), permission_table={}, allow_on_miss=True)
    expired = AuthContext(
        user_id="owner-1",
        roles=frozenset({"user"}),
        delegated_actions=frozenset({"read_file"}),
        delegation_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    verdict = await sentinel.pre_call("read_file", {}, expired, schema={})

    assert verdict.allowed is False
    assert any(v.rule == "delegation_expired" for v in verdict.violations)

    live = replace(expired, delegation_expires_at=datetime.now(UTC) + timedelta(minutes=5))
    verdict = await sentinel.pre_call("read_file", {}, live, schema={})

    assert verdict.allowed is True


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


@pytest.mark.asyncio
async def test_agent_refuses_delegation_without_an_owning_principal() -> None:
    # No owning principal means the host cannot bind a grant; delegation must
    # fail closed rather than run the child with the caller's envelope.
    authority = InMemoryDelegationAuthority([_grant(actions=frozenset({"read_file"}))])
    sentinel = Sentinel(warden=Warden(), permission_table={}, delegation_authority=authority)
    target_strategy = _Result(ReasoningResult(response="writer ran"))
    target = Agent(
        identity=AgentIdentity(name="writer", tools=("read_file",)),
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
        AuthContext(user_id="", project_id="project-1"),
        session_id="goal-1",
        run_id="run-1",
        invocation_id="inv-1",
        delegation_scope="project-1",
    )

    assert "no owning principal" in response.content
    assert target_strategy.calls == 0


@pytest.mark.asyncio
async def test_agent_refuses_when_the_authorization_envelope_cannot_be_carried() -> None:
    # An auth object that is not an AuthContext has no `delegated_actions`
    # slot, so the host-authorized subset cannot travel to the child; the
    # delegation is refused rather than widened.
    from types import SimpleNamespace

    authority = InMemoryDelegationAuthority([_grant(actions=frozenset({"read_file"}))])
    sentinel = Sentinel(warden=Warden(), permission_table={}, delegation_authority=authority)
    target_strategy = _Result(ReasoningResult(response="writer ran"))
    target = Agent(
        identity=AgentIdentity(name="writer", tools=("read_file",)),
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
        SimpleNamespace(user_id="owner-1", roles=frozenset(), project_id="project-1"),
        session_id="goal-1",
        run_id="run-1",
        invocation_id="inv-1",
        delegation_scope="project-1",
    )

    assert "authorization envelope cannot be carried" in response.content
    assert target_strategy.calls == 0


def test_first_set_returns_empty_when_every_value_is_blank() -> None:
    # The fallback chain must terminate at "" when no value is present; the
    # host then sees an empty identity fragment and binds nothing.
    assert Agent._first_set("", "", None) == ""
