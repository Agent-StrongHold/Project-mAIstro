"""Tests for adaptive reconciliation: policy interval shaping + delta comparison."""

from __future__ import annotations

import pytest

from maistro.quota.rate_profile import LimitUnit
from maistro.quota.reconciliation import (
    AdaptiveReconciliationPolicy,
    ProviderQuotaSnapshot,
    ReconciliationState,
    maybe_reconcile,
    reconcile_ambient,
)
from maistro.quota.usage_log import InMemoryUsageLog


class _FakeVerifier:
    def __init__(self, remaining_sequence: list[float]) -> None:
        self._sequence = remaining_sequence
        self._calls = 0

    async def verify(self, scope_key: str) -> ProviderQuotaSnapshot:
        remaining = self._sequence[self._calls]
        self._calls += 1
        return ProviderQuotaSnapshot(
            scope_key=scope_key, unit=LimitUnit.CREDITS_USD, remaining=remaining, checked_at=0.0
        )

    @property
    def calls(self) -> int:
        return self._calls


# --- AdaptiveReconciliationPolicy ------------------------------------------


def test_policy_rejects_decrease_not_steeper_than_increase() -> None:
    with pytest.raises(ValueError, match="decrease_factor must shrink"):
        AdaptiveReconciliationPolicy(increase_factor=1.25, decrease_factor=0.9)


def test_policy_rejects_increase_factor_at_or_below_one() -> None:
    with pytest.raises(ValueError, match="increase_factor"):
        AdaptiveReconciliationPolicy(increase_factor=1.0)


def test_policy_rejects_decrease_factor_out_of_range() -> None:
    with pytest.raises(ValueError, match="decrease_factor"):
        AdaptiveReconciliationPolicy(decrease_factor=1.0)


def test_policy_rejects_bad_interval_bounds() -> None:
    with pytest.raises(ValueError, match="max_interval_s"):
        AdaptiveReconciliationPolicy(min_interval_s=100.0, max_interval_s=50.0)


def test_policy_starts_at_minimum() -> None:
    policy = AdaptiveReconciliationPolicy(min_interval_s=30.0)
    assert policy.current_interval_s == 30.0


def test_match_grows_interval_multiplicatively() -> None:
    policy = AdaptiveReconciliationPolicy(min_interval_s=30.0, increase_factor=1.25)
    policy.record_match()
    assert policy.current_interval_s == pytest.approx(37.5)


def test_match_never_exceeds_max() -> None:
    policy = AdaptiveReconciliationPolicy(
        min_interval_s=100.0, max_interval_s=120.0, increase_factor=2.0
    )
    policy.record_match()
    assert policy.current_interval_s == 120.0


def test_mismatch_shrinks_by_more_than_match_grew_it() -> None:
    # A low floor and several matches first, so the eventual shrink lands well
    # above min_interval_s -- otherwise the floor clamp masks the multiplicative
    # relationship this test exists to check.
    policy = AdaptiveReconciliationPolicy(
        min_interval_s=1.0, increase_factor=1.25, decrease_factor=0.4
    )
    for _ in range(6):
        policy.record_match()
    before_last_match = policy.current_interval_s / policy.increase_factor
    policy.record_mismatch()
    # The mismatch drops it below where it was even *before* the last match --
    # a match-then-mismatch pair nets a loss of trust, not a wash.
    assert policy.current_interval_s < before_last_match


def test_mismatch_never_drops_below_min() -> None:
    policy = AdaptiveReconciliationPolicy(min_interval_s=30.0, decrease_factor=0.1)
    policy.record_mismatch()
    assert policy.current_interval_s == 30.0


def test_due_respects_current_interval() -> None:
    policy = AdaptiveReconciliationPolicy(min_interval_s=60.0)
    assert policy.due(59.9) is False
    assert policy.due(60.0) is True


# --- maybe_reconcile ---------------------------------------------------------


