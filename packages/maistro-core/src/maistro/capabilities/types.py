"""Capability framework types: fallback policy, health, slot spec, unavailable result."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FallbackPolicy(StrEnum):
    """What a slot does when no enabled+healthy provider resolves."""

    BASELINE = "baseline"  # a core-only baseline provider fills the slot
    SAFE_NOOP = "safe_noop"  # return a typed Unavailable; never raise
    HARD_REQUIRED = "hard_required"  # boot fails if unfilled


@dataclass(frozen=True)
class ProviderHealth:
    """Result of a provider healthcheck."""

    healthy: bool
    detail: str = ""


@dataclass(frozen=True)
class SlotSpec:
    """Static declaration of a capability slot."""

    name: str
    fallback_policy: FallbackPolicy
    baseline_provider: str | None = None  # provider name; required when policy is BASELINE


@dataclass(frozen=True)
class Unavailable:
    """Typed 'capability unavailable' result for SAFE_NOOP slots."""

    slot: str
    reason: str = "capability unavailable"
