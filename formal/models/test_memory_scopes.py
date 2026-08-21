"""I30: Memory Scope Isolation — Hypothesis property-based tests."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from maistro.memory.scopes import build_scope_filter, matches_scope
from maistro.memory.types import EpisodicMemory, MemoryScope


def _make_memory(scope, agent_id=None, user_id=None, team_id=None, org_id=None):
    return EpisodicMemory(
        scope=scope,
        agent_id=agent_id,
        user_id=user_id,
        team_id=team_id,
        org_id=org_id,
    )


class ScopeIsolationMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.global_mem = _make_memory(MemoryScope.GLOBAL)
        self.org_mem = _make_memory(MemoryScope.ORGANIZATION, org_id="org1")
        self.team_mem = _make_memory(MemoryScope.TEAM, team_id="team1", org_id="org1")
        self.user_mem = _make_memory(MemoryScope.USER, user_id="user1")
        self.agent_mem = _make_memory(MemoryScope.AGENT, agent_id="agent1")

    @rule(
        agent_id=st.none(),
        user_id=st.none(),
        team_id=st.none(),
        org_id=st.none(),
    )
    def check_global_visible_to_all(self, agent_id, user_id, team_id, org_id):
        filters = build_scope_filter(agent_id, user_id, team_id, org_id)
        assert matches_scope(self.global_mem, filters)

    @rule(
        org_id=st.sampled_from(["org1", "org2"]),
    )
    def check_org_isolation(self, org_id):
        filters = build_scope_filter(org_id=org_id)
        if org_id == "org1":
            assert matches_scope(self.org_mem, filters)
        else:
            assert not matches_scope(self.org_mem, filters)

    @rule(
        org_id=st.sampled_from(["org1", "org2"]),
    )
    def check_team_requires_same_org(self, org_id):
        filters = build_scope_filter(team_id="team1", org_id=org_id)
        if org_id == "org1":
            assert matches_scope(self.team_mem, filters)
        else:
            assert not matches_scope(self.team_mem, filters)

    @rule(
        user_id=st.sampled_from(["user1", "user2"]),
    )
    def check_user_isolation(self, user_id):
        filters = build_scope_filter(user_id=user_id)
        if user_id == "user1":
            assert matches_scope(self.user_mem, filters)
        else:
            assert not matches_scope(self.user_mem, filters)

    @rule(
        agent_id=st.sampled_from(["agent1", "agent2"]),
    )
    def check_agent_isolation(self, agent_id):
        filters = build_scope_filter(agent_id=agent_id)
        if agent_id == "agent1":
            assert matches_scope(self.agent_mem, filters)
        else:
            assert not matches_scope(self.agent_mem, filters)

    @invariant()
    def global_always_visible(self):
        filters = build_scope_filter()
        assert matches_scope(self.global_mem, filters)

    @invariant()
    def global_with_org_restricted(self):
        restricted_mem = _make_memory(MemoryScope.GLOBAL, org_id="org_secret")
        same_org_filters = build_scope_filter(org_id="org_secret")
        assert matches_scope(restricted_mem, same_org_filters)
        diff_org_filters = build_scope_filter(org_id="org_other")
        assert not matches_scope(restricted_mem, diff_org_filters)


TestScopeIsolationMachine = ScopeIsolationMachine.TestCase


def test_global_visible_to_everyone():
    mem = _make_memory(MemoryScope.GLOBAL)
    filters = build_scope_filter()
    assert matches_scope(mem, filters)


def test_org_memory_visible_to_same_org():
    mem = _make_memory(MemoryScope.ORGANIZATION, org_id="org1")
    filters = build_scope_filter(org_id="org1")
    assert matches_scope(mem, filters)


def test_org_memory_hidden_from_other_org():
    mem = _make_memory(MemoryScope.ORGANIZATION, org_id="org1")
    filters = build_scope_filter(org_id="org2")
    assert not matches_scope(mem, filters)


def test_team_memory_requires_matching_team_and_org():
    mem = _make_memory(MemoryScope.TEAM, team_id="t1", org_id="org1")
    filters_same = build_scope_filter(team_id="t1", org_id="org1")
    assert matches_scope(mem, filters_same)
    filters_diff_org = build_scope_filter(team_id="t1", org_id="org2")
    assert not matches_scope(mem, filters_diff_org)


def test_user_memory_visible_to_same_user():
    mem = _make_memory(MemoryScope.USER, user_id="u1")
    filters = build_scope_filter(user_id="u1")
    assert matches_scope(mem, filters)


def test_user_memory_hidden_from_other_user():
    mem = _make_memory(MemoryScope.USER, user_id="u1")
    filters = build_scope_filter(user_id="u2")
    assert not matches_scope(mem, filters)


def test_agent_memory_visible_to_same_agent():
    mem = _make_memory(MemoryScope.AGENT, agent_id="a1")
    filters = build_scope_filter(agent_id="a1")
    assert matches_scope(mem, filters)


def test_agent_memory_hidden_from_other_agent():
    mem = _make_memory(MemoryScope.AGENT, agent_id="a1")
    filters = build_scope_filter(agent_id="a2")
    assert not matches_scope(mem, filters)


def test_global_with_org_visible_to_same_org():
    mem = _make_memory(MemoryScope.GLOBAL, org_id="org1")
    filters = build_scope_filter(org_id="org1")
    assert matches_scope(mem, filters)


def test_global_with_org_hidden_from_different_org():
    mem = _make_memory(MemoryScope.GLOBAL, org_id="org1")
    filters = build_scope_filter(org_id="org2")
    assert not matches_scope(mem, filters)


def test_build_scope_filter_always_includes_global():
    filters = build_scope_filter()
    scopes = [s for s, _ in filters]
    assert MemoryScope.GLOBAL in scopes


@given(
    scope=st.sampled_from([s for s in MemoryScope if s != MemoryScope.SESSION]),
    agent_id=st.text(min_size=1, max_size=10),
    user_id=st.text(min_size=1, max_size=10),
    team_id=st.text(min_size=1, max_size=10),
    org_id=st.text(min_size=1, max_size=10),
)
@settings(max_examples=30)
def test_scope_filter_isolation_property(scope, agent_id, user_id, team_id, org_id):
    mem = _make_memory(scope, agent_id=agent_id, user_id=user_id, team_id=team_id, org_id=org_id)
    filters = build_scope_filter(
        agent_id=agent_id if scope == MemoryScope.AGENT else None,
        user_id=user_id if scope == MemoryScope.USER else None,
        team_id=team_id if scope == MemoryScope.TEAM else None,
        org_id=org_id if scope in (MemoryScope.ORGANIZATION, MemoryScope.TEAM) else None,
    )
    assert matches_scope(mem, filters)
