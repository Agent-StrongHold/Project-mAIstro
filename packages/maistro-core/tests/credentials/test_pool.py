"""Tests for credential pool, selection strategies, and automatic key rotation."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, rule

from maistro.credentials.pool import CredentialPool
from maistro.credentials.rotation import RotationResult, execute_with_pool
from maistro.credentials.types import (
    CredentialRecord,
    PoolExhaustedError,
    SelectionStrategy,
)


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


class _HttpError(Exception):
    def __init__(self, message: str, status_code: int, headers: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = type("Resp", (), {"status_code": status_code, "headers": headers or {}})


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


class TestAutomaticRotation:
    @patch("asyncio.sleep", new_callable=AsyncMock)
    @pytest.mark.ac("ADR-063/AC-10")
    async def test_rotate_on_429(self, _mock_sleep):
        pool = _pool(["a", "b"], SelectionStrategy.FILL_FIRST)

        async def call_fn(cred: CredentialRecord):
            if cred.key_id == "a":
                raise _HttpError("Rate limit exceeded", 429)
            return "ok"

        result = await execute_with_pool(pool, call_fn, max_retries=1)
        assert result.value == "ok"
        assert result.key_id == "b"
        assert result.key_rotations == 1
        key_a = next(e for e in pool._entries if e.key_id == "a")
        assert key_a.cooldown_until is not None

    @patch("asyncio.sleep", new_callable=AsyncMock)
    @pytest.mark.ac("ADR-063/AC-12")
    @pytest.mark.ac("ADR-063/AC-26")
    async def test_429_default_cooldown_is_60_seconds(self, _mock_sleep):
        pool = _pool(["a", "b"], SelectionStrategy.FILL_FIRST)

        async def call_fn(cred: CredentialRecord):
            if cred.key_id == "a":
                raise _HttpError("Rate limit exceeded", 429)
            return "ok"

        await execute_with_pool(pool, call_fn, max_retries=1)
        key_a = next(e for e in pool._entries if e.key_id == "a")
        remaining = key_a.cooldown_until - time.monotonic()
        assert 55 < remaining <= 60

    @patch("asyncio.sleep", new_callable=AsyncMock)
    @pytest.mark.ac("ADR-063/AC-11")
    async def test_429_with_retry_after_header(self, _mock_sleep):
        pool = _pool(["a", "b"], SelectionStrategy.FILL_FIRST)

        async def call_fn(cred: CredentialRecord):
            if cred.key_id == "a":
                raise _HttpError("Slow down", 429, headers={"retry-after": "30"})
            return "ok"

        await execute_with_pool(pool, call_fn, max_retries=1)
        key_a = next(e for e in pool._entries if e.key_id == "a")
        remaining = key_a.cooldown_until - time.monotonic()
        assert 25 < remaining <= 30

    @patch("asyncio.sleep", new_callable=AsyncMock)
    @pytest.mark.ac("ADR-063/AC-27")
    async def test_429_retry_after_capped_at_60(self, _mock_sleep):
        pool = _pool(["a", "b"], SelectionStrategy.FILL_FIRST)

        async def call_fn(cred: CredentialRecord):
            if cred.key_id == "a":
                raise _HttpError("Slow down", 429, headers={"retry-after": "300"})
            return "ok"

        await execute_with_pool(pool, call_fn, max_retries=1)
        key_a = next(e for e in pool._entries if e.key_id == "a")
        remaining = key_a.cooldown_until - time.monotonic()
        assert 55 < remaining <= 60

    @patch("asyncio.sleep", new_callable=AsyncMock)
    @pytest.mark.ac("ADR-063/AC-13")
    async def test_inner_loop_retries_transient(self, _mock_sleep):
        pool = _pool(["a"])
        calls: list[str] = []

        async def call_fn(cred: CredentialRecord):
            calls.append(cred.key_id)
            if len(calls) == 1:
                raise _HttpError("Internal Server Error", 500)
            if len(calls) == 2:
                raise _HttpError("Bad Gateway", 502)
            return "ok"

        result = await execute_with_pool(pool, call_fn, max_retries=3)
        assert result.value == "ok"
        assert result.key_id == "a"
        assert result.attempts == 3
        assert result.retries_on_current_key == 2
        assert result.key_rotations == 0

    @patch("asyncio.sleep", new_callable=AsyncMock)
    @pytest.mark.ac("ADR-063/AC-14")
    async def test_transient_errors_set_no_cooldown(self, _mock_sleep):
        pool = _pool(["a"])
        attempt = 0

        async def call_fn(cred: CredentialRecord):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise _HttpError("Server Error", 500)
            return "ok"

        await execute_with_pool(pool, call_fn, max_retries=3)
        assert pool._entries[0].cooldown_until is None

    async def test_billing_cooldown_via_record_failure(self):
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


class TestRotationIntegration:
    async def test_happy_path(self):
        pool = _pool(["a"])

        async def call_fn(cred: CredentialRecord):
            return "result"

        result = await execute_with_pool(pool, call_fn)
        assert result.value == "result"
        assert result.key_id == "a"
        assert result.attempts == 1
        assert result.key_rotations == 0
        assert result.retries_on_current_key == 0

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_rotation_on_429_failure(self, _mock_sleep):
        pool = _pool(["a", "b"], SelectionStrategy.FILL_FIRST)

        async def call_fn(cred: CredentialRecord):
            if cred.key_id == "a":
                raise _HttpError("Rate limit exceeded", 429)
            return "ok"

        result = await execute_with_pool(pool, call_fn, max_retries=1)
        assert result.value == "ok"
        assert result.key_id == "b"
        assert result.key_rotations == 1

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_pool_exhaustion_from_rotation(self, _mock_sleep):
        pool = _pool(["a", "b"])

        async def call_fn(cred: CredentialRecord):
            raise _HttpError("Rate limit exceeded", 429)

        with pytest.raises(PoolExhaustedError) as exc_info:
            await execute_with_pool(pool, call_fn, max_retries=1)
        assert exc_info.value.provider == "openai"
        assert exc_info.value.total_keys == 2

    @pytest.mark.ac("ADR-063/AC-30")
    async def test_success_records_use_count(self):
        pool = _pool(["a"])

        async def call_fn(cred: CredentialRecord):
            return "ok"

        await execute_with_pool(pool, call_fn)
        assert pool._entries[0].use_count == 1

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_max_key_rotations_limit(self, _mock_sleep):
        pool = _pool(["a", "b", "c"])

        async def call_fn(cred: CredentialRecord):
            raise _HttpError("Rate limit exceeded", 429)

        with pytest.raises(PoolExhaustedError):
            await execute_with_pool(pool, call_fn, max_retries=1, max_key_rotations=2)

    async def test_rotation_result_type(self):
        pool = _pool(["a"])

        async def call_fn(cred: CredentialRecord):
            return 42

        result = await execute_with_pool(pool, call_fn)
        assert isinstance(result, RotationResult)
        assert result.value == 42


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
