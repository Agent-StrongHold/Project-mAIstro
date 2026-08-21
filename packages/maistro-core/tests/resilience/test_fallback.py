from __future__ import annotations

import pytest

from maistro.resilience.classifier import ErrorCategory
from maistro.resilience.fallback import (
    FailoverReason,
    FallbackChain,
    FallbackChainConfig,
    FallbackState,
    ProviderEndpoint,
    _classify_to_reason,
)


def _ep(name: str, priority: int = 0) -> ProviderEndpoint:
    return ProviderEndpoint(name=name, model=f"{name}-model", priority=priority)


class TestProviderEndpoint:
    def test_defaults(self):
        ep = ProviderEndpoint(name="test", model="gpt-4")
        assert ep.api_key == ""
        assert ep.base_url == ""
        assert ep.priority == 0
        assert ep.metadata == {}

    def test_sorted_by_priority(self):
        eps = [_ep("c", priority=2), _ep("a", priority=0), _ep("b", priority=1)]
        chain = FallbackChain(eps)
        assert chain.endpoints[0].name == "a"
        assert chain.endpoints[1].name == "b"
        assert chain.endpoints[2].name == "c"


class TestFallbackState:
    def test_initial_state(self):
        state = FallbackState()
        assert state.current_index == 0
        assert state.is_on_primary is True
        assert state.failover_count == 0
        assert state.consecutive_successes == 0

    def test_to_dict(self):
        state = FallbackState(
            current_index=1,
            failover_count=2,
            last_failover_reason=FailoverReason.RATE_LIMIT,
            consecutive_successes=5,
        )
        d = state.to_dict()
        assert d["current_index"] == 1
        assert d["failover_count"] == 2
        assert d["last_failover_reason"] == "rate_limit"
        assert d["is_on_primary"] is False
        assert d["consecutive_successes"] == 5


class TestFallbackChainBasic:
    def test_requires_at_least_one_endpoint(self):
        with pytest.raises(ValueError, match="at least one"):
            FallbackChain([])

    def test_current_returns_primary(self):
        chain = FallbackChain([_ep("primary"), _ep("fallback")])
        assert chain.current.name == "primary"
        assert chain.primary.name == "primary"

    def test_record_success_stays_on_primary(self):
        chain = FallbackChain([_ep("primary")])
        chain.record_success()
        assert chain.state.is_on_primary
        assert chain.state.consecutive_successes == 1


class TestFallbackChainFailover:
    def test_failover_on_rate_limit(self):
        chain = FallbackChain([_ep("primary"), _ep("fallback")])
        result = chain.record_failure(ConnectionError("429 Too Many Requests"))
        assert result is True
        assert chain.current.name == "fallback"
        assert chain.state.failover_count == 1
        assert chain.state.last_failover_reason == FailoverReason.CONNECTION

    def test_failover_on_timeout(self):
        chain = FallbackChain([_ep("primary"), _ep("fallback")])
        result = chain.record_failure(TimeoutError("request timed out"))
        assert result is True
        assert chain.current.name == "fallback"

    def test_failover_on_connection_error(self):
        chain = FallbackChain([_ep("primary"), _ep("fallback")])
        result = chain.record_failure(ConnectionError("Connection reset by peer"))
        assert result is True

    def test_no_failover_on_permanent_error(self):
        chain = FallbackChain([_ep("primary"), _ep("fallback")])
        result = chain.record_failure(ValueError("Invalid request format"))
        assert result is False
        assert chain.state.is_on_primary

    def test_no_failover_when_exhausted(self):
        chain = FallbackChain([_ep("primary"), _ep("fallback")])
        chain.record_failure(ConnectionError("429"))
        result = chain.record_failure(ConnectionError("429"))
        assert result is False
        assert chain.current.name == "fallback"

    def test_multi_level_failover(self):
        chain = FallbackChain([_ep("a"), _ep("b"), _ep("c")])
        chain.record_failure(ConnectionError("429"))
        assert chain.current.name == "b"
        chain.record_failure(ConnectionError("429"))
        assert chain.current.name == "c"
        chain.record_failure(ConnectionError("429"))
        assert chain.current.name == "c"

    def test_max_failovers_limit(self):
        chain = FallbackChain(
            [_ep("a"), _ep("b"), _ep("c")],
            FallbackChainConfig(max_failovers=1),
        )
        chain.record_failure(ConnectionError("429"))
        assert chain.current.name == "b"
        result = chain.record_failure(ConnectionError("429"))
        assert result is False

    def test_next_endpoint_after_failure(self):
        chain = FallbackChain([_ep("primary"), _ep("fallback")])
        ep = chain.next_endpoint_after_failure(ConnectionError("429"))
        assert ep is not None
        assert ep.name == "fallback"

    def test_next_endpoint_returns_none_when_exhausted(self):
        chain = FallbackChain([_ep("primary")])
        ep = chain.next_endpoint_after_failure(ConnectionError("429"))
        assert ep is None