async def test_not_due_yet_returns_none_without_calling_verifier() -> None:
    policy = AdaptiveReconciliationPolicy(min_interval_s=60.0)
    state = ReconciliationState(policy=policy, last_explicit_check_at=1000.0)
    verifier = _FakeVerifier([100.0])
    log = InMemoryUsageLog()

    outcome = await maybe_reconcile(state, "s1", log, verifier, now=1010.0)

    assert outcome is None
    assert verifier.calls == 0


async def test_first_check_establishes_baseline_without_touching_policy() -> None:
    policy = AdaptiveReconciliationPolicy(min_interval_s=30.0)
    state = ReconciliationState(policy=policy)  # last_checked_at=0.0, last_remaining=None
    verifier = _FakeVerifier([100.0])
    log = InMemoryUsageLog()

    outcome = await maybe_reconcile(state, "s1", log, verifier, now=1000.0)

    assert outcome is not None
    assert outcome.matched is None
    assert state.last_remaining == 100.0
    assert policy.current_interval_s == 30.0  # untouched


async def test_matching_delta_records_match_and_grows_interval() -> None:
    policy = AdaptiveReconciliationPolicy(min_interval_s=30.0, increase_factor=1.25)
    state = ReconciliationState(policy=policy, last_checked_at=0.0, last_remaining=100.0)
    log = InMemoryUsageLog()
    # Local log observed $2 of usage between t=0 and t=30 -> matches provider's $2 drop.
    log.record("s1", cost_usd=2.0, now=15.0)
    verifier = _FakeVerifier([98.0])

    outcome = await maybe_reconcile(state, "s1", log, verifier, now=30.0)

    assert outcome is not None
    assert outcome.matched is True
    assert outcome.provider_delta == pytest.approx(2.0)
    assert outcome.local_delta == pytest.approx(2.0)
    assert policy.current_interval_s == pytest.approx(37.5)
    assert state.last_remaining == 98.0


async def test_mismatching_delta_records_mismatch_and_shrinks_interval() -> None:
    # Low floor + several matches first so the shrink is observable rather
    # than masked by the min_interval_s clamp.
    policy = AdaptiveReconciliationPolicy(min_interval_s=1.0, decrease_factor=0.4)
    for _ in range(6):
        policy.record_match()
    grown = policy.current_interval_s
    state = ReconciliationState(policy=policy, last_checked_at=0.0, last_remaining=100.0)
    log = InMemoryUsageLog()
    # Local log only saw $0.50 of usage, but the provider's balance dropped $10 —
    # something (another key, a manual playground call) spent outside our tracking.
    log.record("s1", cost_usd=0.5, now=15.0)
    verifier = _FakeVerifier([90.0])

    outcome = await maybe_reconcile(state, "s1", log, verifier, now=grown)

    assert outcome is not None
    assert outcome.matched is False
    assert policy.current_interval_s == pytest.approx(grown * 0.4)


async def test_credit_top_up_does_not_crash_zero_provider_delta() -> None:
    """A negative provider_delta (balance went UP between checks, e.g. a top-up)
    must not divide-by-zero or blow up the tolerance comparison."""
    policy = AdaptiveReconciliationPolicy(min_interval_s=30.0)
    state = ReconciliationState(policy=policy, last_checked_at=0.0, last_remaining=10.0)
    log = InMemoryUsageLog()
    verifier = _FakeVerifier([50.0])  # remaining went UP (topped off)

    outcome = await maybe_reconcile(state, "s1", log, verifier, now=30.0)

    assert outcome is not None
    assert outcome.provider_delta == pytest.approx(-40.0)
    assert outcome.matched is False  # local_delta=0 vs provider_delta=-40, well outside tolerance


# --- reconcile_ambient -------------------------------------------------------


def _snapshot(remaining: float, unit: LimitUnit = LimitUnit.REQUESTS) -> ProviderQuotaSnapshot:
    return ProviderQuotaSnapshot(scope_key="s1", unit=unit, remaining=remaining, checked_at=0.0)


