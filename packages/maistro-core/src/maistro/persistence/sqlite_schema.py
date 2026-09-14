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
        # legitimately hold the schema lock longer than a normal write.
        await conn.execute(f"PRAGMA busy_timeout = {_SCHEMA_BUSY_TIMEOUT_MS}")
        await conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            await conn.rollback()
            raise
        else:
            await conn.commit()


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
    conn.execute(f"PRAGMA busy_timeout = {_SCHEMA_BUSY_TIMEOUT_MS}")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


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
