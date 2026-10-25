"""I1: Strike Escalation Ladder — Hypothesis property-based tests."""

from __future__ import annotations

import asyncio

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.security.strikes import (
    DISABLED,
    ELEVATED,
    LOCKED,
    NORMAL,
    InMemoryStrikeTracker,
)


def _run(coro):
    return asyncio.run(coro)


class StrikeEscalationMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.tracker = InMemoryStrikeTracker()
        self.user = "user-1"

    @rule()
    def record_violation(self):
        rec = _run(
            self.tracker.record_violation(
                user_id=self.user,
                flags=("test_flag",),
                boundary="user_input",
            )
        )
        assert rec.strike_count >= 1

    @rule(count=st.integers(min_value=1, max_value=10))
    def remove_strikes(self, count):
        rec = _run(self.tracker.remove_strikes(self.user, count=count))
        if rec is not None:
            assert rec.strike_count >= 0

    @rule()
    def unlock(self):
        _run(self.tracker.unlock(self.user))

    @rule()
    def enable(self):
        _run(self.tracker.enable(self.user))

    @invariant()
    def strike_count_never_negative(self):
        rec = _run(self.tracker.get(self.user))
        if rec is not None:
            assert rec.strike_count >= 0

    @invariant()
    def enable_clears_disabled_and_lock(self):
        pass

    @invariant()
    def zero_strikes_is_clean(self):
        rec = _run(self.tracker.get(self.user))
        if rec is None:
            return
        if rec.strike_count == 0:
            assert rec.scrutiny_level == NORMAL
            assert not rec.disabled
            assert rec.locked_until is None

    @invariant()
    def fresh_violation_escalation(self):
        pass


TestStrikeEscalationMachine = StrikeEscalationMachine.TestCase


@given(st.text(min_size=1, max_size=20))
@settings(max_examples=50)
def test_strike_1_elevated(user_id):
    tracker = InMemoryStrikeTracker()

    rec = _run(
        tracker.record_violation(
            user_id=user_id,
            flags=("flag",),
            boundary="user_input",
        )
    )

    assert rec.strike_count == 1
    assert rec.scrutiny_level == ELEVATED
    assert not rec.disabled
    assert rec.locked_until is None


@given(st.text(min_size=1, max_size=20))
@settings(max_examples=50)
def test_strike_2_locked(user_id):
    tracker = InMemoryStrikeTracker()

    _run(
        tracker.record_violation(
            user_id=user_id,
            flags=("f1",),
            boundary="user_input",
        )
    )
    rec = _run(
        tracker.record_violation(
            user_id=user_id,
            flags=("f2",),
            boundary="user_input",
        )
    )

    assert rec.strike_count == 2
    assert rec.scrutiny_level == LOCKED
    assert rec.locked_until is not None
    assert not rec.disabled


@given(st.text(min_size=1, max_size=20))
@settings(max_examples=50)
def test_strike_3_disabled(user_id):
    tracker = InMemoryStrikeTracker()

    for i in range(3):
        rec = _run(
            tracker.record_violation(
                user_id=user_id,
                flags=(f"f{i}",),
                boundary="user_input",
            )
        )

    assert rec.strike_count == 3
    assert rec.disabled
    assert rec.scrutiny_level == DISABLED


@given(st.text(min_size=1, max_size=20))
@settings(max_examples=50)
def test_unlock_after_strike_2_clears_lock(user_id):
    tracker = InMemoryStrikeTracker()

    _run(tracker.record_violation(user_id=user_id, flags=("a",), boundary="u"))
    _run(tracker.record_violation(user_id=user_id, flags=("b",), boundary="u"))

    rec = _run(tracker.unlock(user_id))
    assert rec is not None
    assert rec.locked_until is None


@given(st.text(min_size=1, max_size=20))
@settings(max_examples=50)
def test_unlock_after_strike_3_keeps_disabled(user_id):
    tracker = InMemoryStrikeTracker()

    for i in range(3):
        _run(tracker.record_violation(user_id=user_id, flags=(f"x{i}",), boundary="u"))

    rec = _run(tracker.unlock(user_id))
    assert rec is not None
    assert rec.disabled
    assert rec.scrutiny_level == DISABLED


@given(st.text(min_size=1, max_size=20))
@settings(max_examples=50)
def test_enable_after_strike_3_resets_disabled(user_id):
    tracker = InMemoryStrikeTracker()

    for i in range(3):
        _run(tracker.record_violation(user_id=user_id, flags=(f"y{i}",), boundary="u"))

    rec = _run(tracker.enable(user_id))
    assert rec is not None
    assert not rec.disabled
    assert rec.locked_until is None


@given(st.text(min_size=1, max_size=20))
@settings(max_examples=50)
def test_remove_all_strikes_resets_to_normal(user_id):
    tracker = InMemoryStrikeTracker()

    for i in range(5):
        _run(tracker.record_violation(user_id=user_id, flags=(f"z{i}",), boundary="u"))

    rec = _run(tracker.remove_strikes(user_id, count=5))
    assert rec is not None
    assert rec.strike_count == 0
    assert rec.scrutiny_level == NORMAL
    assert not rec.disabled
    assert rec.locked_until is None


@given(
    user_id=st.text(min_size=1, max_size=20),
    n=st.integers(min_value=3, max_value=20),
)
@settings(max_examples=50)
def test_many_strikes_stay_disabled(user_id, n):
    tracker = InMemoryStrikeTracker()

    for i in range(n):
        rec = _run(
            tracker.record_violation(
                user_id=user_id,
                flags=(f"w{i}",),
                boundary="u",
            )
        )

    assert rec.disabled
    assert rec.scrutiny_level == DISABLED
    assert rec.strike_count == n


@given(st.text(min_size=1, max_size=20))
@settings(max_examples=50)
def test_violations_appended(user_id):
    tracker = InMemoryStrikeTracker()

    for i in range(3):
        _run(
            tracker.record_violation(
                user_id=user_id,
                flags=(f"flag-{i}",),
                boundary="user_input",
                detail=f"detail-{i}",
            )
        )

    rec = _run(tracker.get(user_id))
    assert len(rec.violations) == 3


@given(st.text(min_size=1, max_size=20))
@settings(max_examples=50)
def test_remove_strikes_recalculates_level(user_id):
    tracker = InMemoryStrikeTracker()

    for i in range(3):
        _run(tracker.record_violation(user_id=user_id, flags=(f"r{i}",), boundary="u"))

    rec = _run(tracker.remove_strikes(user_id, count=2))
    assert rec.strike_count == 1
    assert rec.scrutiny_level == ELEVATED
    assert not rec.disabled
    assert rec.locked_until is None


@given(
    user_a=st.text(min_size=1, max_size=20),
    user_b=st.text(min_size=2, max_size=20),
)
@settings(max_examples=30)
def test_independent_users(user_a, user_b):
    assume(user_a != user_b)
    tracker = InMemoryStrikeTracker()

    _run(tracker.record_violation(user_id=user_a, flags=("a",), boundary="u"))
    _run(tracker.record_violation(user_id=user_b, flags=("b",), boundary="u"))
    _run(tracker.record_violation(user_id=user_b, flags=("c",), boundary="u"))

    rec_a = _run(tracker.get(user_a))
    rec_b = _run(tracker.get(user_b))

    assert rec_a.strike_count == 1
    assert rec_b.strike_count == 2
    assert rec_a.scrutiny_level == ELEVATED
    assert rec_b.scrutiny_level == LOCKED
