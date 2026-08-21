"""Tests for the unified rate-constraint model."""

from __future__ import annotations

import pytest

from maistro.quota.rate_profile import (
    LimitUnit,
    LimitWindow,
    ModelRateProfile,
    RateConstraint,
    cycles_remaining,
    headroom,
)
from maistro.quota.usage_log import InMemoryUsageLog


def test_rate_constraint_rejects_nonpositive_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        RateConstraint(unit=LimitUnit.REQUESTS, window=LimitWindow.MINUTE, limit=0)


def test_scope_key_org_pooled_ignores_model() -> None:
    profile = ModelRateProfile(provider="openai", model="gpt-5", scope_key_fields=("provider",))
    assert profile.scope_key(model="other-model") == "openai"


def test_scope_key_per_key_and_model() -> None:
    profile = ModelRateProfile(
        provider="anthropic",
        model="claude-sonnet",
        scope_key_fields=("provider", "model", "api_key"),
    )
    assert profile.scope_key(api_key="k1") == "anthropic:claude-sonnet:k1"


def test_scope_key_per_endpoint_cohere_style() -> None:
    profile = ModelRateProfile(
        provider="cohere", model="command-a", scope_key_fields=("provider", "endpoint")
    )
    assert profile.scope_key(endpoint="chat") == "cohere:chat"
    assert profile.scope_key(endpoint="embed") == "cohere:embed"


def test_headroom_never_negative() -> None:
    log = InMemoryUsageLog()
    constraint = RateConstraint(unit=LimitUnit.REQUESTS, window=LimitWindow.MINUTE, limit=5)
    for _ in range(10):
        log.record("scope1")
    assert headroom(constraint, "scope1", log) == 0.0


def test_headroom_reflects_remaining_capacity() -> None:
    log = InMemoryUsageLog()
    constraint = RateConstraint(unit=LimitUnit.REQUESTS, window=LimitWindow.MINUTE, limit=10)
    for _ in range(3):
        log.record("scope1")
    assert headroom(constraint, "scope1", log) == 7.0


def test_cycles_remaining_unconstrained_model_is_infinite() -> None:
    profile = ModelRateProfile(provider="local", model="ollama-llama")
    log = InMemoryUsageLog()
    result = cycles_remaining(profile, log, requests_per_cycle=1, tokens_per_cycle=100)
    assert result == float("inf")


def test_cycles_remaining_single_constraint() -> None:
    profile = ModelRateProfile(
        provider="groq",
        model="kimi-k2",
        constraints=(RateConstraint(unit=LimitUnit.REQUESTS, window=LimitWindow.DAY, limit=1000),),
    )
    log = InMemoryUsageLog()
    for _ in range(400):
        log.record(profile.scope_key())
    # 600 requests remain; at 2 requests/cycle that's 300 cycles.
    result = cycles_remaining(profile, log, requests_per_cycle=2, tokens_per_cycle=1)
    assert result == 300.0


def test_cycles_remaining_takes_the_tightest_constraint() -> None:
    """Cerebras-style: multiple simultaneous windows on both requests and tokens —
    the binding constraint is whichever converts to the fewest cycles."""
    profile = ModelRateProfile(
        provider="cerebras",
        model="qwen3-235b",
        constraints=(
            RateConstraint(unit=LimitUnit.REQUESTS, window=LimitWindow.MINUTE, limit=30),
            RateConstraint(unit=LimitUnit.REQUESTS, window=LimitWindow.HOUR, limit=900),
            RateConstraint(unit=LimitUnit.REQUESTS, window=LimitWindow.DAY, limit=14_400),
            RateConstraint(unit=LimitUnit.TOTAL_TOKENS, window=LimitWindow.MINUTE, limit=60_000),
        ),
    )
    log = InMemoryUsageLog()
    # No usage yet: RPM=30 -> 30/1=30 cycles; RPH=900 -> 900 cycles;
    # RPD=14400 -> 14400 cycles; TPM=60000 -> 60000/1000=60 cycles.
    # RPM is tightest at 30 cycles.
    result = cycles_remaining(profile, log, requests_per_cycle=1, tokens_per_cycle=1000)
    assert result == 30.0


def test_cycles_remaining_ignores_zero_per_cycle_dimension() -> None:
    """A constraint whose per-cycle cost is 0 (e.g. a text-only cycle against an
    IMAGES constraint) can't be converted to cycles and is skipped, not divided
    by zero."""
    profile = ModelRateProfile(
        provider="gemini",
        model="gemini-2-5-flash",
        constraints=(RateConstraint(unit=LimitUnit.IMAGES, window=LimitWindow.MINUTE, limit=5),),
    )
    log = InMemoryUsageLog()
    result = cycles_remaining(profile, log, requests_per_cycle=1, tokens_per_cycle=100)
    assert result == float("inf")
