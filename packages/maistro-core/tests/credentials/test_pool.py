"""Tests for credential pool and selection strategies.

Rotation-through-a-call moved to the Invocation path with #58: outcome-driven
cooldown/blocking is covered in ``tests/credentials/test_router.py`` and the
governed-seam composition in ``tests/capabilities/test_credential_routing.py``.
"""

from __future__ import annotations

import time
from typing import cast

import pytest
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, rule

from maistro.credentials.pool import CredentialPool
from maistro.credentials.types import (
    CredentialRecord,
    PoolExhaustedError,
    SelectionStrategy,
)


class _AdvancingMonotonicClock:
    """Scripted stand-in for ``time.monotonic()``.

    Returns the scripted readings in order, holds the last one once the
    script is exhausted, and records every reading it served so tests can
    reason about which instants the code under test sampled.
    """

    def __init__(self, readings: list[float]) -> None:
        self._readings = list(readings)
        self.served: list[float] = []

    def __call__(self) -> float:
        reading = self._readings.pop(0) if self._readings else self.served[-1]
        self.served.append(reading)
        return reading


def _rec(key_id: str, provider: str = "openai", **kwargs) -> CredentialRecord:
    return CredentialRecord(key_id=key_id, provider=provider, api_key=f"sk-{key_id}", **kwargs)


def _pool(
    keys: list[str],
    strategy: SelectionStrategy = SelectionStrategy.ROUND_ROBIN,
    provider: str = "openai",
) -> CredentialPool:
    return CredentialPool(
        provider=provider,
        entries=[_rec(k, provider) for k in keys],
        strategy=strategy,
    )


class TestCredentialRecord:
    def test_fresh_record_is_available(self):
        assert _rec("k").is_available is True

    def test_blocked_record_not_available(self):
        assert _rec("k", blocked=True).is_available is False

    def test_cooldown_active_not_available(self):
        assert _rec("k", cooldown_until=time.monotonic() + 60).is_available is False

    def test_cooldown_expired_is_available(self):
        assert _rec("k", cooldown_until=time.monotonic() - 1).is_available is True

    def test_blocked_overrides_expired_cooldown(self):
        rec = _rec("k", blocked=True, cooldown_until=time.monotonic() - 100)
        assert rec.is_available is False


class TestSelectionStrategies:
    @pytest.mark.ac("ADR-063/AC-1")
    def test_fill_first_selects_first_available(self):
        pool = CredentialPool(
            "openai", [_rec("a"), _rec("b"), _rec("c")], SelectionStrategy.FILL_FIRST
        )
        assert pool.select().key_id == "a"

    @pytest.mark.ac("ADR-063/AC-1")
    def test_fill_first_respects_priority_order(self):
        pool = CredentialPool(
            "openai",
            [_rec("c", priority=10), _rec("a", priority=1), _rec("b", priority=5)],
            SelectionStrategy.FILL_FIRST,
        )
        assert pool.select().key_id == "a"

    @pytest.mark.ac("ADR-063/AC-2")
    def test_fill_first_falls_to_next_on_cooldown(self):
        pool = CredentialPool(
            "openai",
            [_rec("a", cooldown_until=time.monotonic() + 60), _rec("b"), _rec("c")],
            SelectionStrategy.FILL_FIRST,
        )
        assert pool.select().key_id == "b"

    @pytest.mark.ac("ADR-063/AC-3")
    def test_round_robin_cycles(self):
        pool = _pool(["a", "b", "c"], SelectionStrategy.ROUND_ROBIN)
        assert [pool.select().key_id for _ in range(3)] == ["a", "b", "c"]

    @pytest.mark.ac("ADR-063/AC-4")
    def test_round_robin_wraps(self):
        pool = _pool(["a", "b", "c"], SelectionStrategy.ROUND_ROBIN)
        assert [pool.select().key_id for _ in range(5)] == ["a", "b", "c", "a", "b"]

    @pytest.mark.ac("ADR-063/AC-5")
    def test_round_robin_skips_cooldown(self):
        pool = CredentialPool(
            "openai",
            [_rec("a"), _rec("b", cooldown_until=time.monotonic() + 60), _rec("c")],
            SelectionStrategy.ROUND_ROBIN,
        )
        assert [pool.select().key_id for _ in range(4)] == ["a", "c", "a", "c"]

    @pytest.mark.ac("ADR-063/AC-9")
    def test_round_robin_skips_blocked(self):
        pool = CredentialPool(
            "openai",
            [_rec("a"), _rec("b", blocked=True), _rec("c")],
            SelectionStrategy.ROUND_ROBIN,
        )
        assert [pool.select().key_id for _ in range(4)] == ["a", "c", "a", "c"]

    @pytest.mark.ac("ADR-063/AC-6")
    def test_random_only_picks_available(self):
        pool = CredentialPool(
            "openai",
            [_rec("a"), _rec("b"), _rec("c", cooldown_until=time.monotonic() + 60)],
            SelectionStrategy.RANDOM,
        )
        for _ in range(100):
            assert pool.select().key_id in ("a", "b")

    @pytest.mark.ac("ADR-063/AC-6")
    def test_random_distributes(self):
        pool = _pool(["a", "b"], SelectionStrategy.RANDOM)
        counts = {"a": 0, "b": 0}
        for _ in range(200):
            counts[pool.select().key_id] += 1
        assert all(50 <= v <= 150 for v in counts.values())

    @pytest.mark.ac("ADR-063/AC-7")
    def test_least_used_picks_lowest_count(self):
        pool = CredentialPool(
            "openai",
            [_rec("a", use_count=10), _rec("b", use_count=3), _rec("c", use_count=7)],
            SelectionStrategy.LEAST_USED,
        )
        assert pool.select().key_id == "b"

    @pytest.mark.ac("ADR-063/AC-8")
    def test_least_used_breaks_ties_by_priority(self):
        pool = CredentialPool(
            "openai",
            [
                _rec("c", use_count=5, priority=10),
                _rec("a", use_count=5, priority=1),
                _rec("b", use_count=5, priority=5),
            ],
            SelectionStrategy.LEAST_USED,
        )
        assert pool.select().key_id == "a"


