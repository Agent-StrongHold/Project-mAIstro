"""Durability and expiry semantics for elevation grants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from maistro.security.sentinel.elevation import ElevationGrant
from maistro.security.sentinel.elevation_durable import SqliteElevationStore


@pytest.mark.asyncio
async def test_sqlite_elevation_grant_survives_new_store_instance() -> None:
    conn = await aiosqlite.connect(":memory:")
    try:
        first = SqliteElevationStore(conn)
        await first.ensure_schema()
        grant = ElevationGrant(
            principal_id="user-1",
            action_class="deploy",
            kind="self_elevation",
            granted_at=datetime.now(UTC),
            ttl_seconds=300,
            signed_by="user-1",
        )
        await first.store(grant)

        restarted = SqliteElevationStore(conn)
        found = await restarted.find_valid("user-1", "deploy", None)
        assert found is not None
        assert found.signed_by == "user-1"
        assert found.action_args_hash is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_sqlite_elevation_store_does_not_return_expired_or_wrong_scope() -> None:
    conn = await aiosqlite.connect(":memory:")
    try:
        store = SqliteElevationStore(conn)
        await store.ensure_schema()
        await store.store(
            ElevationGrant(
                principal_id="user-1",
                action_class="deploy",
                kind="self_elevation",
                granted_at=datetime.now(UTC) - timedelta(seconds=301),
                ttl_seconds=300,
                signed_by="user-1",
            )
        )
        assert await store.find_valid("user-1", "deploy", None) is None
        assert await store.find_valid("user-2", "deploy", None) is None
    finally:
        await conn.close()
