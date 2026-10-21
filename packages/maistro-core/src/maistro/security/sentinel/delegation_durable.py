"""Durable delegation-authority stores for the supported relational backends.

The in-memory authority in :mod:`maistro.security.sentinel.delegation` is the
test and ephemeral seam. A deployment whose host policy must outlive a restart
supplies one of these stores instead, through the same
:func:`build_delegation_authority` the container calls. The decision logic
itself lives in the base module, so both authorities resolve identically.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol

from maistro.security.sentinel.delegation import (
    DelegationAuthority,
    DelegationDecision,
    DelegationGrant,
    DelegationRequest,
)
from maistro.security.sentinel.delegation import (
    _matches as _grant_matches,
)
from maistro.sqlite_schema import serialized_schema_upgrade

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS delegation_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grant_ref TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    delegating_agent_id TEXT NOT NULL,
    target_agent_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    invocation_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    action TEXT NOT NULL,
    actions TEXT NOT NULL,
    artifact TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    granted_by TEXT NOT NULL,
    provenance TEXT NOT NULL
)
"""

POSTGRES_DELEGATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS delegation_grants (
    id SERIAL PRIMARY KEY,
    grant_ref TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    delegating_agent_id TEXT NOT NULL,
    target_agent_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    invocation_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    action TEXT NOT NULL,
    actions TEXT NOT NULL,
    artifact TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    granted_by TEXT NOT NULL,
    provenance TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_delegation_grants_lookup
    ON delegation_grants (principal_id, expires_at);
"""


class DelegationStore(Protocol):
    """Persists host-created delegation grants."""

    async def ensure_schema(self) -> None:
        """Create the backing table before the first host grant."""
        ...

    async def store(self, grant: DelegationGrant) -> None:
        """Persist a host-created grant."""
        ...

    async def list_valid(self, *, now: datetime) -> list[DelegationGrant]:
        """Return unexpired grants in creation order (oldest first)."""
        ...


async def ensure_delegation_schema(pool: Any) -> None:
    """Bootstrap delegation persistence on a standalone pool.

    Managed deployments also apply the Alembic revision; ``CREATE TABLE IF NOT
    EXISTS`` keeps the two from forking the delegation key.
    """

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(POSTGRES_DELEGATION_SCHEMA)


class SqliteDelegationStore:
    """SQLite delegation store; grants survive a process restart."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        async with serialized_schema_upgrade(self._conn):
            await self._conn.execute(_SQLITE_SCHEMA)

    async def store(self, grant: DelegationGrant) -> None:
        await self._conn.execute(
            "INSERT INTO delegation_grants "
            "(grant_ref, principal_id, owner_id, delegating_agent_id, target_agent_id, "
            "goal_id, run_id, invocation_id, scope, action, actions, artifact, "
            "expires_at, granted_by, provenance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                grant.grant_ref,
                grant.principal_id,
                grant.owner_id,
                grant.delegating_agent_id,
                grant.target_agent_id,
                grant.goal_id,
                grant.run_id,
                grant.invocation_id,
                grant.scope,
                grant.action,
                json.dumps(sorted(grant.actions)),
                grant.artifact,
                grant.expires_at.isoformat(),
                grant.granted_by,
                grant.provenance,
            ),
        )
        await self._conn.commit()

    async def list_valid(self, *, now: datetime) -> list[DelegationGrant]:
        cursor = await self._conn.execute(
            "SELECT grant_ref, principal_id, owner_id, delegating_agent_id, target_agent_id, "
            "goal_id, run_id, invocation_id, scope, action, actions, artifact, "
            "expires_at, granted_by, provenance FROM delegation_grants ORDER BY id ASC"
        )
        grants = [_grant_from_row(row) for row in await cursor.fetchall()]
        return [grant for grant in grants if now < grant.expires_at]


