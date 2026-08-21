"""Tests for the agent-facing delegability evaluator."""

from __future__ import annotations

from maistro.security.delegability import (
    DelegabilityContext,
    ProposedAction,
    evaluate_delegability,
)
from maistro.security.sentinel.authz_types import Principal, Tier
from maistro.security.sentinel.policy import Sentinel
from maistro.security.warden.detector import Warden


def _human(
    roles: tuple[str, ...] = ("user",),
    scopes: tuple[str, ...] = ("user:u1",),
) -> Principal:
    return Principal(id="u1", kind="human", roles=roles, scopes=scopes)


def _agent() -> Principal:
    return Principal(id="agent-1", kind="agent", owner="u1", scopes=("agent:agent-1",))


def _sentinel(
    *,
    permission_table: dict[str, frozenset[str]] | None = None,
    tier_policy: dict[tuple[str, str], Tier] | None = None,
) -> Sentinel:
    return Sentinel(
        warden=Warden(),
        permission_table=permission_table or {},
        tier_policy=tier_policy,
    )


async def test_open_action_is_delegable() -> None:
    decision = await evaluate_delegability(
        ProposedAction("read_file", reversibility="internal"),
        _human(),
        _sentinel(),
    )

    assert decision.status == "delegable"
    assert decision.can_execute is True
    assert decision.unlock_requirements == ()


async def test_irreversible_human_action_is_partially_delegable_with_safe_subactions() -> None:
    decision = await evaluate_delegability(
        ProposedAction(
            "delete_directory",
            reversibility="irreversible",
            safe_subactions=("show_diff", "prepare_backup_plan"),
        ),
        _human(),
        _sentinel(),
    )

    assert decision.status == "partially_delegable"
    assert "principal must complete self-elevation" in decision.unlock_requirements
    assert "show_diff" in decision.safe_subactions
    assert "action is irreversible" in decision.reasons


async def test_irreversible_agent_action_requests_owner_scoped_2fa() -> None:
    decision = await evaluate_delegability(
        ProposedAction(
            "git_push",
            reversibility="irreversible",
            safe_subactions=("git_status", "git_diff", "run_tests"),
            missing_policy=("confirm remote and branch publication authority",),
        ),
        _agent(),
        _sentinel(),
    )

    assert decision.status == "partially_delegable"
    assert "owning human must approve this scoped action" in decision.unlock_requirements
    assert "confirm remote and branch publication authority" in decision.unlock_requirements
    assert decision.safe_subactions == ("git_status", "git_diff", "run_tests")


async def test_blocked_policy_returns_blocked_even_with_safe_subactions() -> None:
    decision = await evaluate_delegability(
        ProposedAction(
            "forbidden",
            reversibility="irreversible",
            safe_subactions=("summarize_request",),
        ),
        _human(),
        _sentinel(tier_policy={("forbidden", "user:u1"): Tier.BLOCKED}),
    )

    assert decision.status == "blocked"
    assert decision.can_execute is False
    assert "action is blocked by policy" in decision.reasons


async def test_unauthorized_action_is_not_yet_delegable() -> None:
    decision = await evaluate_delegability(
        ProposedAction("deploy", reversibility="irreversible"),
        _human(roles=("user",)),
        _sentinel(permission_table={"deploy": frozenset({"admin"})}),
    )

    assert decision.status == "not_yet_delegable"
    assert any("lacks capability" in item for item in decision.unlock_requirements)


async def test_over_budget_exposes_budget_unlock_requirement() -> None:
    decision = await evaluate_delegability(
        ProposedAction("read_file", reversibility="internal"),
        _human(),
        _sentinel(),
        context=DelegabilityContext(within_budget=False),
    )

    assert decision.status == "not_yet_delegable"
    assert "grant or raise the budget for this action" in decision.unlock_requirements
    assert "budget has not been delegated for this action" in decision.reasons
