"""Host-owned trust normalization shared by import and provider boundaries.

Foreign metadata can describe a candidate, but it cannot choose an effective
trust tier. Unknown provider labels remain below every known tier when used for
selection; imported definitions start at ``UNVETTED_TRUST_TIER``.
"""

from __future__ import annotations

TRUST_TIERS: tuple[str, ...] = ("t0", "t1", "t2", "t3", "t4")
UNVETTED_TRUST_TIER = "t3"
_UNKNOWN_TIER_RANK = len(TRUST_TIERS) + 1


def is_known_trust_tier(tier: object) -> bool:
    """Whether a tier is a host-recognized canonical value."""
    return isinstance(tier, str) and tier.strip().lower() in TRUST_TIERS


def trust_rank(tier: object) -> int:
    """Return a total-order rank; smaller is more trusted.

    Do not parse arbitrary strings as numeric tiers. A provider-controlled
    value such as ``""`` or ``"t-1"`` must never sort ahead of a known tier.
    """
    if isinstance(tier, str):
        normalized = tier.strip().lower()
        try:
            return TRUST_TIERS.index(normalized)
        except ValueError:
            pass
    return _UNKNOWN_TIER_RANK


def imported_trust_tier(_declared: object) -> str:
    """Return the effective tier for foreign imported metadata.

    The argument is intentionally ignored: declarations are metadata only and
    promotion belongs to a separate authenticated host workflow.
    """
    return UNVETTED_TRUST_TIER


__all__ = [
    "TRUST_TIERS",
    "UNVETTED_TRUST_TIER",
    "imported_trust_tier",
    "is_known_trust_tier",
    "trust_rank",
]
