"""Durability and expiry semantics for elevation grants.

The PostgreSQL legs of this suite are the ones the coverage-postgres producer
runs (quality.yml names this file explicitly), so a `PgElevationStore` that
diverges from its SQLite twin fails there instead of shipping as an
unmeasured line. They skip without `MAISTRO_TEST_PG_DSN` so the suite stays
runnable on a laptop; a skipped leg is untested, not passing.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from maistro.security.sentinel.elevation import ElevationGrant
from maistro.security.sentinel.elevation_durable import SqliteElevationStore


def _grant(
    *,
    granted_at: datetime | None = None,
    principal_id: str = "user-1",
    action_class: str = "deploy",
    action_args_hash: str | None = None,
) -> ElevationGrant:
    return ElevationGrant(
        principal_id=principal_id,
        action_class=action_class,
        kind="self_elevation",
        granted_at=granted_at if granted_at is not None else datetime.now(UTC),
        ttl_seconds=300,
        signed_by=principal_id,
        action_args_hash=action_args_hash,
    )


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


@pytest.mark.asyncio
async def test_sqlite_store_reads_a_legacy_row_written_without_tz_offset() -> None:
    """A grant persisted by an older build carries no UTC offset.

    `granted_at` is stored as ISO text, so a row written before timestamps
    were offset-aware comes back naive. Expiry arithmetic against a naive
    `datetime.now(UTC)` would raise rather than expire, so the read path
    normalizes to UTC — proven here against the exact storage shape.
    """

    conn = await aiosqlite.connect(":memory:")
    try:
        store = SqliteElevationStore(conn)
        await store.ensure_schema()
        still_valid = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=10)
        await conn.execute(
            "INSERT INTO elevation_grants "
            "(principal_id, action_class, kind, granted_at, ttl_seconds, signed_by, action_args_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("user-1", "deploy", "self_elevation", still_valid.isoformat(), 300, "user-1", None),
        )
        await conn.commit()

        found = await store.find_valid("user-1", "deploy", None)
        assert found is not None
        assert found.granted_at.tzinfo is not None
    finally:
        await conn.close()


def _skip_without_postgres(pg_pool: object) -> None:
    """Skip on a laptop; refuse to skip where a server is guaranteed.

    Same discipline as test_strike_tracker_conformance: the coverage-postgres
    producer sets `MAISTRO_REQUIRE_PG_LEGS`, so a missing DSN there is a
    misconfigured job, and skipping would hide the PG legs it exists to run.
    """
    if pg_pool is not None:
        return
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but no PostgreSQL DSN reached the "
            "pg_pool fixture: the PostgreSQL leg cannot run and must not be "
            "silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_PG_DSN is unset; the PostgreSQL leg needs a real server")


@pytest.mark.asyncio
async def test_postgres_elevation_grant_survives_a_new_store(pg_pool) -> None:
    """The restart contract on the canonical backend: a fresh instance —

    nothing in-process — still finds the grant a previous process stored.
    """
    from maistro.security.sentinel.elevation_durable import PgElevationStore

    _skip_without_postgres(pg_pool)
    await PgElevationStore(pg_pool).store(_grant(action_args_hash="args-hash"))

    found = await PgElevationStore(pg_pool).find_valid("user-1", "deploy", None)
    assert found is not None
    assert found.signed_by == "user-1"
    assert found.kind == "self_elevation"
    assert found.action_args_hash == "args-hash"


@pytest.mark.asyncio
async def test_postgres_elevation_store_does_not_return_expired_or_wrong_scope(
    pg_pool,
) -> None:
    from maistro.security.sentinel.elevation_durable import PgElevationStore

    _skip_without_postgres(pg_pool)
    store = PgElevationStore(pg_pool)
    expired = datetime.now(UTC) - timedelta(seconds=301)
    await store.store(_grant(granted_at=expired))

    assert await store.find_valid("user-1", "deploy", None) is None
    await store.store(_grant(principal_id="user-2"))
    assert await store.find_valid("user-1", "deploy", None) is None


@pytest.mark.asyncio
async def test_build_elevation_store_prefers_the_canonical_pg_pool(pg_pool) -> None:
    """Backend selection follows the container's own pool (#72, #1172):

    a supplied pg_pool means PostgreSQL even when a SQLite pool also exists.
    """
    from maistro.security.sentinel.elevation_durable import PgElevationStore, build_elevation_store

    _skip_without_postgres(pg_pool)
    store = await build_elevation_store(pg_pool=pg_pool, db_pool=object())
    assert isinstance(store, PgElevationStore)
