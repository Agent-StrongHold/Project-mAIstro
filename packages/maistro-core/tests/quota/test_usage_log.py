"""Tests for the local sliding-window usage cache."""

from __future__ import annotations

import pytest

from maistro.quota.rate_profile import LimitUnit
from maistro.quota.usage_log import InMemoryUsageLog, get_default_usage_log, set_default_usage_log


@pytest.fixture(autouse=True)
def _reset_default_usage_log() -> None:
    set_default_usage_log(None)
    yield
    set_default_usage_log(None)


def test_count_since_counts_requests_in_window() -> None:
    log = InMemoryUsageLog()
    now = 1000.0
    log.record("s1", now=now - 30)
    log.record("s1", now=now - 10)
    log.record("s1", now=now - 200)  # outside a 60s window
    assert log.count_since("s1", 60, now=now) == 2.0


def test_tokens_since_splits_input_and_output() -> None:
    log = InMemoryUsageLog()
    now = 1000.0
    log.record("s1", input_tokens=100, output_tokens=20, now=now - 5)
    log.record("s1", input_tokens=50, output_tokens=10, now=now - 5)
    assert log.tokens_since("s1", 60, LimitUnit.INPUT_TOKENS, now=now) == 150.0
    assert log.tokens_since("s1", 60, LimitUnit.OUTPUT_TOKENS, now=now) == 30.0
    assert log.tokens_since("s1", 60, LimitUnit.TOTAL_TOKENS, now=now) == 180.0


def test_tokens_since_rejects_requests_unit() -> None:
    log = InMemoryUsageLog()
    with pytest.raises(ValueError, match="token/image"):
        log.tokens_since("s1", 60, LimitUnit.REQUESTS)


def test_sum_between_credits() -> None:
    log = InMemoryUsageLog()
    log.record("s1", cost_usd=0.02, now=100)
    log.record("s1", cost_usd=0.03, now=110)
    log.record("s1", cost_usd=0.05, now=500)  # outside the queried range
    assert log.sum_between("s1", LimitUnit.CREDITS_USD, 90, 200) == pytest.approx(0.05)


def test_sum_between_images() -> None:
    log = InMemoryUsageLog()
    log.record("s1", images=2, now=100)
    log.record("s1", images=1, now=105)
    assert log.sum_between("s1", LimitUnit.IMAGES, 0, 200) == 3.0


def test_unknown_scope_returns_zero_not_error() -> None:
    log = InMemoryUsageLog()
    assert log.count_since("never-seen", 60) == 0.0
    assert log.tokens_since("never-seen", 60, LimitUnit.TOTAL_TOKENS) == 0.0


def test_scopes_are_independent() -> None:
    log = InMemoryUsageLog()
    now = 1000.0
    log.record("scope-a", now=now)
    assert log.count_since("scope-a", 60, now=now) == 1.0
    assert log.count_since("scope-b", 60, now=now) == 0.0


def test_events_older_than_retention_are_pruned() -> None:
    log = InMemoryUsageLog(max_retention_s=100.0)
    log.record("s1", now=0.0)
    log.record("s1", now=500.0)  # triggers pruning of the now-ancient first event
    # Querying a huge window should only see the retained event.
    assert log.count_since("s1", 10_000, now=500.0) == 1.0


def test_sum_between_is_exclusive_start_inclusive_end() -> None:
    log = InMemoryUsageLog()
    log.record("s1", now=100.0)
    # An event exactly at the end boundary counts (matches "count_since(...,
    # now=now)" including something recorded at this very instant).
    assert log.sum_between("s1", LimitUnit.REQUESTS, 0.0, 100.0) == 1.0
    # An event exactly at the start boundary of the *next* window doesn't
    # double-count into it.
    assert log.sum_between("s1", LimitUnit.REQUESTS, 100.0, 200.0) == 0.0


def test_get_default_usage_log_lazily_constructs_once() -> None:
    first = get_default_usage_log()
    second = get_default_usage_log()
    assert first is second


def test_set_default_usage_log_overrides_the_singleton() -> None:
    override = InMemoryUsageLog()
    set_default_usage_log(override)
    assert get_default_usage_log() is override


def test_set_default_usage_log_none_resets_to_a_fresh_instance() -> None:
    override = InMemoryUsageLog()
    set_default_usage_log(override)
    set_default_usage_log(None)
    assert get_default_usage_log() is not override
