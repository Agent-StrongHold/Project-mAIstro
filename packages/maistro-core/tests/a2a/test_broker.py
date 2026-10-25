"""Tests for the ADR-058 A2A broker — budgets, allow-lists, trust tiers (SPEC-182)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.a2a import (
    A2ABroker,
    A2ATask,
    DelegationBudget,
    DelegationRefused,
    LocalTransport,
)
from maistro.agents.catalog import AgentCard, AgentCatalog


def _budget(**overrides: object) -> DelegationBudget:
    defaults: dict[str, object] = {
        "deadline": datetime.now(UTC) + timedelta(minutes=5),
        "token_budget": 10_000,
        "trace_id": "trace-1",
        "max_depth": 3,
    }
    defaults.update(overrides)
    return DelegationBudget(**defaults)  # type: ignore[arg-type]


def _catalog() -> AgentCatalog:
    catalog = AgentCatalog()
    catalog.register(
        AgentCard(
            id="planner",
            name="planner",
            trust_tier="t2",
            delegation_mode="allow_list",
            sub_agents=("coder",),
        )
    )
    catalog.register(AgentCard(id="coder", name="coder", trust_tier="t2"))
    catalog.register(AgentCard(id="reviewer", name="reviewer", trust_tier="t2"))
    catalog.register(AgentCard(id="admin", name="admin", trust_tier="t0"))
    catalog.register(
        AgentCard(
            id="open-agent",
            name="open-agent",
            trust_tier="t2",
            delegation_mode="allow_all",
        )
    )
    catalog.register(
        AgentCard(
            id="locked-agent",
            name="locked-agent",
            trust_tier="t2",
            delegation_mode="none",
        )
    )
    return catalog


async def _echo_invoker(task: A2ATask, budget: DelegationBudget) -> str:
    return f"handled:{task.to_agent}:{task.task}"


def _broker() -> A2ABroker:
    return A2ABroker(resolver=_catalog(), local=LocalTransport(_echo_invoker))


@pytest.mark.asyncio
async def test_local_delegate_returns_sub_agent_response() -> None:
    result = await _broker().delegate(
        from_agent="planner", to="coder", task="write tests", budget=_budget()
    )
    assert result.status == "completed"
    assert result.result == "handled:coder:write tests"
    assert result.error is None


@pytest.mark.asyncio
async def test_non_allow_listed_target_refused() -> None:
    with pytest.raises(DelegationRefused, match="may not delegate to 'reviewer'"):
        await _broker().delegate(from_agent="planner", to="reviewer", task="x", budget=_budget())


@pytest.mark.asyncio
async def test_delegation_mode_none_refused() -> None:
    with pytest.raises(DelegationRefused, match="delegation_mode=none"):
        await _broker().delegate(from_agent="locked-agent", to="coder", task="x", budget=_budget())


@pytest.mark.asyncio
async def test_allow_all_mode_permits_any_same_tier_target() -> None:
    result = await _broker().delegate(
        from_agent="open-agent", to="reviewer", task="x", budget=_budget()
    )
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_depth_exhausted_refused() -> None:
    with pytest.raises(DelegationRefused, match="depth exhausted"):
        await _broker().delegate(
            from_agent="planner", to="coder", task="x", budget=_budget(max_depth=0)
        )


@pytest.mark.asyncio
async def test_deadline_passed_refused() -> None:
    past = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(DelegationRefused, match="deadline passed"):
        await _broker().delegate(
            from_agent="planner", to="coder", task="x", budget=_budget(deadline=past)
        )


@pytest.mark.asyncio
async def test_cycle_refused() -> None:
    with pytest.raises(DelegationRefused, match="circular delegation"):
        await _broker().delegate(
            from_agent="planner",
            to="coder",
            task="x",
            budget=_budget(chain=("orchestrator", "coder")),
        )


@pytest.mark.asyncio
async def test_token_budget_exhausted_refused() -> None:
    with pytest.raises(DelegationRefused, match="token budget exhausted"):
        await _broker().delegate(
            from_agent="planner", to="coder", task="x", budget=_budget(token_budget=0)
        )


@pytest.mark.asyncio
async def test_trust_tier_escalation_refused() -> None:
    with pytest.raises(DelegationRefused, match="trust-tier escalation"):
        await _broker().delegate(from_agent="open-agent", to="admin", task="x", budget=_budget())


@pytest.mark.asyncio
async def test_explicit_allow_list_overrides_trust_tier() -> None:
    catalog = _catalog()
    catalog.register(
        AgentCard(
            id="ops",
            name="ops",
            trust_tier="t2",
            delegation_mode="allow_list",
            sub_agents=("admin",),
        )
    )
    broker = A2ABroker(resolver=catalog, local=LocalTransport(_echo_invoker))
    result = await broker.delegate(from_agent="ops", to="admin", task="x", budget=_budget())
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_unknown_caller_and_target_refused() -> None:
    with pytest.raises(DelegationRefused, match="unknown calling agent"):
        await _broker().delegate(from_agent="ghost", to="coder", task="x", budget=_budget())
    with pytest.raises(DelegationRefused, match="unknown delegation target"):
        await _broker().delegate(from_agent="planner", to="ghost", task="x", budget=_budget())


@pytest.mark.asyncio
async def test_sub_agent_failure_returns_failed_result() -> None:
    async def _boom(task: A2ATask, budget: DelegationBudget) -> str:
        raise RuntimeError("kaput")

    broker = A2ABroker(resolver=_catalog(), local=LocalTransport(_boom))
    result = await broker.delegate(from_agent="planner", to="coder", task="x", budget=_budget())
    assert result.status == "failed"
    assert result.error == "kaput"


def test_budget_spend_decrements_depth_and_appends_chain() -> None:
    budget = _budget(max_depth=2, chain=("a",))
    hop = budget.spend("b")
    assert hop.max_depth == 1
    assert hop.chain == ("a", "b")
    assert hop.trace_id == budget.trace_id
