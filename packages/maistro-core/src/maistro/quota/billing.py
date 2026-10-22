"""Quota billing: cycle key generation and daily budget normalization.

`cycle_key` is the bucketing half consumed by the quota trackers (#718);
`daily_budget` here is a retained compatibility alias that imports the
authoritative implementation in `maistro.types.model` (#1205) — the router's
scarcity scorer owns the production caller. This module must not grow a second
copy of the budget arithmetic: one formula, one vocabulary, and unknown
billing cycles fail explicitly instead of silently meaning monthly.
"""

from __future__ import annotations

from datetime import UTC, datetime

from maistro.types.model import normalized_daily_budget as _canonical_daily_budget
from maistro.types.model import validate_billing_cycle


def cycle_key(billing_cycle: str) -> str:
    """Bucket key for the current instant under `billing_cycle`.

    Raises `UnknownBillingCycleError` for values outside the supported
    vocabulary — the tracker must never file usage under a bucket that was
    derived by silently assuming an unknown cycle meant monthly (#1205).
    """
    validate_billing_cycle(billing_cycle)
    now = datetime.now(UTC)
    if billing_cycle == "daily":
        return now.strftime("%Y-%m-%d")
    return now.strftime("%Y-%m")


def daily_budget(free_tokens: int, billing_cycle: str) -> float:
    """Compatibility alias over `maistro.types.model.normalized_daily_budget`.

    Retained (rather than deleted) so downstream imports keep resolving, but
    it contributes no arithmetic of its own — the single formula lives in
    `maistro.types.model` and is shared with `router.scarcity` (#1205).
    """
    return _canonical_daily_budget(free_tokens, billing_cycle)
