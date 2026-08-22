"""Acceptance coverage for config-driven resource/security floors."""

from __future__ import annotations

import pytest

from maistro.agents.circuit_breaker import circuit_breaker_from_settings
from maistro.config.settings import Settings
from maistro.security.resource_policy import (
    BASELINE_CIRCUIT_FAILURE_THRESHOLD,
    BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S,
    BASELINE_MAX_REQUEST_BODY_BYTES,
    BASELINE_MAX_WEBHOOK_BODY_BYTES,
    BASELINE_RATE_LIMIT_BURST,
    BASELINE_RATE_LIMIT_PER_MINUTE,
)


@pytest.mark.ac("SPEC-082226-2a10/AC-1")
def test_defaults_match_declared_security_baseline() -> None:
    settings = Settings()
    policy = settings.effective_resource_policy()
    assert policy.max_request_body_bytes == BASELINE_MAX_REQUEST_BODY_BYTES
    assert policy.max_webhook_body_bytes == BASELINE_MAX_WEBHOOK_BODY_BYTES
    assert policy.rate_limit_per_minute == BASELINE_RATE_LIMIT_PER_MINUTE
    assert policy.rate_limit_burst == BASELINE_RATE_LIMIT_BURST
    assert policy.circuit_breaker_failure_threshold == BASELINE_CIRCUIT_FAILURE_THRESHOLD
    assert policy.circuit_breaker_recovery_timeout_s == BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S
    assert policy.unsafe_overrides_enabled is False


@pytest.mark.ac("SPEC-082226-2a10/AC-2")
def test_tightening_every_direction_is_allowed() -> None:
    settings = Settings(
        max_request_body_bytes=512_000,
        max_webhook_body_bytes=512_000,
        rate_limit_per_minute=30,
        rate_limit_burst=5,
        circuit_breaker_failure_threshold=3,
        circuit_breaker_recovery_timeout_s=120,
    )
    assert settings.rate_limit_per_minute == 30
    assert settings.circuit_breaker_recovery_timeout_s == 120


@pytest.mark.ac("SPEC-082226-2a10/AC-3")
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_request_body_bytes", BASELINE_MAX_REQUEST_BODY_BYTES + 1),
        ("max_webhook_body_bytes", BASELINE_MAX_WEBHOOK_BODY_BYTES + 1),
        ("rate_limit_per_minute", BASELINE_RATE_LIMIT_PER_MINUTE + 1),
        ("rate_limit_burst", BASELINE_RATE_LIMIT_BURST + 1),
        ("circuit_breaker_failure_threshold", BASELINE_CIRCUIT_FAILURE_THRESHOLD + 1),
        ("circuit_breaker_recovery_timeout_s", BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S - 1),
    ],
)
def test_weakening_a_baseline_is_rejected_without_explicit_override(
    field: str,
    value: int | float,
) -> None:
    with pytest.raises(ValueError, match="ALLOW_UNSAFE_RESOURCE_OVERRIDES"):
        Settings(**{field: value})


@pytest.mark.ac("SPEC-082226-2a10/AC-4")
def test_explicit_unsafe_override_allows_weaker_dev_policy() -> None:
    settings = Settings(
        allow_unsafe_resource_overrides=True,
        rate_limit_per_minute=600,
        circuit_breaker_recovery_timeout_s=5,
    )
    assert settings.rate_limit_per_minute == 600
    assert settings.circuit_breaker_recovery_timeout_s == 5
    assert settings.effective_resource_policy().unsafe_overrides_enabled is True


def test_nonsensical_values_are_rejected_even_in_unsafe_mode() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        Settings(
            allow_unsafe_resource_overrides=True,
            rate_limit_burst=0,
        )


@pytest.mark.ac("SPEC-082226-2a10/AC-5")
def test_circuit_breaker_uses_validated_effective_settings() -> None:
    settings = Settings(
        circuit_breaker_failure_threshold=2,
        circuit_breaker_recovery_timeout_s=90,
    )
    breaker = circuit_breaker_from_settings(settings)
    assert breaker.failure_threshold == 2
    assert breaker.recovery_timeout == 90
