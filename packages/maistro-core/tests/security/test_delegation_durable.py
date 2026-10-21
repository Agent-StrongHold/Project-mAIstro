"""Durability and parity for host-authorized delegation grants (#845).

The PostgreSQL legs are the ones the coverage-postgres producer runs, so a
`PgDelegationStore` that diverges from its SQLite twin fails there instead of
shipping as an unmeasured line. They skip without `MAISTRO_TEST_PG_DSN` so the
suite stays runnable on a laptop; a skipped leg is untested, not passing.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite
import pytest

from maistro.security.sentinel.authz_types import Principal
from maistro.security.sentinel.delegation import DelegationGrant, DelegationRequest
from maistro.security.sentinel.delegation_durable import (
    DurableDelegationAuthority,
    SqliteDelegationStore,
    build_delegation_authority,
)

_ARTIFACT = "delegate this exact task"


def _grant(
    *,
    grant_id: str = "grant-1",
    principal_id: str = "low-agent",
    expires_in: timedelta = timedelta(minutes=5),
    actions: frozenset[str] = frozenset({"read_file"}),
) -> DelegationGrant:
    return DelegationGrant(
        grant_id=grant_id,
        principal_id=principal_id,
        owner_id="owner-1",
        delegating_agent_id="low-agent",
        target_agent_id="writer",
        goal_id="goal-1",
        run_id="run-1",
        invocation_id="inv-1",
        scope="project-1",
        action="agent.delegate",
        actions=actions,
        artifact=_ARTIFACT,
        expires_at=datetime.now(UTC) + expires_in,
        granted_by="host-policy",
        provenance="human-approval:approval-1",
    )


def _request(
    *, actions: frozenset[str] = frozenset({"read_file", "write_file"})
) -> DelegationRequest:
    principal = Principal(id="low-agent", kind="agent", owner="owner-1", scopes=("project-1",))
    return DelegationRequest(
        principal=principal,
        owner_id="owner-1",
        delegating_agent_id="low-agent",
        target_agent_id="writer",
        goal_id="goal-1",
        run_id="run-1",
        invocation_id="inv-1",
        scope="project-1",
        action="agent.delegate",
        requested_actions=actions,
        artifact=_ARTIFACT,
        requested_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_sqlite_delegation_grant_survives_a_new_authority_instance(tmp_path: Path) -> None:
    """The restart contract: a fresh authority finds the host grant a previous

    process stored. Nothing in-process carries the decision.
    """
    db = tmp_path / "delegation.sqlite"
    conn = await aiosqlite.connect(db)
    try:
        first = DurableDelegationAuthority(SqliteDelegationStore(conn))
        await first.ensure_schema()
        await first.add_host_grant(_grant())

        restarted = DurableDelegationAuthority(SqliteDelegationStore(conn))
        decision = await restarted.authorize(_request(), now=datetime.now(UTC))
        assert decision.allowed is True
        assert decision.effective_actions == frozenset({"read_file"})
        assert decision.grant_id == "grant-1"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_sqlite_delegation_store_hides_expired_and_wrong_principal_grants() -> None:
    conn = await aiosqlite.connect(":memory:")
    try:
        store = SqliteDelegationStore(conn)
        await store.ensure_schema()
        await store.store(_grant(grant_id="expired", expires_in=timedelta(seconds=-1)))
        await store.store(_grant(grant_id="other", principal_id="someone-else"))

        now = datetime.now(UTC)
        found = await store.list_valid(now=now)
        assert [grant.grant_id for grant in found] == ["other"]

        authority = DurableDelegationAuthority(store)
        assert (await authority.authorize(_request(), now=now)).allowed is False
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_durable_and_in_memory_authorities_decide_identically() -> None:
    from maistro.security.sentinel.delegation import InMemoryDelegationAuthority

    conn = await aiosqlite.connect(":memory:")
    try:
        durable = DurableDelegationAuthority(SqliteDelegationStore(conn))
        await durable.ensure_schema()
        await durable.add_host_grant(_grant())
        memory = InMemoryDelegationAuthority([_grant()])

        now = datetime.now(UTC)
        for request in (
            _request(),
            _request(actions=frozenset({"write_file"})),
        ):
            durable_decision = await durable.authorize(request, now=now)
            memory_decision = await memory.authorize(request, now=now)
            assert durable_decision.allowed == memory_decision.allowed
            assert durable_decision.effective_actions == memory_decision.effective_actions
            assert durable_decision.reason == memory_decision.reason
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_build_delegation_authority_falls_back_to_memory_without_a_pool() -> None:
    from maistro.security.sentinel.delegation import InMemoryDelegationAuthority

    authority = await build_delegation_authority(pg_pool=None, db_pool=None)
    assert isinstance(authority, InMemoryDelegationAuthority)


def _skip_without_postgres(pg_pool: object) -> None:
    """Skip on a laptop; refuse to skip where a server is guaranteed."""
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
async def test_postgres_delegation_grant_survives_a_new_authority(pg_pool) -> None:
    """The restart contract on the canonical backend."""
    from maistro.security.sentinel.delegation_durable import PgDelegationStore

    _skip_without_postgres(pg_pool)
    await PgDelegationStore(pg_pool).ensure_schema()
    await PgDelegationStore(pg_pool).store(_grant())

    found = await PgDelegationStore(pg_pool).list_valid(now=datetime.now(UTC))
    assert [grant.grant_id for grant in found] == ["grant-1"]


@pytest.mark.asyncio
async def test_build_delegation_authority_prefers_the_canonical_pg_pool(pg_pool) -> None:
    """Backend selection follows the container's own pool, like elevation."""
    from maistro.security.sentinel.delegation_durable import PgDelegationStore

    _skip_without_postgres(pg_pool)
    authority = await build_delegation_authority(pg_pool=pg_pool, db_pool=object())
    assert isinstance(authority, DurableDelegationAuthority)
    assert isinstance(authority._store, PgDelegationStore)
    # The canonical table exists before any host grant is written, so the first
    # delegation does not raise "relation delegation_grants does not exist".
    assert await authority._store.list_valid(now=datetime.now(UTC)) == []
