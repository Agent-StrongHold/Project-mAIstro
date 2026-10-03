"""Reconciliation: infrequent, adaptive verification against provider ground truth.

The local usage log is the only thing ever read for a real decision. A
`QuotaVerifier` — where a provider actually offers one (OpenRouter's
`/api/v1/key`; most don't) — is consulted rarely, and the interval between
checks adapts to how well the local log has been tracking: a match earns a
longer wait before checking again (build confidence slowly); a mismatch
shrinks the wait by more than a match grew it (lose confidence fast — an
unnoticed drift is worse than one extra check).

`ProviderQuotaSnapshot.remaining` is a *balance* (it falls as usage occurs),
while the local log records *usage* (it rises as usage occurs) — comparing
them directly would compare inverses. So reconciliation compares *deltas*
over the interval between two checks: how much the provider's remaining
balance dropped vs. how much the local log observed in the same window.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from maistro.quota.rate_profile import LimitUnit
from maistro.quota.usage_log import InMemoryUsageLog


@dataclass(frozen=True)
class ProviderQuotaSnapshot:
    """Ground truth read from a provider's own balance/usage endpoint.

    `unit` names what `remaining` is denominated in — OpenRouter's endpoint
    reports a dollar-credit balance (`CREDITS_USD`), not a request/token
    count, so this isn't forced into the same shape `RateConstraint` uses.
    """

    scope_key: str
    unit: LimitUnit
    remaining: float
    checked_at: float


@runtime_checkable
class QuotaVerifier(Protocol):
    """A provider-specific ground-truth check. Only a minority of providers
    have one — most reconcile ambiently via response headers/body instead
    (a separate, per-call mechanism); this protocol is for the rest."""

    async def verify(self, scope_key: str) -> ProviderQuotaSnapshot: ...


@dataclass
class AdaptiveReconciliationPolicy:
    """Adjusts the wait between verifications based on the last outcome.

    Mirrors an AIMD shape but inverted in intent: `increase_factor` grows the
    interval gently on a match (don't rush to relax); `decrease_factor` must
    shrink it by *more* than a single match would have grown it, so a
    mismatch is never just "undone" by the next good check — it costs net
    trust. Enforced in `__post_init__`, not left as a convention callers
    might violate.
    """

    min_interval_s: float = 30.0
    max_interval_s: float = 3600.0
    increase_factor: float = 1.25
    decrease_factor: float = 0.4
    _current_interval_s: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.min_interval_s <= 0:
            raise ValueError("min_interval_s must be positive")
        if self.max_interval_s <= self.min_interval_s:
            raise ValueError("max_interval_s must exceed min_interval_s")
        if self.increase_factor <= 1.0:
            raise ValueError("increase_factor must be > 1.0 or the interval never grows")
        if not (0.0 < self.decrease_factor < 1.0):
            raise ValueError("decrease_factor must be in (0, 1) or the interval never shrinks")
        if self.decrease_factor >= 1.0 / self.increase_factor:
            raise ValueError(
                "decrease_factor must shrink the interval by more than one increase step "
                f"grows it: need decrease_factor < 1/increase_factor "
                f"({1.0 / self.increase_factor:.4f}), got {self.decrease_factor}"
            )
        self._current_interval_s = self.min_interval_s

    @property
    def current_interval_s(self) -> float:
        return self._current_interval_s

    def record_match(self) -> None:
        self._current_interval_s = min(
            self.max_interval_s, self._current_interval_s * self.increase_factor
        )

    def record_mismatch(self) -> None:
        self._current_interval_s = max(
            self.min_interval_s, self._current_interval_s * self.decrease_factor
        )

    def due(self, seconds_since_last_check: float) -> bool:
        return seconds_since_last_check >= self._current_interval_s


@dataclass
class ReconciliationState:
    """Per-scope-key mutable state the orchestrator threads across calls.

    `last_checked_at` is the delta-computation boundary shared by *both*
    `maybe_reconcile` and `reconcile_ambient` (it answers "how much local
    usage happened since we last had a snapshot to diff against," regardless
    of which mechanism produced that snapshot). `last_explicit_check_at` is
    separate and exists only to gate `maybe_reconcile`'s `due()` check --
    without it, steady ambient traffic (which bumps `last_checked_at` on
    every real call, `update_policy=False` or not) would keep resetting the
    clock the explicit-verifier cadence reads, silently suppressing explicit
    checks indefinitely even though the adaptive interval itself never grew.
    """

    policy: AdaptiveReconciliationPolicy
    last_checked_at: float = 0.0
    last_explicit_check_at: float = 0.0
    last_remaining: float | None = None


@dataclass(frozen=True)
class ReconciliationOutcome:
    matched: bool | None  # None on the very first check ever — no prior baseline to compare
    local_delta: float
    provider_delta: float
    snapshot: ProviderQuotaSnapshot


async def maybe_reconcile(
    state: ReconciliationState,
    scope_key: str,
    log: InMemoryUsageLog,
    verifier: QuotaVerifier,
    *,
    tolerance: float = 0.05,
    abs_floor: float = 1.0,
    now: float | None = None,
) -> ReconciliationOutcome | None:
    """Run a verification if the adaptive policy says it's due. Returns None
    if not due yet; otherwise the outcome of the comparison.

    The first-ever check for a scope key has no prior balance to diff
    against, so it only establishes the baseline — the policy interval is
    left untouched (a single reading says nothing about tracking accuracy).
    """
    now = now if now is not None else time.time()
    if not state.policy.due(now - state.last_explicit_check_at):
        return None

    snapshot = await verifier.verify(scope_key)
    outcome = _compare_and_update(
        state,
        scope_key,
        log,
        snapshot,
        tolerance=tolerance,
        abs_floor=abs_floor,
        now=now,
        update_policy=True,
    )
    state.last_explicit_check_at = now
    return outcome


def reconcile_ambient(
    state: ReconciliationState,
    scope_key: str,
    log: InMemoryUsageLog,
    snapshot: ProviderQuotaSnapshot,
    *,
    tolerance: float = 0.05,
    abs_floor: float = 1.0,
    now: float | None = None,
) -> ReconciliationOutcome:
    """Reconcile against a snapshot parsed for free from a response header/body
    already in hand (see `ambient.py`) — no network call, so no throttle: an
    ambient signal costs nothing extra, so every real call's signal is applied
    immediately. Unlike `maybe_reconcile`, this never touches
    `state.policy`'s interval — that interval paces *explicit* verification
    calls, and there's no such call to pace here.
    """
    now = now if now is not None else time.time()
    return _compare_and_update(
        state,
        scope_key,
        log,
        snapshot,
        tolerance=tolerance,
        abs_floor=abs_floor,
        now=now,
        update_policy=False,
    )


def _compare_and_update(
    state: ReconciliationState,
    scope_key: str,
    log: InMemoryUsageLog,
    snapshot: ProviderQuotaSnapshot,
    *,
    tolerance: float,
    abs_floor: float,
    now: float,
    update_policy: bool,
) -> ReconciliationOutcome:
    if state.last_remaining is None:
        outcome = ReconciliationOutcome(
            matched=None, local_delta=0.0, provider_delta=0.0, snapshot=snapshot
        )
    else:
        local_delta = log.sum_between(scope_key, snapshot.unit, state.last_checked_at, now)
        provider_delta = state.last_remaining - snapshot.remaining
        matched = _within_tolerance(local_delta, provider_delta, tolerance, abs_floor)
        if update_policy:
            if matched:
                state.policy.record_match()
            else:
                state.policy.record_mismatch()
        outcome = ReconciliationOutcome(
            matched=matched,
            local_delta=local_delta,
            provider_delta=provider_delta,
            snapshot=snapshot,
        )

    state.last_remaining = snapshot.remaining
    state.last_checked_at = now
    return outcome


def _within_tolerance(
    local_delta: float, provider_delta: float, tolerance: float, abs_floor: float
) -> bool:
    """`tolerance` is a fraction of whichever is bigger: the provider-observed
    delta, or `abs_floor`. The floor matters when `provider_delta` is ~0 (no
    usage happened, or a credit top-up occurred) — a relative comparison
    against zero is meaningless, so a small absolute band takes over instead.
    """
    scale = max(abs(provider_delta), abs_floor)
    return abs(local_delta - provider_delta) <= tolerance * scale
