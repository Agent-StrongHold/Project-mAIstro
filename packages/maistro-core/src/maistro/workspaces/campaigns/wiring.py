"""Selecting the campaign store the deployment actually has.

Follows the same rule as `maistro.workspaces.wiring`: the store rides the
backend the deployment already selected, and a deployment that cannot honour
durability is told so loudly instead of silently losing operator controls on
restart. PostgreSQL campaign tables are not part of the schema yet — a
Postgres deployment gets the in-memory store and a warning naming the cost,
so #804 does not quietly build on controls that die with the process.
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.workspaces.campaigns.store import CampaignStore, InMemoryCampaignStore

logger = logging.getLogger(__name__)


async def wire_campaign_store(db_pool: Any) -> CampaignStore:
    """Wire the campaign store over the SQLite database pool.

    ``db_pool`` is the same aiosqlite pool the rest of the SQLite backend
    uses, so campaign records live beside the Workspaces and Projects they
    scope, and a restart re-reads the same controls (AC-5)."""
    from maistro.workspaces.campaigns.sqlite_store import SqliteCampaignStore

    store = SqliteCampaignStore(db_pool)
    await store.ensure_schema()
    return store


def wire_in_memory_campaign_store(*, warn: bool = True) -> CampaignStore:
    """The non-durable fallback. ``warn`` keeps the loss loud: pin-next,
    pause, exclude and human-only written through this store do not survive
    a restart, which is exactly what AC-5 forbids for real deployments."""
    if warn:
        logger.warning(
            "No SQLite database pool is available, so campaign records are in-process "
            "and operator controls (pin-next, pause, exclude, human-only) are lost on "
            "restart. Run with a sqlite database URL so campaigns persist (#103)."
        )
    return InMemoryCampaignStore()