def test_ambient_first_check_establishes_baseline_without_touching_policy() -> None:
    policy = AdaptiveReconciliationPolicy(min_interval_s=30.0)
    state = ReconciliationState(policy=policy)

    outcome = reconcile_ambient(state, "s1", InMemoryUsageLog(), _snapshot(100.0), now=1000.0)

    assert outcome.matched is None
    assert state.last_remaining == 100.0
    assert policy.current_interval_s == 30.0  # untouched, same as maybe_reconcile's first check


def test_ambient_never_touches_policy_interval_even_on_mismatch() -> None:
    """Unlike maybe_reconcile, ambient reconciliation doesn't pace anything --
    there's no explicit network call to throttle, so a mismatch shouldn't
    shrink an interval nobody is using for this signal."""
    policy = AdaptiveReconciliationPolicy(min_interval_s=30.0)
    state = ReconciliationState(policy=policy, last_checked_at=0.0, last_remaining=100.0)
    log = InMemoryUsageLog()
    # Local log saw nothing, but the ambient signal says usage dropped a lot --
    # a real mismatch, yet the policy interval must stay exactly where it was.
    before = policy.current_interval_s

    outcome = reconcile_ambient(state, "s1", log, _snapshot(10.0), now=30.0)

    assert outcome.matched is False
    assert policy.current_interval_s == before


def test_ambient_runs_unconditionally_regardless_of_elapsed_time() -> None:
    """No `due()` gate at all -- called back-to-back, both calls reconcile."""
    # would block maybe_reconcile since seconds_since_last_check (1s) < min_interval_s
    policy = AdaptiveReconciliationPolicy(min_interval_s=3600.0, max_interval_s=7200.0)
    state = ReconciliationState(policy=policy, last_checked_at=0.0, last_remaining=100.0)
    log = InMemoryUsageLog()

    first = reconcile_ambient(state, "s1", log, _snapshot(99.0), now=1.0)
    second = reconcile_ambient(state, "s1", log, _snapshot(98.0), now=2.0)

    assert first.matched is not None
    assert second.matched is not None
    assert state.last_remaining == 98.0


def test_ambient_matching_delta_reports_matched_true() -> None:
    state = ReconciliationState(
        policy=AdaptiveReconciliationPolicy(), last_checked_at=0.0, last_remaining=1000.0
    )
    log = InMemoryUsageLog()
    log.record("s1", now=15.0)  # 1 request recorded locally
    # Provider's remaining requests dropped by 1 too -- matches.
    outcome = reconcile_ambient(state, "s1", log, _snapshot(999.0), now=30.0)
    assert outcome.matched is True


async def test_steady_ambient_traffic_does_not_indefinitely_suppress_explicit_checks() -> None:
    """Regression: on a shared ReconciliationState, reconcile_ambient used to
    bump the same `last_checked_at` field maybe_reconcile's due() gate read,
    so frequent ambient calls (real LLM traffic) kept resetting that clock
    and could suppress explicit verification indefinitely even though the
    adaptive interval itself never grew."""
    policy = AdaptiveReconciliationPolicy(min_interval_s=60.0)
    state = ReconciliationState(policy=policy, last_remaining=1000.0)
    verifier = _FakeVerifier([900.0])
    log = InMemoryUsageLog()

    # Steady ambient traffic every 10s, well inside the 60s explicit interval,
    # for longer than that interval in total elapsed time.
    for t in (10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0):
        reconcile_ambient(state, "s1", log, _snapshot(950.0), now=t)

    # 70s have elapsed since the state was created (last_explicit_check_at
    # starts at 0.0) -- comfortably past the 60s interval, so the explicit
    # check must fire despite the constant ambient traffic in between.
    outcome = await maybe_reconcile(state, "s1", log, verifier, now=70.0)
    assert outcome is not None
    assert verifier.calls == 1