class TestScopedSelection:
    """#58: selection constrained to the credential refs a Binding authorizes."""

    def test_select_never_returns_a_key_outside_the_authorized_subset(self):
        pool = _pool(["a", "b", "c"], SelectionStrategy.ROUND_ROBIN)

        for _ in range(6):
            assert pool.select(allowed_key_ids=frozenset({"b"})).key_id == "b"

    def test_exhaustion_error_counts_only_authorized_keys(self):
        pool = CredentialPool(
            "openai",
            [
                _rec("a", cooldown_until=time.monotonic() + 60),
                _rec("b", cooldown_until=time.monotonic() + 30),
                _rec("c"),
            ],
        )
        with pytest.raises(PoolExhaustedError) as exc_info:
            pool.select(allowed_key_ids=frozenset({"a", "b"}))
        err = exc_info.value
        assert err.total_keys == 2
        assert err.cooling_down_keys == 2
        assert 20 < err.wait_seconds <= 30

    def test_authorized_subset_with_no_available_key_leaves_others_unreachable(self):
        pool = CredentialPool(
            "openai",
            [_rec("a", blocked=True), _rec("c")],
        )
        with pytest.raises(PoolExhaustedError):
            pool.select(allowed_key_ids=frozenset({"a"}))

    def test_key_ids_lists_every_configured_key(self):
        pool = _pool(["a", "b"])
        assert pool.key_ids() == frozenset({"a", "b"})

    def test_unknown_strategy_is_refused_rather_than_guessed(self):
        pool = CredentialPool("openai", [_rec("a")], cast(SelectionStrategy, "bogus"))

        with pytest.raises(ValueError, match="Unknown strategy"):
            pool.select()


class TestAutomaticRotation:
    """Cooldown mechanics driven through record_failure.

    The request-execution sequences the ADR-063 rotation scenarios describe
    (429/402 through a real call) are exercised against the router that now
    owns them in ``tests/credentials/test_router.py``.
    """

    def test_billing_cooldown_via_record_failure(self):
        pool = _pool(["a", "b"], SelectionStrategy.FILL_FIRST)
        pool.record_failure("a", status_code=402, error_code="billing", cooldown_seconds=3600)
        key_a = next(e for e in pool._entries if e.key_id == "a")
        remaining = key_a.cooldown_until - time.monotonic()
        assert 3500 < remaining <= 3600
        assert pool.select().key_id == "b"


