"""I7: Auth Scopes — Scope Expansion and Service Identity — Hypothesis property-based tests."""

from __future__ import annotations

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.auth._types import (
    CATEGORY_SCOPES,
    Scope,
    ScopeCategory,
    ServiceIdentity,
    expand_scopes,
)


_VALID_SCOPES = [s.value for s in Scope]
_VALID_CATEGORIES = [c.value for c in ScopeCategory]


class ScopeExpansionMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.identity = ServiceIdentity(name="test-svc", scopes=frozenset())
        self.expanded_count = 0

    @rule(
        spec=st.one_of(
            st.sampled_from(_VALID_SCOPES),
            st.just("*:*"),
            st.builds(lambda c: f"{c}:*", st.sampled_from(_VALID_CATEGORIES)),
            st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))),
        )
    )
    def expand_and_set(self, spec):
        scopes = expand_scopes([spec])
        self.identity = ServiceIdentity(name="test-svc", scopes=scopes)
        self.expanded_count += 1

    @invariant()
    def identity_scopes_are_frozen(self):
        assert isinstance(self.identity.scopes, frozenset)
        for s in self.identity.scopes:
            assert isinstance(s, Scope)

    @invariant()
    def has_scope_consistent(self):
        for s in self.identity.scopes:
            assert self.identity.has_scope(s)


TestScopeExpansionMachine = ScopeExpansionMachine.TestCase


@given(cat=st.sampled_from(list(ScopeCategory)))
@settings(max_examples=20)
def test_category_wildcard_expands_to_all(cat):
    result = expand_scopes([f"{cat.value}:*"])
    expected = CATEGORY_SCOPES[cat]
    assert result == expected


@given(scope=st.sampled_from(list(Scope)))
@settings(max_examples=50)
def test_individual_scope_expands_to_itself(scope):
    result = expand_scopes([scope.value])
    assert result == frozenset({scope})


def test_superuser_expands_to_all():
    result = expand_scopes(["*:*"])
    all_scopes = set()
    for scopes in CATEGORY_SCOPES.values():
        all_scopes |= scopes
    assert result == frozenset(all_scopes)


@given(
    invalid=st.text(min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "N"))).filter(
        lambda x: x not in _VALID_SCOPES and x != "*:*" and not any(x == f"{c.value}:*" for c in ScopeCategory)
    )
)
@settings(max_examples=50)
def test_invalid_scopes_ignored(invalid):
    result = expand_scopes([invalid])
    assert result == frozenset()


@given(
    scope=st.sampled_from(list(Scope)),
)
@settings(max_examples=50)
def test_has_scope_true_for_member(scope):
    identity = ServiceIdentity(name="svc", scopes=frozenset({scope}))
    assert identity.has_scope(scope)


@given(
    scope_a=st.sampled_from(list(Scope)),
    scope_b=st.sampled_from(list(Scope)),
)
@settings(max_examples=50)
def test_has_scope_false_for_nonmember(scope_a, scope_b):
    assume(scope_a != scope_b)
    identity = ServiceIdentity(name="svc", scopes=frozenset({scope_a}))
    assert not identity.has_scope(scope_b)


@given(
    scopes=st.sets(st.sampled_from(list(Scope)), min_size=1, max_size=5),
)
@settings(max_examples=30)
def test_has_any_scope_intersection(scopes):
    identity = ServiceIdentity(name="svc", scopes=frozenset(scopes))
    some = list(scopes)[:2]
    assert identity.has_any_scope(*some)


@given(
    member=st.sampled_from(list(Scope)),
    nonmember=st.sampled_from(list(Scope)),
)
@settings(max_examples=50)
def test_has_any_scope_no_intersection(member, nonmember):
    assume(member != nonmember)
    identity = ServiceIdentity(name="svc", scopes=frozenset({member}))
    assert not identity.has_any_scope(nonmember)


def test_frozen_identity_immutable():
    identity = ServiceIdentity(name="svc", scopes=frozenset({Scope.CHAT_COMPLETIONS}))
    with pytest.raises((AttributeError, TypeError)):
        identity.name = "other"


@given(
    specs=st.lists(
        st.sampled_from(_VALID_SCOPES),
        min_size=1,
        max_size=10,
    )
)
@settings(max_examples=30)
def test_multiple_valid_scopes(specs):
    result = expand_scopes(specs)
    for spec in specs:
        assert Scope(spec) in result


@given(
    cat=st.sampled_from(list(ScopeCategory)),
    extra=st.sampled_from(list(Scope)),
)
@settings(max_examples=30)
def test_category_plus_individual(cat, extra):
    result = expand_scopes([f"{cat.value}:*", extra.value])
    expected = CATEGORY_SCOPES[cat] | frozenset({extra})
    assert result == expected


@given(
    scope=st.sampled_from(list(Scope)),
)
@settings(max_examples=20)
def test_empty_input_returns_empty(scope):
    result = expand_scopes([])
    assert result == frozenset()


@given(
    cat=st.sampled_from(list(ScopeCategory)),
)
@settings(max_examples=20)
def test_category_scopes_nonempty(cat):
    assert len(CATEGORY_SCOPES[cat]) > 0


@given(
    scope=st.sampled_from(list(Scope)),
)
@settings(max_examples=50)
def test_scope_in_exactly_one_category(scope):
    categories_containing = [cat for cat, scopes in CATEGORY_SCOPES.items() if scope in scopes]
    assert len(categories_containing) == 1
