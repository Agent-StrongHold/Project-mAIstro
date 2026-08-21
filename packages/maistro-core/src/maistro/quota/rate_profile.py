"""Unified rate-limit model: arbitrary gating dimensions per model, not a fixed set.

Real providers gate on wildly different combinations — OpenAI's RPM/TPM/RPD/TPD,
Cerebras's RPM+RPH+RPD+TPM+TPH+TPD (six simultaneous windows), Anthropic's
separate input/output token limits, Cohere's per-endpoint-type scoping. A fixed
"4 dimensions" model already fails to represent half the roster, so a
`ModelRateProfile` carries however many `RateConstraint`s actually apply —
zero special-casing which combination is present.

`headroom`/`cycles_remaining` read from a usage source (see `usage_log.py`) to
answer "how much can I still do right now," converting every constraint into a
common currency (cycles) so a request-gated limit and a token-gated limit on
the same model compare directly and combine via `min`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class LimitUnit(StrEnum):
    """What a constraint counts. Split by token direction because providers do:
    Anthropic tracks ITPM/OTPM separately, Gemini adds an image dimension.
    CREDITS_USD is not a `RateConstraint` dimension (no provider gates on a
    rolling-window dollar rate) — it exists so a balance-style verifier
    (OpenRouter's `/api/v1/key`) and the local log can talk about the same
    quantity for reconciliation, without forcing a dollar balance through a
    request/token-shaped constraint."""

    REQUESTS = "requests"
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    TOTAL_TOKENS = "total_tokens"
    IMAGES = "images"
    CREDITS_USD = "credits_usd"


class LimitWindow(StrEnum):
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"


WINDOW_SECONDS: dict[LimitWindow, float] = {
    LimitWindow.SECOND: 1.0,
    LimitWindow.MINUTE: 60.0,
    LimitWindow.HOUR: 3600.0,
    LimitWindow.DAY: 86_400.0,
}


@dataclass(frozen=True)
class RateConstraint:
    """One gating dimension: e.g. RPM=30, or TPD=1_000_000."""

    unit: LimitUnit
    window: LimitWindow
    limit: int

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError(f"RateConstraint.limit must be positive, got {self.limit}")


@dataclass(frozen=True)
class ModelRateProfile:
    """A model's full gating shape plus how usage is scoped/tracked for it.

    `scope_key_fields` names whichever combination of dimensions this
    provider actually pools limits across — OpenAI-style org-wide pooling is
    `("provider",)`; Anthropic-style is `("provider", "model", "api_key")`;
    Cohere's per-endpoint-type scoping is `("provider", "endpoint")`. No
    fixed enum of scope shapes — providers don't agree, so the field list is
    free-form and `scope_key` just joins whatever's named.
    """

    provider: str
    model: str
    constraints: tuple[RateConstraint, ...] = field(default_factory=tuple)
    scope_key_fields: tuple[str, ...] = ("provider", "model")

    def scope_key(self, **values: str) -> str:
        """Build the tracking key for a given call's identifying values.

        Only fields named in `scope_key_fields` matter — e.g. a
        provider-pooled profile ignores `model`/`api_key` even if supplied.
        """
        parts = []
        for f in self.scope_key_fields:
            if f == "provider":
                parts.append(self.provider)
            elif f == "model":
                parts.append(self.model)
            else:
                parts.append(str(values.get(f, "")))
        return ":".join(parts)


@runtime_checkable
class UsageSource(Protocol):
    """Read-side contract `headroom`/`cycles_remaining` need from a usage log."""

    def count_since(self, scope_key: str, seconds_ago: float) -> float:
        """Amount of REQUESTS-unit usage recorded in the last `seconds_ago` seconds."""
        ...

    def tokens_since(self, scope_key: str, seconds_ago: float, unit: LimitUnit) -> float:
        """Amount of the given token/image unit recorded in the last `seconds_ago` seconds."""
        ...


def _used_for(constraint: RateConstraint, scope_key: str, source: UsageSource) -> float:
    window_s = WINDOW_SECONDS[constraint.window]
    if constraint.unit is LimitUnit.REQUESTS:
        return source.count_since(scope_key, window_s)
    return source.tokens_since(scope_key, window_s, constraint.unit)


def headroom(constraint: RateConstraint, scope_key: str, source: UsageSource) -> float:
    """Remaining capacity on this single constraint, right now. Never negative."""
    used = _used_for(constraint, scope_key, source)
    return max(0.0, constraint.limit - used)


_PER_CYCLE_PARAM: dict[LimitUnit, str] = {
    LimitUnit.REQUESTS: "requests_per_cycle",
    LimitUnit.INPUT_TOKENS: "tokens_per_cycle",
    LimitUnit.OUTPUT_TOKENS: "tokens_per_cycle",
    LimitUnit.TOTAL_TOKENS: "tokens_per_cycle",
    LimitUnit.IMAGES: "images_per_cycle",
}


def cycles_remaining(
    profile: ModelRateProfile,
    source: UsageSource,
    *,
    requests_per_cycle: float,
    tokens_per_cycle: float,
    images_per_cycle: float = 0.0,
    scope_values: dict[str, str] | None = None,
) -> float:
    """How many more "cycles" (whatever unit of work the caller defines) this
    model's current headroom supports, across every constraint it carries.

    Each constraint is converted into cycles before comparing, so a
    request-gated limit and a token-gated limit on the same model combine
    correctly via `min` — the model's real ceiling is however constrained it
    is on its *tightest* dimension, not any single one considered alone.
    Images are priced separately from tokens (`images_per_cycle`, default 0)
    — a text-only cycle costs zero images, so an IMAGES constraint on a
    model never wrongly caps a cycle count that doesn't touch it.
    A model with no constraints at all (`profile.constraints` empty) has no
    known ceiling — returns `math.inf`, not zero, since "unconstrained" and
    "exhausted" must never look the same to a caller.
    """
    if not profile.constraints:
        return float("inf")

    per_cycle_values = {
        "requests_per_cycle": requests_per_cycle,
        "tokens_per_cycle": tokens_per_cycle,
        "images_per_cycle": images_per_cycle,
    }
    scope_key = profile.scope_key(**(scope_values or {}))
    caps: list[float] = []
    for c in profile.constraints:
        per_cycle = per_cycle_values[_PER_CYCLE_PARAM[c.unit]]
        if per_cycle <= 0:
            continue
        caps.append(headroom(c, scope_key, source) / per_cycle)

    return min(caps) if caps else float("inf")
