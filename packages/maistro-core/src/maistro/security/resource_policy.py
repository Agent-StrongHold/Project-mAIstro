"""Deployment policy for resource limits that also protect security boundaries.

The baseline values are the strongest values the engine historically shipped.
Operators may tighten them freely. Weakening one requires an explicit unsafe
resource override so a production deployment cannot silently increase exposure
by changing what looks like an ordinary tuning knob.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

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
        return {field.name: getattr(self, field.name) for field in fields(self)}


@dataclass(frozen=True)
class _Floor:
    """One protected limit, its baseline, and which way tightening runs."""

    name: str
    baseline: int | float
    #: True when a *smaller* value is the safer one, which is the common case:
    #: a smaller body cap, rate limit, burst or failure threshold each admits
    #: less. Recovery timeout inverts — a shorter cooldown reopens the circuit
    #: to a failing provider sooner — so it is the one entry set False.
    smaller_is_tighter: bool
    #: Whether zero is a coherent configuration rather than a typo. Only
    #: `rate_limit_burst` sets this: `rate_limiter.py` reads 0 as "run no
    #: separate burst check", not "allow nothing through". Everywhere else a
    #: zero would mean a limit that admits nothing, which no deployment wants
    #: and no override should license.
    zero_is_meaningful: bool = False

    def incoherent(self, value: int | float) -> bool:
        return value < 0 if self.zero_is_meaningful else value <= 0

    def weakens(self, value: int | float) -> bool:
        return value > self.baseline if self.smaller_is_tighter else value < self.baseline

    def describe(self, value: int | float) -> str:
        direction = ">" if self.smaller_is_tighter else "<"
        return f"{self.name}{direction}{self.baseline:g}"


def _effective_burst(policy: EffectiveResourcePolicy) -> int:
    """What the limiter's burst check actually enforces.

    `RateLimiter` skips the burst window entirely when `burst_limit` is 0, so a
    burst of 0 does not admit zero requests — it admits as many as the per-minute
    limit does. Comparing the literal 0 against a baseline of 10 would call that
    *tighter* than the shipped default, when it is the opposite: the burst
    throttle is off. Comparing the value the limiter enforces means an operator
    who writes `RATE_LIMIT_PER_MINUTE=2` with no burst throttle is accepted
    (2 is tighter than 10), while one who writes 6000 with no burst throttle is
    refused — which is the true reading of both.
    """
    if policy.rate_limit_burst == 0:
        return policy.rate_limit_per_minute
    return policy.rate_limit_burst


#: Every protected limit, in the order an error message should list them. The
#: table is the whole check: a knob is enforced because it is listed here, so a
#: field added to `EffectiveResourcePolicy` and left out of this tuple would be
#: freely weakenable while looking governed. `test_resource_policy.py` walks the
#: dataclass against this tuple to make that omission a failing test.
_FLOORS: tuple[_Floor, ...] = (
    _Floor("max_request_body_bytes", BASELINE_MAX_REQUEST_BODY_BYTES, True),
    _Floor("max_webhook_body_bytes", BASELINE_MAX_WEBHOOK_BODY_BYTES, True),
    _Floor("rate_limit_per_minute", BASELINE_RATE_LIMIT_PER_MINUTE, True),
    _Floor("rate_limit_burst", BASELINE_RATE_LIMIT_BURST, True, zero_is_meaningful=True),
    _Floor("circuit_breaker_failure_threshold", BASELINE_CIRCUIT_FAILURE_THRESHOLD, True),
    _Floor("circuit_breaker_recovery_timeout_s", BASELINE_CIRCUIT_RECOVERY_TIMEOUT_S, False),
)

_FLOOR_BY_NAME: dict[str, _Floor] = {floor.name: floor for floor in _FLOORS}


def validate_resource_policy(policy: EffectiveResourcePolicy) -> EffectiveResourcePolicy:
    """Reject nonsensical values and silent weakening of shipped protections."""
    configured: dict[str, int | float] = {
        floor.name: getattr(policy, floor.name) for floor in _FLOORS
    }

    invalid = sorted(
        name for name, floor in _FLOOR_BY_NAME.items() if floor.incoherent(configured[name])
    )
    if invalid:
        raise ValueError(f"resource/security limits must be positive: {', '.join(invalid)}")

    # Checked after the coherence rule, deliberately: the override licenses a
    # weaker deployment, not an incoherent one. A rate limit of zero is a
    # mistake in every mode.
    if policy.unsafe_overrides_enabled:
        return policy

    # Compare what the runtime enforces, not what was typed — see
    # `_effective_burst` for the one place those differ.
    enforced = {**configured, "rate_limit_burst": _effective_burst(policy)}

    weakened = [
        floor.describe(enforced[floor.name])
        for floor in _FLOORS
        if floor.weakens(enforced[floor.name])
    ]
    if weakened:
        raise ValueError(
            "resource/security configuration weakens the declared baseline "
            f"({', '.join(weakened)}); set ALLOW_UNSAFE_RESOURCE_OVERRIDES=true "
            "only for an explicit unsafe/dev deployment"
        )
    return policy
