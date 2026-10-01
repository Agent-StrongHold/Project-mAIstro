"""Which campaign store each backend actually yields (SPEC-092626-1831).

Same rule as `test_wiring.py` for Workspaces (#516): the selection is
asserted rather than assumed, because the way a wiring fallback goes wrong is
silently — a deployment that cannot honour durability gets controls that die
with the process, which is exactly what AC-5 forbids for real deployments.
The in-memory fallback must therefore stay loud: the warning is part of the
contract, and a caller that already knows (the container wiring a non-durable
backend deliberately) can pass ``warn=False`` without losing the record type.
"""

from __future__ import annotations

import logging

import aiosqlite

from maistro.workspaces.campaigns.sqlite_store import SqliteCampaignStore
from maistro.workspaces.campaigns.store import InMemoryCampaignStore
from maistro.workspaces.campaigns.wiring import (
    wire_campaign_store,
    wire_in_memory_campaign_store,
)


async def test_a_sqlite_pool_yields_the_durable_store_with_its_schema(tmp_path) -> None:
    conn = await aiosqlite.connect(tmp_path / "campaigns.db")
    try:
        store = await wire_campaign_store(conn)
        assert isinstance(store, SqliteCampaignStore)
        # `ensure_schema` ran: the tables exist without the caller doing anything.
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'campaign%'"
        ) as cursor:
            tables = {row[0] for row in await cursor.fetchall()}
        assert tables == {
            "campaigns",
            "campaign_audit",
            "campaign_controls",
            "campaign_item_records",
            "campaign_parks",
            "campaign_usage",
        }
    finally:
        await conn.close()


async def test_no_pool_yields_the_in_memory_reference_loudly(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="maistro.workspaces.campaigns.wiring"):
        store = wire_in_memory_campaign_store()
    assert isinstance(store, InMemoryCampaignStore)
    assert any("lost on restart" in record.message for record in caplog.records)


async def test_the_in_memory_fallback_can_be_wired_silently(caplog) -> None:
    """``warn=False`` is for callers that already named the cost elsewhere
    (the container wiring a non-durable backend on purpose); the store type —
    and therefore the durability fact — is unchanged."""
    with caplog.at_level(logging.WARNING, logger="maistro.workspaces.campaigns.wiring"):
        store = wire_in_memory_campaign_store(warn=False)
    assert isinstance(store, InMemoryCampaignStore)
    assert not [record for record in caplog.records if "lost on restart" in record.message]