class TestPoolExhaustion:
    @pytest.mark.ac("ADR-063/AC-17")
    def test_all_keys_in_cooldown(self):
        pool = CredentialPool(
            "openai",
            [
                _rec("a", cooldown_until=time.monotonic() + 30),
                _rec("b", cooldown_until=time.monotonic() + 120),
            ],
        )
        with pytest.raises(PoolExhaustedError) as exc_info:
            pool.select()
        err = exc_info.value
        assert err.cooling_down_keys == 2
        assert err.total_keys == 2
        assert 20 < err.wait_seconds <= 30

    @pytest.mark.ac("ADR-063/AC-18")
    def test_all_keys_blocked(self):
        pool = CredentialPool("openai", [_rec("a", blocked=True)])
        with pytest.raises(PoolExhaustedError) as exc_info:
            pool.select()
        assert exc_info.value.blocked_keys == 1
        assert exc_info.value.wait_seconds <= 0

    def test_single_key_exhaustion(self):
        pool = _pool(["a"])
        pool.record_failure("a", cooldown_seconds=60)
        with pytest.raises(PoolExhaustedError) as exc_info:
            pool.select()
        assert exc_info.value.total_keys == 1

    @pytest.mark.ac("ADR-063/AC-20")
    def test_error_contains_provider(self):
        pool = CredentialPool(
            "anthropic", [_rec("x", provider="anthropic", cooldown_until=time.monotonic() + 60)]
        )
        with pytest.raises(PoolExhaustedError) as exc_info:
            pool.select()
        assert exc_info.value.provider == "anthropic"

    def test_mixed_blocked_and_cooldown(self):
        pool = CredentialPool(
            "openai",
            [
                _rec("a", blocked=True),
                _rec("b", cooldown_until=time.monotonic() + 30),
                _rec("c", cooldown_until=time.monotonic() + 60),
            ],
        )
        with pytest.raises(PoolExhaustedError) as exc_info:
            pool.select()
        err = exc_info.value
        assert err.blocked_keys == 1
        assert err.cooling_down_keys == 2
        assert err.total_keys == 3


