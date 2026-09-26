"""Shared transaction discipline for SQLite schema initialization."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any
from weakref import WeakKeyDictionary

_CONNECTION_LOCKS: WeakKeyDictionary[Any, asyncio.Lock] = WeakKeyDictionary()
_CONNECTION_LOCKS_GUARD = threading.Lock()
_SCHEMA_BUSY_TIMEOUT_MS = 60_000


def _connection_lock(conn: Any) -> asyncio.Lock:
    """Return the in-process lock associated with one SQLite connection."""
    with _CONNECTION_LOCKS_GUARD:
        lock = _CONNECTION_LOCKS.get(conn)
        if lock is None:
            lock = asyncio.Lock()
            _CONNECTION_LOCKS[conn] = lock
        return lock


def connection_write_lock(conn: Any) -> asyncio.Lock:
    """The one in-process write lock every store on this connection shares.

    `serialized_schema_upgrade` already keys schema work by connection so two
    tasks cannot interleave transactions on one aiosqlite connection. The
    durable stores sharing that connection need the same identity for their
    *data* writes (#38): `SqliteProjectScopeStore.delete` refuses a Project
    that owns Runs, and `SqliteRunStore.create_run` validates the Graph's
    Project before inserting -- two check-then-act pairs over the same tables
    from two stores. Private locks per store serialize each store against
    itself and leave the cross-store pair racing (a Run committed after the
    ownership check, then a Project deleted out from under it: the M1-A2
    review's orphaned-Run interleaving). Keying by connection makes the pair
    one critical section in-process; each side's `BEGIN IMMEDIATE` is what a
    second process sharing the file additionally needs, as #1147 established
    for the move-cycle window.
    """
    return _connection_lock(conn)


@asynccontextmanager
async def serialized_schema_upgrade(conn: Any) -> AsyncIterator[None]:
    """Serialize one schema upgrade within and across processes.

    The asyncio lock prevents two tasks from starting transactions on the same
    aiosqlite connection. ``BEGIN IMMEDIATE`` obtains SQLite's database write
    lock, making the read-then-DDL sequence wait behind another process rather
    than observing its pre-upgrade schema. DDL remains transactional, so a
    failed upgrade rolls back as one deterministic unit and can be retried.
    """
    async with _connection_lock(conn):
        # Do not inherit a short driver default: a large legacy backfill may
        # legitimately hold the schema lock longer than a normal write. The
        # caller's previous timeout is restored when the upgrade finishes.
        cursor = await conn.execute("PRAGMA busy_timeout")
        row = await cursor.fetchone()
        prior_timeout = int(row[0]) if row is not None else 0
        try:
            await conn.execute(f"PRAGMA busy_timeout = {_SCHEMA_BUSY_TIMEOUT_MS}")
            try:
                # Cancelling the await does not stop aiosqlite's worker
                # thread: a cancelled BEGIN IMMEDIATE can still land and take
                # the write lock afterwards, so the rollback guard must cover
                # the BEGIN itself and not only the upgrade body.
                await conn.execute("BEGIN IMMEDIATE")
            except BaseException:
                await conn.rollback()
                raise
            try:
                yield
            except BaseException:
                await conn.rollback()
                raise
            else:
                try:
                    await conn.commit()
                except BaseException:
                    # A failed COMMIT (for example a reader in rollback-journal
                    # mode outlasting the busy timeout) can leave the
                    # transaction open; roll it back so the connection does
                    # not keep holding the schema write lock.
                    await conn.rollback()
                    raise
        finally:
            await conn.execute(f"PRAGMA busy_timeout = {prior_timeout}")


async def execute_schema_script(conn: Any, script: str) -> None:
    """Execute a multi-statement schema script without breaking its transaction."""
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            await conn.execute(statement)
            statement = ""
    if statement.strip():
        await conn.execute(statement)


@contextmanager
def serialized_schema_upgrade_sync(conn: sqlite3.Connection) -> Iterator[None]:
    """Serialize a synchronous SQLite schema upgrade across processes."""
    cursor = conn.execute("PRAGMA busy_timeout")
    row = cursor.fetchone()
    prior_timeout = int(row[0]) if row is not None else 0
    try:
        conn.execute(f"PRAGMA busy_timeout = {_SCHEMA_BUSY_TIMEOUT_MS}")
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            conn.rollback()
            raise
        else:
            try:
                conn.commit()
            except BaseException:
                # Mirror the async path: a failed COMMIT can leave the
                # transaction open, so release the schema write lock.
                conn.rollback()
                raise
    finally:
        conn.execute(f"PRAGMA busy_timeout = {prior_timeout}")


def execute_schema_script_sync(conn: sqlite3.Connection, script: str) -> None:
    """Synchronous counterpart of :func:`execute_schema_script`."""
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        conn.execute(statement)