class PgDelegationStore:
    """PostgreSQL delegation store using the container's canonical pool."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        await ensure_delegation_schema(self._pool)

    async def store(self, grant: DelegationGrant) -> None:
        await self._pool.execute(
            "INSERT INTO delegation_grants "
            "(grant_ref, principal_id, owner_id, delegating_agent_id, target_agent_id, "
            "goal_id, run_id, invocation_id, scope, action, actions, artifact, "
            "expires_at, granted_by, provenance) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)",
            grant.grant_ref,
            grant.principal_id,
            grant.owner_id,
            grant.delegating_agent_id,
            grant.target_agent_id,
            grant.goal_id,
            grant.run_id,
            grant.invocation_id,
            grant.scope,
            grant.action,
            json.dumps(sorted(grant.actions)),
            grant.artifact,
            grant.expires_at,
            grant.granted_by,
            grant.provenance,
        )

    async def list_valid(self, *, now: datetime) -> list[DelegationGrant]:
        rows = await self._pool.fetch(
            "SELECT grant_ref, principal_id, owner_id, delegating_agent_id, target_agent_id, "
            "goal_id, run_id, invocation_id, scope, action, actions, artifact, "
            "expires_at, granted_by, provenance FROM delegation_grants "
            "WHERE expires_at > $1 ORDER BY id ASC",
            now,
        )
        return [_grant_from_row(row) for row in rows]


class DurableDelegationAuthority:
    """A :class:`DelegationAuthority` backed by durable host policy.

    ``add_host_grant`` is async because the write goes to the canonical
    backend; the decision path only reads.
    """

    def __init__(self, store: DelegationStore) -> None:
        self._store = store

    async def ensure_schema(self) -> None:
        await self._store.ensure_schema()

    async def add_host_grant(self, grant: DelegationGrant) -> None:
        await self._store.store(grant)

    async def authorize(self, request: DelegationRequest, *, now: datetime) -> DelegationDecision:
        if request.principal.kind != "agent":
            return DelegationDecision(False, reason="delegation principal must be an agent")
        if request.principal.owner != request.owner_id:
            return DelegationDecision(False, reason="delegation owner does not match principal")
        for grant in reversed(await self._store.list_valid(now=now)):
            if now >= grant.expires_at:
                continue
            if not _grant_matches(grant, request):
                continue
            return DelegationDecision(
                True,
                effective_actions=frozenset(request.requested_actions & grant.actions),
                grant_ref=grant.grant_ref,
                expires_at=grant.expires_at,
                granted_by=grant.granted_by,
                provenance=grant.provenance,
            )
        return DelegationDecision(False, reason="no host grant matches this delegation")


def _grant_from_row(row: Any) -> DelegationGrant:
    """Rebuild a grant from a SQLite row or a PG record."""
    values = tuple(row)
    expires_at = values[12]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return DelegationGrant(
        grant_ref=str(values[0]),
        principal_id=str(values[1]),
        owner_id=str(values[2]),
        delegating_agent_id=str(values[3]),
        target_agent_id=str(values[4]),
        goal_id=str(values[5]),
        run_id=str(values[6]),
        invocation_id=str(values[7]),
        scope=str(values[8]),
        action=str(values[9]),
        actions=frozenset(json.loads(values[10])),
        artifact=str(values[11]),
        expires_at=expires_at,
        granted_by=str(values[13]),
        provenance=str(values[14]),
    )


async def build_delegation_authority(*, pg_pool: Any, db_pool: Any) -> Any:
    """Select delegation persistence from the same backend as the other stores."""
    if pg_pool is not None:
        pg_store: Any = PgDelegationStore(pg_pool)
        # The canonical backend's table is created by the store's idempotent
        # DDL, exactly as `_wire_audit_log` does for the audit store: a
        # deployment that has not applied a delegation migration still gets a
        # usable authority, and the first host grant does not raise
        # "relation does not exist" (#845).
        await pg_store.ensure_schema()
        return DurableDelegationAuthority(pg_store)
    if db_pool is not None:
        sqlite_store: Any = SqliteDelegationStore(db_pool)
        await sqlite_store.ensure_schema()
        return DurableDelegationAuthority(sqlite_store)
    from maistro.security.sentinel.delegation import InMemoryDelegationAuthority

    return InMemoryDelegationAuthority()


__all__ = [
    "POSTGRES_DELEGATION_SCHEMA",
    "DelegationStore",
    "DurableDelegationAuthority",
    "PgDelegationStore",
    "SqliteDelegationStore",
    "build_delegation_authority",
    "ensure_delegation_schema",
]
