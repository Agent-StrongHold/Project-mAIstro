"""Tests for wiring real per-call usage into the local quota cache."""

from __future__ import annotations

import httpx

from maistro.quota.ambient import GroqHeaderParser
from maistro.quota.rate_profile import LimitUnit
from maistro.quota.recorder import (
    ScopedReconciliationRegistry,
    build_quota_recording_hook,
    extract_usage,
    record_ambient_signals,
    record_llm_usage,
)
from maistro.quota.usage_log import InMemoryUsageLog


def _response(json_body: dict, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json=json_body,
        headers=headers or {},
        request=httpx.Request("POST", "https://gw/v1/chat/completions"),
    )


def test_extract_usage_reads_prompt_and_completion_tokens() -> None:
    body = {"usage": {"prompt_tokens": 120, "completion_tokens": 45}}
    assert extract_usage(body) == (120, 45)


def test_extract_usage_missing_usage_is_zero_zero_not_an_error() -> None:
    assert extract_usage({"choices": []}) == (0, 0)


def test_extract_usage_malformed_usage_is_zero_zero() -> None:
    assert extract_usage({"usage": "not-a-dict"}) == (0, 0)
    assert extract_usage({"usage": {"prompt_tokens": "not-a-number"}}) == (0, 0)


def test_record_llm_usage_writes_into_the_log() -> None:
    log = InMemoryUsageLog()
    body = {"usage": {"prompt_tokens": 100, "completion_tokens": 20}}

    recorded = record_llm_usage(log, "cerebras:qwen3-235b", body, now=1000.0)

    assert recorded == (100, 20)
    assert log.tokens_since("cerebras:qwen3-235b", 60, LimitUnit.INPUT_TOKENS, now=1000.0) == 100.0
    assert log.tokens_since("cerebras:qwen3-235b", 60, LimitUnit.OUTPUT_TOKENS, now=1000.0) == 20.0
    assert log.count_since("cerebras:qwen3-235b", 60, now=1000.0) == 1.0


def test_record_llm_usage_missing_usage_still_records_a_request() -> None:
    """Even with no usage numbers, the call itself happened -- it should still
    count toward request-based constraints (RPM/RPD)."""
    log = InMemoryUsageLog()
    record_llm_usage(log, "groq:kimi-k2", {}, now=1000.0)
    assert log.count_since("groq:kimi-k2", 60, now=1000.0) == 1.0


def test_record_ambient_signals_reconciles_parsed_snapshots() -> None:
    registry = ScopedReconciliationRegistry()
    log = InMemoryUsageLog()
    response = _response(
        {"choices": []},
        headers={
            "llm_provider-x-ratelimit-remaining-requests": "950",
            "llm_provider-x-ratelimit-remaining-tokens": "4500",
        },
    )

    outcomes = record_ambient_signals(registry, log, "groq:kimi-k2", response, GroqHeaderParser())

    assert len(outcomes) == 2
    # First-ever reconciliation for each unit establishes a baseline, no verdict yet.
    assert all(o.matched is None for o in outcomes)


def test_record_ambient_signals_empty_when_no_headers_present() -> None:
    registry = ScopedReconciliationRegistry()
    log = InMemoryUsageLog()
    response = _response({"choices": []})

    outcomes = record_ambient_signals(registry, log, "groq:kimi-k2", response, GroqHeaderParser())

    assert outcomes == []


def test_registry_tracks_each_unit_independently() -> None:
    registry = ScopedReconciliationRegistry()
    requests_state = registry.get_or_create("groq:kimi-k2", LimitUnit.REQUESTS)
    tokens_state = registry.get_or_create("groq:kimi-k2", LimitUnit.TOTAL_TOKENS)
    assert requests_state is not tokens_state
    # Same (scope_key, unit) always returns the same state object.
    assert registry.get_or_create("groq:kimi-k2", LimitUnit.REQUESTS) is requests_state


def test_build_quota_recording_hook_records_usage_only_without_ambient_parser() -> None:
    log = InMemoryUsageLog()
    hook = build_quota_recording_hook(log, "mistral:mistral-small")
    response = _response({"usage": {"prompt_tokens": 10, "completion_tokens": 3}})

    hook(response.json(), response)

    assert log.tokens_since("mistral:mistral-small", 60, LimitUnit.INPUT_TOKENS) == 10.0


def test_build_quota_recording_hook_also_reconciles_ambient_signal() -> None:
    log = InMemoryUsageLog()
    hook = build_quota_recording_hook(log, "groq:kimi-k2", ambient_parser=GroqHeaderParser())
    response = _response(
        {"usage": {"prompt_tokens": 10, "completion_tokens": 3}},
        headers={"llm_provider-x-ratelimit-remaining-requests": "999"},
    )

    hook(response.json(), response)  # should not raise; records usage + ambient signal

    assert log.count_since("groq:kimi-k2", 60) == 1.0


def test_build_quota_recording_hook_shares_registry_across_hooks() -> None:
    log = InMemoryUsageLog()
    shared_registry = ScopedReconciliationRegistry()
    hook_a = build_quota_recording_hook(
        log, "groq:kimi-k2", ambient_parser=GroqHeaderParser(), registry=shared_registry
    )
    hook_b = build_quota_recording_hook(
        log, "groq:kimi-k2", ambient_parser=GroqHeaderParser(), registry=shared_registry
    )
    response = _response({}, headers={"llm_provider-x-ratelimit-remaining-requests": "500"})

    hook_a(response.json(), response)
    hook_b(response.json(), response)

    # Both hooks fed the same (scope_key, unit) state -- second call sees a
    # prior baseline, not a fresh one.
    state = shared_registry.get_or_create("groq:kimi-k2", LimitUnit.REQUESTS)
    assert state.last_remaining == 500.0