class TestExhaustionClockAccounting:
    """#1116: PoolExhaustedError accounting must classify every scoped key
    against one monotonic clock sample, with the same classification
    semantics get_stats() uses -- the clock-boundary race #1041 removed from
    get_stats() but left in _exhaustion_counts()."""

    @staticmethod
    def _cooling_at(entries: list[CredentialRecord], now: float) -> int:
        """Independent oracle: cooling-down count at a single instant."""

        return sum(
            1
            for e in entries
            if not e.blocked and e.cooldown_until is not None and e.cooldown_until > now
        )

    def test_clock_crossing_cooldown_boundaries_cannot_contradict_the_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # b expires at 100, c at 200. The fake clock serves 10 while select()
        # inspects availability, then crosses BOTH expiries while the
        # accounting scans the scoped set: per-entry readings would see b
        # cooling (99 < 100) but c already available (201 > 200) and report
        # blocked + cooling = 1 -- a count true at none of the sampled
        # instants ("all 2 authorized credentials exhausted", only 1
        # accounted for). One sample (99.0) makes both keys cooling and the
        # accounting exact. The unauthorized cooling x and available z must
        # stay out of the counts entirely.
        clock = _AdvancingMonotonicClock([10.0, 10.0, 10.0, 99.0, 201.0])
        monkeypatch.setattr(time, "monotonic", clock)
        pool = CredentialPool(
            "openai",
            [
                _rec("b", cooldown_until=100.0),
                _rec("c", cooldown_until=200.0),
                _rec("x", cooldown_until=500.0),  # cooling but NOT authorized
                _rec("z"),  # available but NOT authorized
            ],
        )

        with pytest.raises(PoolExhaustedError) as exc_info:
            pool.select(allowed_key_ids=frozenset({"b", "c"}))
        err = exc_info.value

        assert err.total_keys == 2  # only the authorized keys are accounted
        assert err.blocked_keys == 0
        assert err.cooling_down_keys == 2  # per-entry sampling yields 1
        assert err.soonest_available_at == 100.0
        # exactly one accounting sample: three availability checks in
        # _available (b, c, x) plus one reading classifying the scoped set
        assert len(clock.served) == 4
        # the reported counts are the truth at one of the sampled instants
        scoped = [e for e in pool._entries if e.key_id in {"b", "c"}]
        assert any(self._cooling_at(scoped, t) == err.cooling_down_keys for t in clock.served)

    def test_exhaustion_error_and_stats_classify_identically_at_one_instant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Frozen clock: both reporters classify the same state at the same
        # instant and must agree exactly -- two subtly different rules
        # (per-entry vs one sample, >= vs >) would eventually disagree here.
        monkeypatch.setattr(time, "monotonic", lambda: 150.0)
        pool = CredentialPool(
            "openai",
            [
                _rec("a", blocked=True),
                _rec("b", cooldown_until=200.0),
                _rec("c", cooldown_until=160.0),
            ],
        )
        stats = pool.get_stats()
        assert stats.total_keys == 3
        assert stats.available_keys == 0
        assert stats.blocked_keys == 1
        assert stats.cooling_down_keys == 2

        with pytest.raises(PoolExhaustedError) as exc_info:
            pool.select()
        err = exc_info.value
        assert (err.total_keys, err.blocked_keys, err.cooling_down_keys) == (
            stats.total_keys,
            stats.blocked_keys,
            stats.cooling_down_keys,
        )
        assert err.blocked_keys + err.cooling_down_keys == err.total_keys
        assert err.soonest_available_at == 160.0

    def test_cooldown_expiry_boundary_is_available_not_cooling_everywhere(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A key is selectable the instant its cooldown expires: the shared
        # boundary rule (cooldown_until > now) must agree between stats
        # accounting and actual selection at the boundary itself.
        monkeypatch.setattr(time, "monotonic", lambda: 160.0)
        pool = CredentialPool("openai", [_rec("c", cooldown_until=160.0)])
        stats = pool.get_stats()
        assert stats.available_keys == 1
        assert stats.cooling_down_keys == 0
        assert stats.blocked_keys == 0
        assert pool.select().key_id == "c"


class TestCooldownAndRecovery:
    @pytest.mark.ac("ADR-063/AC-21")
    def test_available_after_cooldown_expires(self):
        rec = _rec("a", cooldown_until=time.monotonic() - 1)
        pool = CredentialPool("openai", [rec, _rec("b")])
        assert pool.select().key_id == "a"

    @pytest.mark.ac("ADR-063/AC-22")
    def test_unavailable_during_cooldown(self):
        pool = CredentialPool("openai", [_rec("a", cooldown_until=time.monotonic() + 60)])
        with pytest.raises(PoolExhaustedError):
            pool.select()

    @pytest.mark.ac("ADR-063/AC-23")
    def test_record_success_clears_error_state(self):
        rec = _rec("a", last_error_code="rate_limit", use_count=5)
        pool = CredentialPool("openai", [rec])
        pool.record_success("a")
        assert rec.last_status == 200
        assert rec.last_error_code is None
        assert rec.use_count == 6
        assert rec.last_used_at is not None

    @pytest.mark.ac("ADR-063/AC-24")
    def test_401_blocks_key(self):
        pool = CredentialPool("openai", [_rec("a"), _rec("b")])
        pool.record_failure("a", status_code=401, block=True)
        key_a = next(e for e in pool._entries if e.key_id == "a")
        assert key_a.blocked is True
        assert key_a.is_available is False

    @pytest.mark.ac("ADR-063/AC-25")
    def test_403_blocks_key(self):
        pool = CredentialPool("openai", [_rec("a"), _rec("b")])
        pool.record_failure("a", status_code=403, block=True)
        key_a = next(e for e in pool._entries if e.key_id == "a")
        assert key_a.blocked is True

    @pytest.mark.ac("ADR-063/AC-26")
    def test_rate_limit_cooldown_set(self):
        pool = _pool(["a"])
        pool.record_failure("a", status_code=429, error_code="rate_limit", cooldown_seconds=60)
        remaining = pool._entries[0].cooldown_until - time.monotonic()
        assert 0 < remaining <= 60

    def test_clear_cooldown_resets_key(self):
        rec = _rec(
            "a", cooldown_until=time.monotonic() + 60, last_status=429, last_error_code="rate_limit"
        )
        pool = CredentialPool("openai", [rec])
        pool.clear_cooldown("a")
        assert rec.cooldown_until is None
        assert rec.blocked is False
        assert rec.is_available is True
        assert rec.last_status is None
        assert rec.last_error_code is None

    def test_clear_all_cooldowns(self):
        pool = CredentialPool(
            "openai",
            [
                _rec("a", cooldown_until=time.monotonic() + 30, last_status=429),
                _rec("b", blocked=True, last_status=401),
            ],
        )
        pool.clear_all_cooldowns()
        assert all(e.is_available for e in pool._entries)
        assert all(e.last_status is None for e in pool._entries)


class TestPoolStats:
    @pytest.mark.ac("ADR-063/AC-28")
    def test_stats_reflect_current_state(self):
        pool = CredentialPool(
            "openai",
            [
                _rec("a", use_count=100, error_count=2),
                _rec("b", use_count=80, cooldown_until=time.monotonic() + 30),
                _rec("c", blocked=True),
            ],
        )
        stats = pool.get_stats()
        assert stats.total_keys == 3
        assert stats.available_keys == 1
        assert stats.cooling_down_keys == 1
        assert stats.blocked_keys == 1
        assert stats.total_use_count == 180
        assert stats.total_error_count == 2

    @pytest.mark.ac("ADR-063/AC-29")
    def test_stats_per_key_breakdown(self):
        pool = _pool(["a", "b"])
        stats = pool.get_stats()
        assert len(stats.per_key) == 2
        key_ids = {r["key_id"] for r in stats.per_key}
        assert key_ids == {"a", "b"}
        for r in stats.per_key:
            assert "use_count" in r
            assert "error_count" in r
            assert "is_available" in r

    @pytest.mark.ac("ADR-063/AC-30")
    def test_record_success_increments_use_count(self):
        rec = _rec("a")
        pool = CredentialPool("openai", [rec])
        pool.record_success("a")
        assert rec.use_count == 1
        assert rec.last_used_at is not None

    @pytest.mark.ac("ADR-063/AC-31")
    def test_record_failure_increments_error_count(self):
        rec = _rec("a")
        pool = CredentialPool("openai", [rec])
        pool.record_failure("a", status_code=429, error_code="rate_limit")
        assert rec.error_count == 1

    @pytest.mark.ac("ADR-063/AC-32")
    def test_stats_reports_strategy(self):
        pool = _pool(["a"], strategy=SelectionStrategy.LEAST_USED)
        assert pool.get_stats().strategy == SelectionStrategy.LEAST_USED


class CredentialPoolMachine(RuleBasedStateMachine):
    """Stateful fuzz over interleaved select/record_failure/record_success/
    clear_cooldown/remove calls — mirrors formal/models/test_strike_escalation.py's
    RuleBasedStateMachine pattern. Random interleavings must never violate the
    pool's core invariants: the stats partition always accounts for every key,
    select() never returns a blocked or cooling-down entry, and mutating
    methods on an unknown/already-removed key_id are silent no-ops rather than
    raising (matching CredentialPool._find's documented behavior)."""

    keys = Bundle("keys")

    def __init__(self) -> None:
        super().__init__()
        self.pool = CredentialPool("openai", strategy=SelectionStrategy.ROUND_ROBIN)
        self.live_keys: set[str] = set()
        self._next_id = 0

    @rule(target=keys)
    def add_key(self) -> str:
        key_id = f"k{self._next_id}"
        self._next_id += 1
        self.pool.add(CredentialRecord(key_id=key_id, provider="openai", api_key=f"sk-{key_id}"))
        self.live_keys.add(key_id)
        return key_id

    @rule(key=keys)
    def remove_key(self, key: str) -> None:
        if self.pool.remove(key):
            self.live_keys.discard(key)

    @rule(
        key=keys,
        status_code=st.sampled_from([429, 500, 401, 403, 0]),
        cooldown_seconds=st.floats(
            min_value=0, max_value=120, allow_nan=False, allow_infinity=False
        ),
        block=st.booleans(),
    )
    def record_failure(
        self, key: str, status_code: int, cooldown_seconds: float, block: bool
    ) -> None:
        self.pool.record_failure(
            key, status_code=status_code, cooldown_seconds=cooldown_seconds, block=block
        )

    @rule(key=keys)
    def record_success(self, key: str) -> None:
        self.pool.record_success(key)

    @rule(key=keys)
    def clear_cooldown(self, key: str) -> None:
        self.pool.clear_cooldown(key)

    @rule()
    def try_select(self) -> None:
        try:
            rec = self.pool.select()
        except PoolExhaustedError as exc:
            assert exc.total_keys == self.pool.size
            return
        assert rec.is_available
        assert not rec.blocked

    @invariant()
    def stats_partition_covers_every_key(self) -> None:
        stats = self.pool.get_stats()
        assert stats.total_keys == self.pool.size
        assert (
            stats.total_keys == stats.available_keys + stats.blocked_keys + stats.cooling_down_keys
        )

    @invariant()
    def pool_size_matches_tracked_live_keys(self) -> None:
        assert self.pool.size == len(self.live_keys)


TestCredentialPoolMachine = CredentialPoolMachine.TestCase
