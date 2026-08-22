"""Deployment policy for resource limits that also protect security boundaries.

The baseline values are the strongest values the engine historically shipped.
Operators may tighten them freely. Weakening one requires an explicit unsafe
resource override so a production deployment cannot silently increase exposure
by changing what looks like an ordinary tuning knob.
"""

from __future__ import annotations

from dataclasses import dataclass

BASELINE_MAX_REQUEST_BODY_BYTES = 1_048_576
BASELINE_MAX_WEBHOOK_BODY_BYTES = 1_048_576
BASELINE_RATE_LIMIT_PER_MINUTE = 60
BASELINE_RATE_LIMIT_BURST = 10
BASELINE_CIRCUIT_FAILURE_THRESHOLD = 5
BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class EffectiveResourcePolicy:
    """Resolved resource/security values used by a deployment."""

    max_request_body_bytes: int
    max_webhook_body_bytes: int
    rate_limit_per_minute: int
    rate_limit_burst: int
    circuit_breaker_failure_threshold: int
    circuit_breaker_recovery_timeout_s: float
    unsafe_overrides_enabled: bool = False

    def as_dict(self) -> dict[str, int | float | bool]:
        return {
            "max_request_body_bytes": self.max_request_body_bytes,
            "max_webhook_body_bytes": self.max_webhook_body_bytes,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "rate_limit_burst": self.rate_limit_burst,
            "circuit_breaker_failure_threshold": self.circuit_breaker_failure_threshold,
            "circuit_breaker_recovery_timeout_s": self.circuit_breaker_recovery_timeout_s,
            "unsafe_overrides_enabled": self.unsafe_overrides_enabled,
        }


def validate_resource_policy(policy: EffectiveResourcePolicy) -> EffectiveResourcePolicy:
    """Reject nonsensical values and silent weakening of shipped protections."""
    positive: dict[str, int | float] = {
        "max_request_body_bytes": policy.max_request_body_bytes,
        "max_webhook_body_bytes": policy.max_webhook_body_bytes,
        "rate_limit_per_minute": policy.rate_limit_per_minute,
        "rate_limit_burst": policy.rate_limit_burst,
        "circuit_breaker_failure_threshold": policy.circuit_breaker_failure_threshold,
        "circuit_breaker_recovery_timeout_s": policy.circuit_breaker_recovery_timeout_s,
    }
    invalid = [name for name, value in positive.items() if value <= 0]
    if invalid:
        raise ValueError(f"resource/security limits must be positive: {', '.join(sorted(invalid))}")

    if policy.unsafe_overrides_enabled:
        return policy

    weakened: list[str] = []
    if policy.max_request_body_bytes > BASELINE_MAX_REQUEST_BODY_BYTES:
        weakened.append(
            f"max_request_body_bytes>{BASELINE_MAX_REQUEST_BODY_BYTES}"
        )
    if policy.max_webhook_body_bytes > BASELINE_MAX_WEBHOOK_BODY_BYTES:
        weakened.append(
            f"max_webhook_body_bytes>{BASELINE_MAX_WEBHOOK_BODY_BYTES}"
        )
    if policy.rate_limit_per_minute > BASELINE_RATE_LIMIT_PER_MINUTE:
        weakened.append(f"rate_limit_per_minute>{BASELINE_RATE_LIMIT_PER_MINUTE}")
    if policy.rate_limit_burst > BASELINE_RATE_LIMIT_BURST:
        weakened.append(f"rate_limit_burst>{BASELINE_RATE_LIMIT_BURST}")
    if policy.circuit_breaker_failure_threshold > BASELINE_CIRCUIT_FAILURE_THRESHOLD:
        weakened.append(
            "circuit_breaker_failure_threshold>"
            f"{BASELINE_CIRCUIT_FAILURE_THRESHOLD}"
        )
    if policy.circuit_breaker_recovery_timeout_s < BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S:
        weakened.append(
            "circuit_breaker_recovery_timeout_s<"
            f"{BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S:g}"
        )

    if weakened:
        joined = ", ".join(weakened)
        raise ValueError(
            "resource/security configuration weakens the declared baseline "
            f"({joined}); set ALLOW_UNSAFE_RESOURCE_OVERRIDES=true only for an "
            "explicit unsafe/dev deployment"
        )
    return policy
