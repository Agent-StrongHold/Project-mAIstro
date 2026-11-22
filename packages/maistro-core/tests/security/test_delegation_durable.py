"""Durability and parity for host-authorized delegation grants (#845).

The PostgreSQL legs are the ones the coverage-postgres producer runs, so a
`PgDelegationStore` that diverges from its SQLite twin fails there instead of
shipping as an unmeasured line. They skip without `MAISTRO_TEST_PG_DSN` so the
suite stays runnable on a laptop; a skipped leg is untested, not passing.
"""

from __future__ import annotations

import os
from dataclasses import replace
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
    grant_ref: str = "grant-1",
    principal_id: str = "low-agent",
    expires_in: timedelta = timedelta(minutes=5),
    actions: frozenset[str] = frozenset({"read_file"}),
) -> DelegationGrant:
    return DelegationGrant(
        grant_ref=grant_ref,
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
        assert decision.grant_ref == "grant-1"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_sqlite_delegation_store_hides_expired_and_wrong_principal_grants() -> None:
    conn = await aiosqlite.connect(":memory:")
    try:
        store = SqliteDelegationStore(conn)
        await store.ensure_schema()
        await store.store(_grant(grant_ref="expired", expires_in=timedelta(seconds=-1)))
        await store.store(_grant(grant_ref="other", principal_id="someone-else"))

        now = datetime.now(UTC)
        found = await store.list_valid(now=now)
        assert [grant.grant_ref for grant in found] == ["other"]

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
            memory_decision = memory.authorize(request, now=now)
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


@pytest.mark.asyncio
async def test_durable_authority_refuses_a_non_agent_principal() -> None:
    """A human principal cannot delegate even with a matching grant stored."""

    conn = await aiosqlite.connect(":memory:")
    try:
        authority = DurableDelegationAuthority(SqliteDelegationStore(conn))
        await authority.ensure_schema()
        await authority.add_host_grant(_grant())
        request = replace(_request(), principal=Principal(id="owner-1", kind="human"))

        decision = await authority.authorize(request, now=datetime.now(UTC))

        assert decision.allowed is False
        assert decision.reason == "delegation principal must be an agent"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_durable_authority_refuses_an_owner_mismatch() -> None:
    """A request whose owner is not the principal's owner cannot spend a grant."""

    conn = await aiosqlite.connect(":memory:")
    try:
        authority = DurableDelegationAuthority(SqliteDelegationStore(conn))
        await authority.ensure_schema()
        await authority.add_host_grant(_grant())
        request = replace(_request(), owner_id="owner-2")

        decision = await authority.authorize(request, now=datetime.now(UTC))

        assert decision.allowed is False
        assert decision.reason == "delegation owner does not match principal"
    finally:
        await conn.close()


class _StaleStore:
    """A DelegationStore whose TTL read can hand back expired rows.

    Models a store whose filter missed an expiry (clock skew between writer
    and reader, or a filter bug): the decision layer must not inherit that
    blindness.
    """

    def __init__(self, grants: list[DelegationGrant]) -> None:
        self._grants = grants

    async def ensure_schema(self) -> None:
        return None

    async def store(self, grant: DelegationGrant) -> None:
        self._grants.append(grant)

    async def list_valid(self, *, now: datetime) -> list[DelegationGrant]:
        return list(self._grants)


@pytest.mark.asyncio
async def test_durable_authority_rechecks_expiry_after_the_store_read() -> None:
    """Expiry is enforced at the decision layer, not only by the store filter:

    a row the store's TTL read still returned must not authorize, and a valid
    row behind it still answers.
    """

    expired = _grant(grant_ref="expired", expires_in=timedelta(seconds=-5))
    valid = _grant(grant_ref="valid")
    now = datetime.now(UTC)

    # reversed() read order hands the authority the expired row first; the
    # authority must skip it itself and answer from the valid grant.
    authority = DurableDelegationAuthority(_StaleStore([valid, expired]))
    decision = await authority.authorize(_request(), now=now)
    assert decision.allowed is True
    assert decision.grant_ref == "valid"

    only_expired = DurableDelegationAuthority(_StaleStore([expired]))
    refused = await only_expired.authorize(_request(), now=now)
    assert refused.allowed is False
    assert refused.reason == "no host grant matches this delegation"


@pytest.mark.asyncio
async def test_sqlite_store_reads_a_naive_stored_expiry_as_utc() -> None:
    """A naive expiry written through the host API survives the round trip as

    UTC, so the TTL comparison never mixes naive and aware datetimes.
    """

    conn = await aiosqlite.connect(":memory:")
    try:
        store = SqliteDelegationStore(conn)
        await store.ensure_schema()
        naive_expiry = datetime(2030, 1, 1, 12, 0, 0)
        await store.store(replace(_grant(), expires_at=naive_expiry))

        found = await store.list_valid(now=datetime.now(UTC))

        assert [grant.expires_at for grant in found] == [datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)]
    finally:
        await conn.close()


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
    assert [grant.grant_ref for grant in found] == ["grant-1"]


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
