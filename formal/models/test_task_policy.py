"""I9: Task Acceptance Policy + Budget — Hypothesis property-based tests."""

from __future__ import annotations

import math

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.security.task_policy import InMemoryTaskAcceptancePolicy


_VALID_TIERS = ["P0", "P1", "P2", "P3", "P4", "P5"]


class TaskPolicyMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.policy = InMemoryTaskAcceptancePolicy()
        self.denied_agents: set[tuple[str, str]] = set()

    @rule(
        user_id=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L", "N"))),
        agent_name=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L", "N"))),
    )
    def deny_agent(self, user_id, agent_name):
        self.policy.deny_agent(user_id, agent_name)
        self.denied_agents.add((user_id, agent_name))

    @rule(
        user_id=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L", "N"))),
        agent_name=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L", "N"))),
    )
    def check_task_creation(self, user_id, agent_name):
        result = self.policy.check_task_creation(user_id, agent_name)
        if (user_id, agent_name) in self.denied_agents:
            assert not result
        else:
            assert result

    @invariant()
    def denied_agents_always_rejected(self):
        for user_id, agent_name in self.denied_agents:
            assert not self.policy.check_task_creation(user_id, agent_name)


TestTaskPolicyMachine = TaskPolicyMachine.TestCase


@given(
    user_id=st.text(min_size=1, max_size=20),
    agent_name=st.text(min_size=1, max_size=20),
)
@settings(max_examples=50)
def test_denied_agent_rejected(user_id, agent_name):
    policy = InMemoryTaskAcceptancePolicy()
    policy.deny_agent(user_id, agent_name)
    assert not policy.check_task_creation(user_id, agent_name)


@given(
    user_id=st.text(min_size=1, max_size=20),
    agent_name=st.text(min_size=1, max_size=20),
)
@settings(max_examples=50)
def test_nondenied_agent_allowed(user_id, agent_name):
    policy = InMemoryTaskAcceptancePolicy()
    assert policy.check_task_creation(user_id, agent_name)


@given(
    tier=st.text(min_size=1, max_size=5).filter(lambda t: t not in _VALID_TIERS),
    user_id=st.text(min_size=1, max_size=20),
)
@settings(max_examples=30)
def test_unknown_tier_rejected(user_id, tier):
    policy = InMemoryTaskAcceptancePolicy()
    assert not policy.check_budget(user_id, tier)


@given(tier=st.sampled_from(_VALID_TIERS))
@settings(max_examples=10)
def test_known_tier_no_limits_allowed(tier):
    policy = InMemoryTaskAcceptancePolicy()
    assert policy.check_budget("user1", tier)


@given(tier=st.sampled_from(_VALID_TIERS))
@settings(max_examples=10)
def test_token_budget_within_limit_allowed(tier):
    policy = InMemoryTaskAcceptancePolicy()
    base_tokens = policy._base_tokens_per_tier[tier]
    priority = int(tier[1:])
    max_tokens = base_tokens / math.log2(priority + 2)
    assert policy.check_budget("user1", tier, token_budget=max_tokens * 0.5)


@given(tier=st.sampled_from(_VALID_TIERS))
@settings(max_examples=10)
def test_token_budget_exceeds_denied(tier):
    policy = InMemoryTaskAcceptancePolicy()
    base_tokens = policy._base_tokens_per_tier[tier]
    priority = int(tier[1:])
    max_tokens = base_tokens / math.log2(priority + 2)
    assert not policy.check_budget("user1", tier, token_budget=max_tokens + 1)


@given(
    tier=st.sampled_from(_VALID_TIERS),
    cost=st.floats(min_value=0.01, max_value=1000.0),
)
@settings(max_examples=50)
def test_cost_budget_boundary(tier, cost):
    policy = InMemoryTaskAcceptancePolicy()
    max_cost = policy._base_budget[tier]["max_cost"]
    result = policy.check_budget("user1", tier, cost_budget=cost)
    if cost > max_cost:
        assert not result
    else:
        assert result


@given(
    tier=st.sampled_from(_VALID_TIERS),
    seconds=st.floats(min_value=0.0, max_value=100000.0),
)
@settings(max_examples=50)
def test_wall_clock_boundary(tier, seconds):
    policy = InMemoryTaskAcceptancePolicy()
    max_seconds = policy._base_budget[tier]["max_seconds"]
    result = policy.check_budget("user1", tier, wall_clock_seconds=seconds)
    if seconds > max_seconds:
        assert not result
    else:
        assert result


def test_deny_agent_per_user():
    policy = InMemoryTaskAcceptancePolicy()
    policy.deny_agent("alice", "dangerous-agent")

    assert not policy.check_task_creation("alice", "dangerous-agent")
    assert policy.check_task_creation("bob", "dangerous-agent")
    assert policy.check_task_creation("alice", "safe-agent")


@given(
    user_id=st.text(min_size=1, max_size=20),
    agent_a=st.text(min_size=1, max_size=20),
    agent_b=st.text(min_size=1, max_size=20),
)
@settings(max_examples=30)
def test_deny_one_agent_doesnt_affect_other(user_id, agent_a, agent_b):
    assume(agent_a != agent_b)
    policy = InMemoryTaskAcceptancePolicy()
    policy.deny_agent(user_id, agent_a)

    assert not policy.check_task_creation(user_id, agent_a)
    assert policy.check_task_creation(user_id, agent_b)


@given(
    user_a=st.text(min_size=1, max_size=20),
    user_b=st.text(min_size=1, max_size=20),
    agent_name=st.text(min_size=1, max_size=20),
)
@settings(max_examples=30)
def test_deny_per_user_isolation(user_a, user_b, agent_name):
    assume(user_a != user_b)
    policy = InMemoryTaskAcceptancePolicy()
    policy.deny_agent(user_a, agent_name)

    assert not policy.check_task_creation(user_a, agent_name)
    assert policy.check_task_creation(user_b, agent_name)


@given(tier=st.sampled_from(_VALID_TIERS))
@settings(max_examples=10)
def test_none_budgets_pass(tier):
    policy = InMemoryTaskAcceptancePolicy()
    assert policy.check_budget("user1", tier, token_budget=None, cost_budget=None, wall_clock_seconds=None)


@given(tier=st.sampled_from(_VALID_TIERS))
@settings(max_examples=10)
def test_zero_budgets_pass(tier):
    policy = InMemoryTaskAcceptancePolicy()
    assert policy.check_budget("user1", tier, token_budget=0.0, cost_budget=0.0, wall_clock_seconds=0.0)


@given(tier=st.sampled_from(_VALID_TIERS))
@settings(max_examples=10)
def test_set_budget_limit_enforced(tier):
    policy = InMemoryTaskAcceptancePolicy()
    policy.set_budget_limit(tier, max_tokens=100.0, max_cost=1.0, max_seconds=60.0)

    assert not policy.check_budget("user1", tier, token_budget=200.0)
    assert not policy.check_budget("user1", tier, cost_budget=5.0)
    assert not policy.check_budget("user1", tier, wall_clock_seconds=120.0)
    assert policy.check_budget("user1", tier, token_budget=10.0, cost_budget=0.5, wall_clock_seconds=30.0)
