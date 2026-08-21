"""Default DAG seeds — one or more per use_case.

Hive seeds these into `stores.dags` on first boot per active project
use_case. Each seed function returns a fresh dict (no shared mutable
state) so callers can mutate without surprising other tests.

Seeds are domain-neutral substrate citizens: they compose registered
node kinds + the standard validator into a valid DAG. They are the
proof-points that an end-to-end use case can be expressed by the
substrate without escaping to bespoke route code.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .daily_status import daily_status_seed

# Registry: use_case → list of seed factories.
SEEDS_BY_USE_CASE: dict[str, list[Callable[[], dict[str, Any]]]] = {
    "pm_fleet": [daily_status_seed],
    # canvas_creative + engineering_rfc + others get their default seeds
    # in later phases.
}


def list_seeds_for(use_case: str) -> list[Callable[[], dict[str, Any]]]:
    """Return the seed factories for a given use_case (empty list if none)."""
    return list(SEEDS_BY_USE_CASE.get(use_case, ()))


__all__ = ["SEEDS_BY_USE_CASE", "daily_status_seed", "list_seeds_for"]
