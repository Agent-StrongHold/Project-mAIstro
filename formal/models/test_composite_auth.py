"""I26: Composite Provider Chain — Hypothesis property-based tests."""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from maistro.security._types import AuthContext
from maistro.security.auth_composite import AuthError, CompositeAuthProvider


class MockProvider:
    def __init__(self, should_fail=False, auth_context=None):
        self._should_fail = should_fail
        self._auth_context = auth_context

    async def authenticate(self, authorization, headers=None):
        if self._should_fail:
            raise ValueError("mock fail")
        return self._auth_context or AuthContext(user_id="test")


class CompositeMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.ctx_a = AuthContext(user_id="provider_a", auth_method="a")
        self.ctx_b = AuthContext(user_id="provider_b", auth_method="b")
        self.provider_a = MockProvider(auth_context=self.ctx_a)
        self.provider_b = MockProvider(auth_context=self.ctx_b)

    @rule(
        a_fails=st.booleans(),
        b_fails=st.booleans(),
    )
    def try_composite(self, a_fails, b_fails):
        pa = MockProvider(should_fail=a_fails, auth_context=self.ctx_a)
        pb = MockProvider(should_fail=b_fails, auth_context=self.ctx_b)
        composite = CompositeAuthProvider([pa, pb])
        if a_fails and b_fails:
            # Fix #13: an exhausted chain raises AuthError, not ValueError
            try:
                asyncio.run(composite.authenticate("Bearer t"))
                raise AssertionError("Expected AuthError")
            except AuthError:
                pass
        elif a_fails:
            ctx = asyncio.run(composite.authenticate("Bearer t"))
            assert ctx.user_id == "provider_b"
        else:
            ctx = asyncio.run(composite.authenticate("Bearer t"))
            assert ctx.user_id == "provider_a"

    @invariant()
    def empty_provider_list_raises(self):
        composite = CompositeAuthProvider([])
        try:
            asyncio.run(composite.authenticate("Bearer t"))
            raise AssertionError("Expected AuthError")
        except AuthError:
            pass


TestCompositeMachine = CompositeMachine.TestCase


def test_first_provider_succeeds():
    pa = MockProvider(auth_context=AuthContext(user_id="first"))
    pb = MockProvider(auth_context=AuthContext(user_id="second"))
    composite = CompositeAuthProvider([pa, pb])
    ctx = asyncio.run(composite.authenticate("Bearer t"))
    assert ctx.user_id == "first"


def test_first_fails_second_succeeds():
    pa = MockProvider(should_fail=True, auth_context=AuthContext(user_id="first"))
    pb = MockProvider(auth_context=AuthContext(user_id="second"))
    composite = CompositeAuthProvider([pa, pb])
    ctx = asyncio.run(composite.authenticate("Bearer t"))
    assert ctx.user_id == "second"


def test_all_fail_raises():
    pa = MockProvider(should_fail=True)
    pb = MockProvider(should_fail=True)
    composite = CompositeAuthProvider([pa, pb])
    try:
        asyncio.run(composite.authenticate("Bearer t"))
        raise AssertionError("Expected AuthError")
    except AuthError:
        pass


def test_empty_list_raises():
    composite = CompositeAuthProvider([])
    try:
        asyncio.run(composite.authenticate("Bearer t"))
        raise AssertionError("Expected AuthError")
    except AuthError:
        pass


def test_order_matters():
    ctx1 = AuthContext(user_id="alpha")
    ctx2 = AuthContext(user_id="beta")
    p1 = MockProvider(auth_context=ctx1)
    p2 = MockProvider(auth_context=ctx2)
    c1 = CompositeAuthProvider([p1, p2])
    c2 = CompositeAuthProvider([p2, p1])
    r1 = asyncio.run(c1.authenticate("Bearer t"))
    r2 = asyncio.run(c2.authenticate("Bearer t"))
    assert r1.user_id == "alpha"
    assert r2.user_id == "beta"


def test_provider_exceptions_suppressed():
    pa = MockProvider(should_fail=True)
    pb = MockProvider(auth_context=AuthContext(user_id="ok"))
    composite = CompositeAuthProvider([pa, pb])
    ctx = asyncio.run(composite.authenticate("Bearer t"))
    assert ctx.user_id == "ok"


@given(n_failing=st.integers(min_value=0, max_value=5))
@settings(max_examples=20)
def test_chain_with_n_failing_before_success(n_failing):
    providers = [MockProvider(should_fail=True) for _ in range(n_failing)]
    final = MockProvider(auth_context=AuthContext(user_id="final"))
    providers.append(final)
    composite = CompositeAuthProvider(providers)
    ctx = asyncio.run(composite.authenticate("Bearer t"))
    assert ctx.user_id == "final"
