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

_DURABLE_RUN_LEGACY_SCHEMA = """
    CREATE TABLE durable_graph_runs (
        run_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        active_node_id TEXT,
        project_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        resume_at TEXT,
        version INTEGER NOT NULL DEFAULT 0,
        record_json TEXT NOT NULL
    )
"""


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


def _ensure_durable_run_worker(path: str, barrier: Any, results: Any) -> None:
    """Open the synchronous durable-run store in a fresh process."""
    try:
        from maistro.graph.durable_runs.stores import SqliteDurableRunStore

        barrier.wait()
        SqliteDurableRunStore(path)
    except BaseException:
        results.put(("error", traceback.format_exc()))
    else:
        results.put(("ok", "durable_graph_runs"))


def _make_legacy_database(path: Path, kind: str) -> None:
    with sqlite3.connect(path) as conn:
        for statement in _LEGACY_SCHEMA[kind].split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.commit()


def _make_legacy_durable_run_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(_DURABLE_RUN_LEGACY_SCHEMA)
        conn.commit()


@pytest.mark.asyncio
async def test_busy_timeout_restored_after_upgrade(tmp_path: Path) -> None:
    """The schema upgrade must not leave its 60s timeout on the connection."""
    import aiosqlite

    path = tmp_path / "timeout.sqlite"
    async with aiosqlite.connect(path) as conn:
        await conn.execute("PRAGMA busy_timeout = 1234")
        async with serialized_schema_upgrade(conn):
            cursor = await conn.execute("PRAGMA busy_timeout")
            row = await cursor.fetchone()
            assert int(row[0]) >= 60_000  # upgrade-time timeout in force
        cursor = await conn.execute("PRAGMA busy_timeout")
        row = await cursor.fetchone()
        assert int(row[0]) == 1234  # caller's timeout restored


@pytest.mark.asyncio
async def test_busy_timeout_restored_after_failed_upgrade(tmp_path: Path) -> None:
    """The restore happens on the failure path too."""
    import aiosqlite

    path = tmp_path / "timeout-fail.sqlite"
    async with aiosqlite.connect(path) as conn:
        await conn.execute("PRAGMA busy_timeout = 4321")
        with pytest.raises(sqlite3.OperationalError, match="boom"):
            async with serialized_schema_upgrade(conn):
                raise sqlite3.OperationalError("boom")
        cursor = await conn.execute("PRAGMA busy_timeout")
        row = await cursor.fetchone()
        assert int(row[0]) == 4321


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_and_propagates(tmp_path: Path) -> None:
    """A failing COMMIT must roll back instead of leaking the write lock."""
    import aiosqlite

    path = tmp_path / "commit-fail.sqlite"
    async with aiosqlite.connect(path) as conn:
        original_commit = conn.commit
        original_rollback = conn.rollback
        rollback_calls: list[int] = []

        async def failing_commit() -> None:
            raise sqlite3.OperationalError("database is locked during commit")

        async def tracking_rollback() -> None:
            rollback_calls.append(1)
            await original_rollback()

        conn.commit = failing_commit  # type: ignore[method-assign]
        conn.rollback = tracking_rollback  # type: ignore[method-assign]
        with pytest.raises(sqlite3.OperationalError, match="locked during commit"):
            async with serialized_schema_upgrade(conn):
                await conn.execute("CREATE TABLE committed_never (id INTEGER)")
        assert rollback_calls, "COMMIT failure must trigger rollback"
        conn.commit = original_commit  # type: ignore[method-assign]
        conn.rollback = original_rollback  # type: ignore[method-assign]
        # The leaked transaction was rolled back, so a fresh upgrade works.
        async with serialized_schema_upgrade(conn):
            await conn.execute("CREATE TABLE committed_never (id INTEGER)")


def test_sync_upgrade_restores_timeout_and_rolls_back_failed_commit(tmp_path: Path) -> None:
    """Sync path mirrors the async guarantees."""
    from maistro.persistence.sqlite_schema import serialized_schema_upgrade_sync

    path = tmp_path / "sync.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA busy_timeout = 2345")

        class _FailingCommit:
            """Delegates everything to the real connection but commit fails."""

            def __init__(self, inner: sqlite3.Connection) -> None:
                self._inner = inner

            def execute(self, sql: str, *args: object) -> Any:
                return self._inner.execute(sql, args)  # type: ignore[arg-type]

            def rollback(self) -> None:
                self._inner.rollback()

            def commit(self) -> None:
                raise sqlite3.OperationalError("locked during commit")

        with pytest.raises(sqlite3.OperationalError, match="locked during commit"), \
                serialized_schema_upgrade_sync(_FailingCommit(conn)):
            conn.execute("CREATE TABLE sync_never (id INTEGER)")
        # Timeout restored despite the failure.
        assert int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) == 2345
        # Transaction was rolled back: a fresh upgrade succeeds.
        with serialized_schema_upgrade_sync(conn):
            conn.execute("CREATE TABLE sync_never (id INTEGER)")


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


@pytest.mark.asyncio
async def test_configured_sqlite_schema_failure_propagates(tmp_path: Path) -> None:
    """Wiring surfaces an incompatible schema instead of choosing memory."""
    import aiosqlite

    from maistro.container import _wire_episodic_store

    path = tmp_path / "incompatible.sqlite"
    async with aiosqlite.connect(path) as conn:
        await conn.execute("CREATE TABLE episodic_memories (memory_id TEXT)")
        await conn.commit()
        with pytest.raises(sqlite3.OperationalError, match="no such column"):
            await _wire_episodic_store(
                database_url="sqlite:///incompatible.sqlite",
                pg_pool=None,
                db_pool=conn,
            )


@pytest.mark.asyncio
async def test_legacy_capability_invocation_schema_adds_revision(tmp_path: Path) -> None:
    """The shared transaction also covers late columns outside memory stores."""
    import aiosqlite

    from maistro.capabilities.invocation_store import SqliteInvocationStore

    path = tmp_path / "invocations.sqlite"
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            """
            CREATE TABLE capability_invocations (
                invocation_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                node_run_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                binding_id TEXT NOT NULL,
                effect_key TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        await conn.commit()
        await SqliteInvocationStore(conn).ensure_schema()

        cursor = await conn.execute("PRAGMA table_info(capability_invocations)")
        columns = {str(row[1]): row[4] for row in await cursor.fetchall()}
        assert columns["revision"] == "0"


requires_fork = pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(),
    reason="platform does not provide the fork start method (e.g. native Windows)",
)


@requires_fork
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


@requires_fork
def test_two_processes_upgrade_synchronous_durable_run_store(tmp_path: Path) -> None:
    """The synchronous canonical initializer also serializes legacy upgrades."""
    path = tmp_path / "durable_graph_runs.sqlite"
    _make_legacy_durable_run_database(path)

    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(target=_ensure_durable_run_worker, args=(str(path), barrier, results))
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
    assert observed == [("ok", "durable_graph_runs"), ("ok", "durable_graph_runs")]

    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(durable_graph_runs)")}
    assert "hitl_deadline_at" in columns
