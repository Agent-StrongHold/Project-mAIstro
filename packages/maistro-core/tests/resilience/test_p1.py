"""Tests for P1 resilience (ADR-066 / SPEC-070226-af02).

RetryBudget depth enforcement, compaction, ResiliencePolicy control-scope
gating, error-code classification, backoff, and executor integration.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.graph.events import GraphEvent
from maistro.graph.executor import execute_with_resilience
from maistro.resilience.p1 import (
    DEFAULT_POLICY,
    CompactedRetry,
    InMemoryResiliencePolicyStore,
    Layer,
    ResiliencePolicy,
    RetryAttempt,
    RetryBudget,
    classify_error_code,
    compact_attempts,
    exponential_backoff,
    linear_backoff,
)


class RateLimitError(Exception):
    def __init__(self, message: str = "429 rate limit exceeded") -> None:
        super().__init__(message)
        self.status_code = 429


class RefusalError(Exception):
    def __init__(self) -> None:
        super().__init__("request refused by content policy")


# ---------------------------------------------------------------- classify


def test_classify_rate_limit() -> None:
    assert classify_error_code(RateLimitError()) == "rate_limit"


def test_classify_timeout() -> None:
    assert classify_error_code(TimeoutError("timed out")) == "timeout"


def test_classify_llm_refusal() -> None:
    assert classify_error_code(RefusalError()) == "llm_refusal"


def test_classify_unknown() -> None:
    assert classify_error_code(ValueError("weird")) == "unknown"


# ---------------------------------------------------------------- budget


def test_budget_records_attempts_and_exhausts() -> None:
    budget = RetryBudget(max_retries=3)
    assert budget.remaining == 3
    for i in range(3):
        assert not budget.exhausted
        budget.record(ValueError(f"e{i}"))
    assert budget.current_attempt == 3
    assert budget.exhausted
    assert budget.remaining == 0


def test_budget_record_classifies_error() -> None:
    budget = RetryBudget()
    attempt = budget.record(RateLimitError())
    assert attempt.error_code == "rate_limit"
    assert budget.attempts == [attempt]


# ---------------------------------------------------------------- compaction


def _attempt(code: str, ts: float, msg: str = "boom") -> RetryAttempt:
    return RetryAttempt(error_code=code, message=msg, timestamp=ts)


def test_compact_same_code_within_window() -> None:
    attempts = [_attempt("rate_limit", 0.0), _attempt("rate_limit", 1.0)]
    result = compact_attempts(attempts, window_ms=5000)
    assert len(result) == 1
    compacted = result[0]
    assert isinstance(compacted, CompactedRetry)
    assert compacted.count == 2
    assert compacted.error_code == "rate_limit"
    assert compacted.first_timestamp == 0.0
    assert compacted.last_timestamp == 1.0


def test_single_attempt_never_compacted() -> None:
    result = compact_attempts([_attempt("timeout", 0.0)], window_ms=5000)
    assert len(result) == 1
    assert isinstance(result[0], RetryAttempt)


def test_compacted_retry_always_count_ge_2() -> None:
    attempts = [
        _attempt("rate_limit", 0.0),
        _attempt("rate_limit", 1.0),
        _attempt("timeout", 2.0),
        _attempt("rate_limit", 3.0),
    ]
    result = compact_attempts(attempts, window_ms=5000)
    for entry in result:
        if isinstance(entry, CompactedRetry):
            assert entry.count >= 2


def test_attempts_outside_window_not_compacted() -> None:
    attempts = [_attempt("rate_limit", 0.0), _attempt("rate_limit", 10.0)]
    result = compact_attempts(attempts, window_ms=5000)
    assert len(result) == 2
    assert all(isinstance(e, RetryAttempt) for e in result)


def test_different_codes_grouped_separately() -> None:
    attempts = [
        _attempt("rate_limit", 0.0),
        _attempt("rate_limit", 0.5),
        _attempt("timeout", 1.0),
        _attempt("timeout", 1.5),
    ]
    result = compact_attempts(attempts, window_ms=5000)
    assert len(result) == 2
    assert all(isinstance(e, CompactedRetry) and e.count == 2 for e in result)


def test_compact_empty() -> None:
    assert compact_attempts([], window_ms=5000) == []


# ---------------------------------------------------------------- backoff


def test_exponential_backoff_sequence() -> None:
    assert [exponential_backoff(n) for n in (1, 2, 3)] == [2.0, 4.0, 8.0]


def test_exponential_backoff_capped() -> None:
    assert exponential_backoff(10, max_delay=60.0) == 60.0


def test_linear_backoff_sequence() -> None:
    assert [linear_backoff(n) for n in (1, 2, 3)] == [2.0, 4.0, 6.0]


def test_backoff_zero_for_attempt_zero() -> None:
    assert exponential_backoff(0) == 0.0
    assert linear_backoff(0) == 0.0


# ---------------------------------------------------------------- policy


def test_policy_decide_retry_then_fail() -> None:
    policy = ResiliencePolicy(max_p1_retries=3)
    assert policy.decide(1, "rate_limit") == "retry"
    assert policy.decide(2, "rate_limit") == "retry"
    assert policy.decide(3, "rate_limit") == "fail"
    assert policy.decide(4, "rate_limit") == "fail"


def test_policy_decide_escalate_wins() -> None:
    policy = ResiliencePolicy(escalate_on=frozenset({"llm_refusal"}))
    assert policy.decide(1, "llm_refusal") == "escalate"
    # escalation beats the retry ceiling check
    assert policy.decide(99, "llm_refusal") == "escalate"


def test_policy_decide_accepts_exception() -> None:
    policy = ResiliencePolicy(escalate_on=frozenset({"llm_refusal"}))
    assert policy.decide(1, RefusalError()) == "escalate"
    assert policy.decide(1, RateLimitError()) == "retry"


def test_policy_backoff_strategies() -> None:
    exp = ResiliencePolicy(backoff_strategy="exponential")
    lin = ResiliencePolicy(backoff_strategy="linear")
    assert exp.backoff_for(3) == 8.0
    assert lin.backoff_for(3) == 6.0


# ---------------------------------------------------------------- store


async def test_store_exact_match() -> None:
    policy = ResiliencePolicy(agent_id="coder", layer="agents", error_code="timeout")
    store = InMemoryResiliencePolicyStore(include_defaults=False)
    store.set(policy)
    assert await store.get("coder", "agents", "timeout") is policy


async def test_store_wildcard_fallback_order() -> None:
    layer_wide = ResiliencePolicy(agent_id="*", layer="agents", error_code="timeout")
    code_wide = ResiliencePolicy(agent_id="*", layer="*", error_code="timeout")
    store = InMemoryResiliencePolicyStore(include_defaults=False)
    store.set(code_wide)
    store.set(layer_wide)
    # (*, layer, code) is more specific than (*, *, code)
    assert await store.get("anyone", "agents", "timeout") is layer_wide
    assert await store.get("anyone", "tools", "timeout") is code_wide


async def test_store_unknown_falls_back_to_default() -> None:
    store = InMemoryResiliencePolicyStore(include_defaults=False)
    policy = await store.get("nobody", "nowhere", "unknown")
    assert policy is DEFAULT_POLICY
    assert policy.backoff_strategy == "exponential"
    assert policy.escalate_on == frozenset()


async def test_store_defaults_escalate_refusal_and_retry_rate_limits() -> None:
    store = InMemoryResiliencePolicyStore()
    refusal = await store.get("any", Layer.AGENTS.value, "llm_refusal")
    assert refusal.decide(1, "llm_refusal") == "escalate"
    tools_rl = await store.get("any", Layer.TOOLS.value, "rate_limit")
    assert tools_rl.max_p1_retries == 5


# ------------------------------------------------------- executor integration


class Recorder:
    def __init__(self) -> None:
        self.events: list[GraphEvent] = []
        self.sleeps: list[float] = []

    async def emit(self, event: GraphEvent) -> None:
        self.events.append(event)

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)

    def types(self) -> list[str]:
        return [e.type for e in self.events]


def _flaky(fail_times: int, exc_factory: Any = None) -> Any:
    state = {"calls": 0}

    async def op() -> str:
        state["calls"] += 1
        if state["calls"] <= fail_times:
            raise (exc_factory() if exc_factory else RateLimitError())
        return "ok"

    return op, state


async def test_success_first_try_no_events() -> None:
    rec = Recorder()
    op, state = _flaky(0)
    result = await execute_with_resilience(op, emit=rec.emit, sleep=rec.sleep)
    assert result == "ok"
    assert state["calls"] == 1
    assert rec.events == []


async def test_retries_then_succeeds_with_exponential_backoff() -> None:
    rec = Recorder()
    op, state = _flaky(3)
    store = InMemoryResiliencePolicyStore(
        include_defaults=False, default=ResiliencePolicy(max_p1_retries=5)
    )
    result = await execute_with_resilience(
        op,
        budget=RetryBudget(max_retries=5),
        policy_store=store,
        emit=rec.emit,
        sleep=rec.sleep,
    )
    assert result == "ok"
    assert state["calls"] == 4
    assert rec.types() == ["node.retry_attempted"] * 3
    assert rec.sleeps == [2.0, 4.0, 8.0]


async def test_fails_after_exactly_max_retries_attempts() -> None:
    """No off-by-one: max_retries=3 means exactly 3 executions, then raise."""
    rec = Recorder()
    op, state = _flaky(100)
    with pytest.raises(RateLimitError):
        await execute_with_resilience(
            op,
            budget=RetryBudget(max_retries=3),
            emit=rec.emit,
            sleep=rec.sleep,
        )
    assert state["calls"] == 3


async def test_exactly_four_events_for_three_retries_plus_exhaustion() -> None:
    rec = Recorder()
    op, _ = _flaky(100)
    with pytest.raises(RateLimitError):
        await execute_with_resilience(
            op,
            budget=RetryBudget(max_retries=3),
            run_id="r1",
            node_id="n1",
            emit=rec.emit,
            sleep=rec.sleep,
        )
    assert rec.types() == [
        "node.retry_attempted",
        "node.retry_attempted",
        "node.retry_attempted",
        "node.retry_exhausted",
    ]
    assert len(rec.events) == 4
    for event in rec.events:
        assert event.detail["source"] == "resilience.p1"
        assert event.run_id == "r1"


async def test_exhaustion_event_carries_compacted_history() -> None:
    rec = Recorder()
    op, _ = _flaky(100)
    with pytest.raises(RateLimitError):
        await execute_with_resilience(
            op, budget=RetryBudget(max_retries=3), emit=rec.emit, sleep=rec.sleep
        )
    exhausted = rec.events[-1]
    assert exhausted.type == "node.retry_exhausted"
    assert exhausted.detail["total_attempts"] == 3
    compacted = exhausted.detail["compacted"]
    assert compacted == [
        {
            "error_code": "rate_limit",
            "count": 3,
            "first_timestamp": compacted[0]["first_timestamp"],
            "last_timestamp": compacted[0]["last_timestamp"],
            "common_cause": "429 rate limit exceeded",
        }
    ]


async def test_llm_refusal_escalates_and_propagates() -> None:
    """Escalate policy: node.escalated emitted, exception propagates, no local retry."""
    rec = Recorder()
    op, state = _flaky(100, RefusalError)
    with pytest.raises(RefusalError):
        await execute_with_resilience(
            op,
            layer=Layer.AGENTS.value,
            emit=rec.emit,
            sleep=rec.sleep,
        )
    assert state["calls"] == 1
    assert rec.types() == ["node.escalated"]
    assert rec.events[0].detail["error_code"] == "llm_refusal"
    assert rec.events[0].detail["escalate_to"] == "orchestrator"
    assert rec.sleeps == []


async def test_policy_consulted_on_every_retry_decision() -> None:
    calls: list[tuple[str, str, str]] = []

    class SpyStore:
        async def get(self, agent_id: str, layer: str, error_code: str) -> ResiliencePolicy:
            calls.append((agent_id, layer, error_code))
            return ResiliencePolicy(max_p1_retries=10)

    op, _ = _flaky(100)
    rec = Recorder()
    with pytest.raises(RateLimitError):
        await execute_with_resilience(
            op,
            agent_id="coder",
            layer="tools",
            budget=RetryBudget(max_retries=4),
            policy_store=SpyStore(),
            emit=rec.emit,
            sleep=rec.sleep,
        )
    assert calls == [("coder", "tools", "rate_limit")] * 4


async def test_policy_fail_stops_before_budget_exhausted() -> None:
    rec = Recorder()
    op, state = _flaky(100)
    store = InMemoryResiliencePolicyStore(
        include_defaults=False, default=ResiliencePolicy(max_p1_retries=2)
    )
    with pytest.raises(RateLimitError):
        await execute_with_resilience(
            op,
            budget=RetryBudget(max_retries=10),
            policy_store=store,
            emit=rec.emit,
            sleep=rec.sleep,
        )
    assert state["calls"] == 2
    assert rec.types()[-1] == "node.retry_exhausted"
    assert rec.events[-1].detail["reason"] == "policy_fail"


async def test_mixed_error_codes_route_to_matching_policies() -> None:
    """A refusal on attempt 2 escalates even though attempt 1 retried."""
    state = {"calls": 0}

    async def op() -> str:
        state["calls"] += 1
        if state["calls"] == 1:
            raise RateLimitError()
        raise RefusalError()

    rec = Recorder()
    with pytest.raises(RefusalError):
        await execute_with_resilience(
            op, budget=RetryBudget(max_retries=10), emit=rec.emit, sleep=rec.sleep
        )
    assert rec.types() == ["node.retry_attempted", "node.escalated"]
