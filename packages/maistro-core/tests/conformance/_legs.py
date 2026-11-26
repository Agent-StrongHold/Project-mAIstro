"""Backend legs for the generalized conformance suites (#892).

A *leg* is one production implementation of a protocol, plus the knowledge
the contract checks must not have: how to build it, how to simulate a
process restart over the same durable state, and how to close it. A check
that only uses ``leg.store()`` and ``await leg.restart()`` runs unchanged on
every leg — that is the whole experiment.

The PostgreSQL leg follows the repo's established honest-skip discipline
(``tests/events/test_durable_store_conformance.py``): it runs against a real
server named by ``MAISTRO_TEST_DATABASE_URL`` and *skips* without one, unless
``MAISTRO_REQUIRE_PG_LEGS`` is set, in which case a missing URL is a
misconfiguration and must fail loudly. A skipped leg is untested, not
passing — which is exactly the kind of gap this suite exists to make loud.

Legs isolate their rows by namespace (every check mints a fresh token into
its ids) rather than by truncating tables, so the suite never depends on
exclusive ownership of the database it points at.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import pytest

#: Environment variable naming the PostgreSQL server the durable leg runs
#: against. Same contract as the events durable-store conformance suite.
PG_URL_ENV = "MAISTRO_TEST_DATABASE_URL"

#: When this is set, an empty ``PG_URL_ENV`` is a CI misconfiguration, not a
#: skip: the leg must run and must not silently go green.
PG_REQUIRE_ENV = "MAISTRO_REQUIRE_PG_LEGS"


def require_postgres_url() -> str:
    """The durable-test server URL, or a skip unless a server is guaranteed."""
    url = os.environ.get(PG_URL_ENV, "")
    if url:
        return url
    if os.environ.get(PG_REQUIRE_ENV):
        msg = (
            f"{PG_REQUIRE_ENV} is set but {PG_URL_ENV} is empty: "
            "the PostgreSQL leg cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip(f"{PG_URL_ENV} is unset; the PostgreSQL leg needs a real server")


@dataclass
class ConformanceLeg:
    """One protocol implementation under test, plus its lifecycle handles."""

    name: str
    """Backend identifier used in node IDs and the xfail matrix."""

    durable: bool
    """Whether state survives ``restart()`` — and must, per the contract."""

    _store: Any = field(repr=False, default=None)
    _restart: Any = field(repr=False, default=None)
    _close: Any = field(repr=False, default=None)

    def store(self) -> Any:
        return self._store

    async def restart(self) -> Any:
        """Reopen the store over the same durable state (a no-op in memory)."""
        if self._restart is None:
            return self._store
        return await self._restart()

    async def aclose(self) -> None:
        if self._close is not None:
            await self._close()


async def _sqlite_invocation_leg(tmp_path: Any) -> ConformanceLeg:
    import aiosqlite

    from maistro.capabilities.invocation_store import SqliteInvocationStore

    path = tmp_path / "conformance-invocations.db"
    conn = await aiosqlite.connect(path)
    store = SqliteInvocationStore(conn)
    await store.ensure_schema()

    async def restart() -> SqliteInvocationStore:
        nonlocal conn
        await conn.close()
        conn = await aiosqlite.connect(path)
        fresh = SqliteInvocationStore(conn)
        await fresh.ensure_schema()
        return fresh

    async def close() -> None:
        await conn.close()

    return ConformanceLeg("sqlite", durable=True, _store=store, _restart=restart, _close=close)


async def _postgres_invocation_leg() -> ConformanceLeg:
    import asyncpg

    from maistro.capabilities.pg_invocation_store import PgInvocationStore

    pool = await asyncpg.create_pool(require_postgres_url(), min_size=1, max_size=2)
    store = PgInvocationStore(pool)
    await store.ensure_schema()
    # Rows are isolated by namespace, so no truncate: the leg must not assume
    # it owns the database (setup-cost evidence for the experiment record).
    return ConformanceLeg("postgres", durable=True, _store=store, _close=pool.close)


async def _sqlite_approval_leg(tmp_path: Any) -> ConformanceLeg:
    import aiosqlite

    from maistro.capabilities.approval_store import SqliteApprovalStore

    path = tmp_path / "conformance-approvals.db"
    conn = await aiosqlite.connect(path)
    store = SqliteApprovalStore(conn)
    await store.ensure_schema()

    async def restart() -> SqliteApprovalStore:
        nonlocal conn
        await conn.close()
        conn = await aiosqlite.connect(path)
        fresh = SqliteApprovalStore(conn)
        await fresh.ensure_schema()
        return fresh

    async def close() -> None:
        await conn.close()

    return ConformanceLeg("sqlite", durable=True, _store=store, _restart=restart, _close=close)


async def _postgres_approval_leg() -> ConformanceLeg:
    import asyncpg

    from maistro.capabilities.approval_store import PgApprovalStore

    pool = await asyncpg.create_pool(require_postgres_url(), min_size=1, max_size=2)
    store = PgApprovalStore(pool)
    await store.ensure_schema()
    return ConformanceLeg("postgres", durable=True, _store=store, _close=pool.close)


def in_memory_invocation_leg() -> ConformanceLeg:
    from maistro.capabilities.invocation import InMemoryInvocationStore

    return ConformanceLeg("memory", durable=False, _store=InMemoryInvocationStore())


def in_memory_approval_leg() -> ConformanceLeg:
    from maistro.capabilities.approval_store import InMemoryApprovalStore

    return ConformanceLeg("memory", durable=False, _store=InMemoryApprovalStore())


async def build_invocation_leg(backend: str, tmp_path: Any) -> ConformanceLeg:
    """Build the InvocationStore leg named by *backend*."""
    if backend == "memory":
        return in_memory_invocation_leg()
    if backend == "sqlite":
        return await _sqlite_invocation_leg(tmp_path)
    if backend == "postgres":
        return await _postgres_invocation_leg()
    raise ValueError(f"unknown InvocationStore backend {backend!r}")


async def build_approval_leg(backend: str, tmp_path: Any) -> ConformanceLeg:
    """Build the ApprovalStore leg named by *backend*."""
    if backend == "memory":
        return in_memory_approval_leg()
    if backend == "sqlite":
        return await _sqlite_approval_leg(tmp_path)
    if backend == "postgres":
        return await _postgres_approval_leg()
    raise ValueError(f"unknown ApprovalStore backend {backend!r}")
