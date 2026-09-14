"""SQLite startup upgrades serialize across supported processes."""

from __future__ import annotations

import asyncio

import aiosqlite
import pytest

from maistro.persistence.sqlite_learnings import SqliteLearningStore


@pytest.mark.asyncio
async def test_concurrent_learning_schema_upgrades_do_not_race(tmp_path) -> None:
    database = tmp_path / "shared.db"
    first_conn = await aiosqlite.connect(database)
    second_conn = await aiosqlite.connect(database)
    try:
        await asyncio.gather(
            SqliteLearningStore(first_conn).ensure_schema(),
            SqliteLearningStore(second_conn).ensure_schema(),
        )
        cursor = await first_conn.execute("PRAGMA table_info(learnings)")
        columns = {row[1] for row in await cursor.fetchall()}
        assert {"org_id", "run_id", "node_run_id", "attempt_id"} <= columns
    finally:
        await first_conn.close()
        await second_conn.close()
