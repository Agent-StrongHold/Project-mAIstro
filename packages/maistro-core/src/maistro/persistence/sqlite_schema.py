"""SQLite startup schema serialization shared by durable stores."""

from __future__ import annotations

from typing import Any


async def begin_schema_upgrade(conn: Any) -> None:
    """Acquire SQLite's file writer lock before inspect-and-alter upgrades.

    ``CREATE TABLE IF NOT EXISTS`` is safe concurrently, but a subsequent
    ``PRAGMA table_info`` followed by ``ALTER TABLE`` is not. ``BEGIN
    IMMEDIATE`` makes that whole startup decision one database-level critical
    section and the existing store commit releases it.
    """
    await conn.execute("PRAGMA busy_timeout = 5000")
    await conn.execute("BEGIN IMMEDIATE")
