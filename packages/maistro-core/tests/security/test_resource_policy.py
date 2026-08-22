"""Acceptance coverage for config-driven resource/security floors."""

from __future__ import annotations

import pytest

from maistro.agents.circuit_breaker import circuit_breaker_from_settings
from maistro.config.settings import Settings
from maistro.security.resource_policy import (
    _FLOORS,
    BASELINE_CIRCUIT_FAILURE_THRESHOLD,
    BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S,
    BASELINE_MAX_REQUEST_BODY_BYTES,
    BASELINE_MAX_WEBHOOK_BODY_BYTES,
    BASELINE_RATE_LIMIT_BURST,
    BASELINE_RATE_LIMIT_PER_MINUTE,
    EffectiveResourcePolicy,
    _effective_burst,
)

#: The env vars this policy reads. The suite's own `conftest.py` sets three of
#: them — high rate limits plus the unsafe override that legitimises them — so a
#: test about a *pristine* deployment has to clear them first. Without this the
#: refusal tests pass vacuously: the override is already on, so nothing raises,
#: and the file would report green while proving nothing.
_POLICY_ENV = (
    "ALLOW_UNSAFE_RESOURCE_OVERRIDES",
    "MAX_REQUEST_BODY_BYTES",
    "MAX_WEBHOOK_BODY_BYTES",
    "RATE_LIMIT_PER_MINUTE",
    "RATE_LIMIT_BURST",
    "CIRCUIT_BREAKER_FAILURE_THRESHOLD",
    "CIRCUIT_BREAKER_RECOVERY_TIMEOUT_S",
)


@pytest.fixture(autouse=True)
def _pristine_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Construct `Settings` as a deployment that configured nothing would."""
    for name in _POLICY_ENV:
        monkeypatch.delenv(name, raising=False)


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
    """The override licenses a weaker deployment, not an incoherent one."""
    with pytest.raises(ValueError, match="must be finite and positive"):
        Settings(
            allow_unsafe_resource_overrides=True,
            rate_limit_per_minute=0,
        )


@pytest.mark.ac("SPEC-082226-2a10/AC-7")
def test_zero_burst_is_the_limiters_disable_sentinel_not_a_typo() -> None:
    """`rate_limiter.py` skips the burst window entirely when `burst_limit` is
    0, so 0 admits as much as the per-minute limit rather than nothing. Rejecting
    it as non-positive would refuse a real configuration; treating the literal 0
    as tighter than a baseline of 10 would wave through the opposite of what it
    means. Both readings are wrong, so the check compares what the limiter
    enforces."""
    tighter = Settings(rate_limit_per_minute=2, rate_limit_burst=0)
    assert tighter.rate_limit_burst == 0

    with pytest.raises(ValueError, match="rate_limit_burst>10"):
        Settings(rate_limit_per_minute=60, rate_limit_burst=0)


def test_a_negative_burst_is_still_incoherent() -> None:
    with pytest.raises(ValueError, match="must be finite and positive"):
        Settings(allow_unsafe_resource_overrides=True, rate_limit_burst=-1)


@pytest.mark.ac("SPEC-082226-2a10/AC-5")
def test_circuit_breaker_uses_validated_effective_settings() -> None:
    settings = Settings(
        circuit_breaker_failure_threshold=2,
        circuit_breaker_recovery_timeout_s=90,
    )
    breaker = circuit_breaker_from_settings(settings)
    assert breaker.failure_threshold == 2
    assert breaker.recovery_timeout == 90


def test_the_suite_env_would_hide_these_refusals_without_the_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard the guard. `conftest.py` turns the unsafe override on for the whole
    suite so its high rate limits are legal; with that leaking in, every refusal
    test above would pass by never raising. If this ever stops holding, the
    fixture has become load-bearing for the wrong reason and the refusals need
    re-checking."""
    monkeypatch.setenv("ALLOW_UNSAFE_RESOURCE_OVERRIDES", "true")

    assert Settings(rate_limit_per_minute=BASELINE_RATE_LIMIT_PER_MINUTE + 1)


def test_every_protected_field_has_a_declared_floor() -> None:
    """A limit is enforced because it appears in `_FLOORS`. A field added to
    `EffectiveResourcePolicy` and left out of that tuple would sit in the
    readiness diagnostic and the settings table looking governed while being
    freely weakenable — the exact shape of inert security configuration this
    repository rejects."""
    from dataclasses import fields

    governed = {floor.name for floor in _FLOORS}
    declared = {
        field.name
        for field in fields(EffectiveResourcePolicy)
        if field.name != "unsafe_overrides_enabled"
    }

    assert declared == governed, (
        f"ungoverned: {sorted(declared - governed)}; "
        f"floors with no field: {sorted(governed - declared)}"
    )


# ── the Codex review on #127 ──


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_limit_is_refused_in_every_mode(value: float) -> None:
    """`nan` fails every comparison, including the floor checks — which is how
    it was accepted without the override. It then disables the control it was
    set on: the breaker's `elapsed >= recovery_timeout` is permanently False, so
    a circuit that opens never becomes half-open and the provider is never
    retried. A value that silently disables a control is worse than one that
    refuses to start, so this holds even under the unsafe override."""
    with pytest.raises(ValueError, match="finite"):
        Settings(circuit_breaker_recovery_timeout_s=value)
    with pytest.raises(ValueError, match="finite"):
        Settings(allow_unsafe_resource_overrides=True, circuit_breaker_recovery_timeout_s=value)


def test_nan_would_have_wedged_the_breaker_open() -> None:
    """The reason the check above is worth its line, stated as an assertion
    rather than left in prose."""
    assert not (float("nan") <= 100.0), "any elapsed time fails this comparison"


def test_a_burst_above_the_per_minute_limit_is_capped_not_refused() -> None:
    """The limiter checks the minute window first and returns before the burst
    window is consulted, so `rpm=2, burst=50` admits two requests a second, not
    fifty. Comparing the literal 50 against a baseline of 10 refused a
    configuration strictly tighter than the shipped 60/10 — a false refusal, and
    the kind that teaches an operator the override is routine."""
    settings = Settings(rate_limit_per_minute=2, rate_limit_burst=50)

    assert settings.rate_limit_burst == 50, "stored as configured"
    assert _effective_burst(settings.effective_resource_policy()) == 2, "enforced as capped"


def test_capping_does_not_admit_a_genuinely_looser_burst() -> None:
    """The cap is `min`, not "ignore the burst": with the per-minute limit at
    its baseline, a burst above the baseline is still weaker and still refused."""
    with pytest.raises(ValueError, match="rate_limit_burst>10"):
        Settings(rate_limit_per_minute=60, rate_limit_burst=50)
