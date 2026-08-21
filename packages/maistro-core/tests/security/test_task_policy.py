"""Coverage for maistro.security.task_policy.InMemoryTaskAcceptancePolicy (was 0%)."""

from __future__ import annotations

import math

from maistro.security.task_policy import InMemoryTaskAcceptancePolicy


def test_task_creation_allowed_by_default() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    assert policy.check_task_creation("u1", "agent-a") is True


def test_deny_agent_blocks_only_that_user_agent_pair() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    policy.deny_agent("u1", "agent-a")

    assert policy.check_task_creation("u1", "agent-a") is False
    assert policy.check_task_creation("u1", "agent-b") is True
    assert policy.check_task_creation("u2", "agent-a") is True


def test_check_budget_rejects_unknown_tier() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    assert policy.check_budget("u1", "P99") is False


def test_check_budget_passes_with_no_budgets_specified() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    assert policy.check_budget("u1", "P2") is True


def test_check_budget_cost_within_limit_passes() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    assert policy.check_budget("u1", "P0", cost_budget=10.0) is True


def test_check_budget_cost_over_limit_fails() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    assert policy.check_budget("u1", "P0", cost_budget=10.01) is False


def test_check_budget_wall_clock_within_limit_passes() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    assert policy.check_budget("u1", "P1", wall_clock_seconds=600) is True


def test_check_budget_wall_clock_over_limit_fails() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    assert policy.check_budget("u1", "P1", wall_clock_seconds=600.01) is False


def test_check_budget_token_within_calculated_limit_passes() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    # P0: base 200_000 / log2(0 + 2) == 200_000 / 1 == 200_000
    expected_max = 200_000 / math.log2(0 + 2)
    assert policy.check_budget("u1", "P0", token_budget=expected_max) is True


def test_check_budget_token_over_calculated_limit_fails() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    expected_max = 200_000 / math.log2(0 + 2)
    assert policy.check_budget("u1", "P0", token_budget=expected_max + 1) is False


def test_higher_priority_tier_has_smaller_log_divisor_more_tokens_relatively() -> None:
    # P5 priority=5 -> divisor log2(7); P0 priority=0 -> divisor log2(2)=1.
    policy = InMemoryTaskAcceptancePolicy()
    p0_max = 200_000 / math.log2(0 + 2)
    p5_max = 25_000 / math.log2(5 + 2)
    assert policy.check_budget("u1", "P0", token_budget=p0_max) is True
    assert policy.check_budget("u1", "P5", token_budget=p5_max) is True
    assert policy.check_budget("u1", "P5", token_budget=p5_max + 1) is False


def test_set_budget_limit_overrides_max_cost() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    policy.set_budget_limit("P0", max_cost=1.0)
    assert policy.check_budget("u1", "P0", cost_budget=1.0) is True
    assert policy.check_budget("u1", "P0", cost_budget=1.01) is False


def test_set_budget_limit_overrides_max_seconds() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    policy.set_budget_limit("P0", max_seconds=10)
    assert policy.check_budget("u1", "P0", wall_clock_seconds=10) is True
    assert policy.check_budget("u1", "P0", wall_clock_seconds=11) is False


def test_set_budget_limit_overrides_max_tokens() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    policy.set_budget_limit("P0", max_tokens=1_000)
    expected_max = 1_000 / math.log2(0 + 2)
    assert policy.check_budget("u1", "P0", token_budget=expected_max) is True
    assert policy.check_budget("u1", "P0", token_budget=expected_max + 1) is False


def test_set_budget_limit_partial_update_leaves_other_fields_untouched() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    policy.set_budget_limit("P0", max_cost=2.0)
    # max_seconds for P0 should remain the original 300.
    assert policy.check_budget("u1", "P0", wall_clock_seconds=300) is True
    assert policy.check_budget("u1", "P0", wall_clock_seconds=301) is False


def test_check_budget_multiple_dimensions_fail_independently() -> None:
    policy = InMemoryTaskAcceptancePolicy()
    # cost ok, time over limit -> overall False
    assert (
        policy.check_budget(
            "u1",
            "P3",
            cost_budget=5.0,
            wall_clock_seconds=99999,
        )
        is False
    )