class TestFallbackChainRestore:
    def test_restore_after_successes(self):
        chain = FallbackChain(
            [_ep("primary"), _ep("fallback")],
            FallbackChainConfig(restore_after_successes=2, restore_cooldown_seconds=0),
        )
        chain.record_failure(ConnectionError("429"))
        assert chain.current.name == "fallback"
        chain.record_success()
        assert chain.current.name == "fallback"
        chain.record_success()
        assert chain.current.name == "primary"

    def test_restore_respects_cooldown(self):
        chain = FallbackChain(
            [_ep("primary"), _ep("fallback")],
            FallbackChainConfig(restore_after_successes=1, restore_cooldown_seconds=9999),
        )
        chain.record_failure(ConnectionError("429"))
        chain.record_success()
        assert chain.current.name == "fallback"

    def test_no_restore_when_already_on_primary(self):
        chain = FallbackChain([_ep("primary")])
        for _ in range(10):
            chain.record_success()
        assert chain.state.is_on_primary

    def test_failover_then_restore_then_failover(self):
        chain = FallbackChain(
            [_ep("primary"), _ep("fallback")],
            FallbackChainConfig(restore_after_successes=1, restore_cooldown_seconds=0),
        )
        chain.record_failure(ConnectionError("429"))
        assert chain.current.name == "fallback"
        chain.record_success()
        assert chain.current.name == "primary"
        chain.record_failure(ConnectionError("429"))
        assert chain.current.name == "fallback"


class TestFallbackChainReset:
    def test_reset_returns_to_primary(self):
        chain = FallbackChain([_ep("primary"), _ep("fallback")])
        chain.record_failure(ConnectionError("429"))
        assert chain.current.name == "fallback"
        chain.reset()
        assert chain.state.is_on_primary
        assert chain.state.failover_count == 0
        assert chain.state.consecutive_successes == 0


class TestClassifyToReason:
    def test_all_categories(self):
        assert _classify_to_reason_type(ErrorCategory.RATE_LIMIT) == FailoverReason.RATE_LIMIT
        assert _classify_to_reason_type(ErrorCategory.PROVIDER) == FailoverReason.OVERLOAD
        assert _classify_to_reason_type(ErrorCategory.NETWORK) == FailoverReason.CONNECTION
        assert _classify_to_reason_type(ErrorCategory.TIMEOUT) == FailoverReason.TIMEOUT
        assert (
            _classify_to_reason_type(ErrorCategory.CONTEXT_OVERFLOW)
            == FailoverReason.CONTEXT_OVERFLOW
        )

    def test_unknown_for_unmapped(self):
        assert _classify_to_reason_type(ErrorCategory.AUTH) == FailoverReason.UNKNOWN


def _classify_to_reason_type(category: ErrorCategory) -> FailoverReason:
    from maistro.resilience.classifier import ClassifiedError

    ce = ClassifiedError(
        category=category,
        original=RuntimeError("test"),
        message="test",
        retryable=True,
    )
    return _classify_to_reason(ce)
