"""Cross-process coverage for SQLite schema upgrade serialization."""

from __future__ import annotations

import asyncio
import multiprocessing
import sqlite3
import traceback
from pathlib import Path
from typing import Any

import pytest

from maistro.persistence.sqlite_schema import serialized_schema_upgrade

_LEGACY_SCHEMA: dict[str, str] = {
    "learnings": """
        CREATE TABLE learnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL DEFAULT 'general',
            trigger_keys TEXT NOT NULL DEFAULT '[]',
            learning TEXT NOT NULL DEFAULT '',
            tool_name TEXT NOT NULL DEFAULT '',
            agent_id TEXT NOT NULL DEFAULT '',
            user_id TEXT,
            scope TEXT NOT NULL DEFAULT 'agent',
            hit_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            rca_category TEXT,
            rca_prevention TEXT NOT NULL DEFAULT '',
            success_after_use INTEGER NOT NULL DEFAULT 0,
            failure_after_use INTEGER NOT NULL DEFAULT 0
        )
    """,
    "episodic_memories": """
        CREATE TABLE episodic_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL UNIQUE,
            tier TEXT NOT NULL DEFAULT 'observation',
            content TEXT NOT NULL DEFAULT '',
            weight REAL NOT NULL DEFAULT 0.3,
            org_id TEXT NOT NULL DEFAULT '',
            team_id TEXT NOT NULL DEFAULT '',
            agent_id TEXT,
            user_id TEXT,
            scope TEXT NOT NULL DEFAULT 'agent',
            source TEXT NOT NULL DEFAULT '',
            context TEXT NOT NULL DEFAULT '{}',
            reinforcement_count INTEGER NOT NULL DEFAULT 0,
            contradiction_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT '',
            last_accessed_at TEXT NOT NULL DEFAULT '',
            deleted INTEGER NOT NULL DEFAULT 0
        )
    """,
    "outcomes": """
        CREATE TABLE outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL DEFAULT '',
            task_type TEXT NOT NULL DEFAULT '',
            model_used TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT '',
            tool_calls TEXT NOT NULL DEFAULT '',
            success INTEGER NOT NULL DEFAULT 1,
            error_type TEXT NOT NULL DEFAULT '',
            response_time_ms INTEGER NOT NULL DEFAULT 0,
            team_id TEXT NOT NULL DEFAULT '',
            user_id TEXT NOT NULL DEFAULT '',
            agent_id TEXT NOT NULL DEFAULT '',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            charged_microchips INTEGER NOT NULL DEFAULT 0,
            pricing_version TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
    """,
    "session_turns": """
        CREATE TABLE sessions (
            session_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp REAL NOT NULL,
            PRIMARY KEY (session_id, seq)
        );
        CREATE TABLE session_turns (
            session_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            PRIMARY KEY (session_id, turn_id)
        )
    """,
}


def _ensure_worker(kind: str, path: str, barrier: Any, results: Any) -> None:
    """Open one legacy file in a fresh process and run its upgrade."""

    async def run() -> None:
        import aiosqlite

        from maistro.persistence.sqlite_episodic import SqliteEpisodicStore
        from maistro.persistence.sqlite_learnings import SqliteLearningStore
        from maistro.persistence.sqlite_outcomes import SqliteOutcomeStore
        from maistro.persistence.sqlite_sessions import SqliteSessionStore

        stores = {
            "learnings": SqliteLearningStore,
            "episodic_memories": SqliteEpisodicStore,
            "outcomes": SqliteOutcomeStore,
            "session_turns": SqliteSessionStore,
        }
        async with aiosqlite.connect(path, timeout=10) as conn:
            barrier.wait()
            await stores[kind](conn).ensure_schema()

    try:
        asyncio.run(run())
    except BaseException:
        results.put(("error", traceback.format_exc()))
    else:
        results.put(("ok", kind))


def _make_legacy_database(path: Path, kind: str) -> None:
    with sqlite3.connect(path) as conn:
        for statement in _LEGACY_SCHEMA[kind].split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.commit()


@pytest.mark.asyncio
async def test_failed_upgrade_rolls_back_and_can_retry(tmp_path: Path) -> None:
    """A failed DDL step leaves no half-upgraded schema behind."""
    import aiosqlite

    path = tmp_path / "retry.sqlite"
    async with aiosqlite.connect(path) as conn:
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            async with serialized_schema_upgrade(conn):
                await conn.execute("CREATE TABLE partial (id INTEGER)")
                await conn.execute("ALTER TABLE missing ADD COLUMN value TEXT")

        cursor = await conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'partial'"
        )
        assert await cursor.fetchone() is None

        async with serialized_schema_upgrade(conn):
            await conn.execute("CREATE TABLE partial (id INTEGER)")


@pytest.mark.parametrize("kind", sorted(_LEGACY_SCHEMA))
def test_two_processes_upgrade_each_legacy_sqlite_store(kind: str, tmp_path: Path) -> None:
    """Both first opens must succeed when they race on the same old file."""
    path = tmp_path / f"{kind}.sqlite"
    _make_legacy_database(path, kind)

    # Fork keeps the test module importable when pytest collects this directory
    # as the top-level ``persistence`` module; the workers still have distinct
    # processes and SQLite connections.
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(target=_ensure_worker, args=(kind, str(path), barrier, results))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
    for process in processes:
        if process.is_alive():
            process.terminate()
        assert process.exitcode == 0

    observed = [results.get(timeout=5) for _ in processes]
    assert observed == [("ok", kind), ("ok", kind)]
