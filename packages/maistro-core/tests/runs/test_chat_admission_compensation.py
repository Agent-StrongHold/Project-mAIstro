"""Atomic compare-and-cancel for the existing #338 no-NodeRun disposition."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import aiosqlite
import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.chat_admission import ADMISSION_INCOMPLETE
from maistro.runs.lifecycle import InvalidLifecycleTransition
from maistro.runs.model import Run, RunStatus
from maistro.runs.sources import ADMISSION_SOURCE, CHAT_SOURCE
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.runs.store import RunIntegrityError, RunNotFound, RunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


async def _admit(
    store: RunStore, workspace: str, project: str, *, source: str = CHAT_SOURCE
) -> Run:
    graph = Graph(
        workspace_id=workspace,
        project_id=project,
        name="chat",
        nodes=[Node(node_id="turn", node_type="agent")],
    )
    return await store.create_run(
        graph,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        provenance={ADMISSION_SOURCE: source},
    )


@pytest.mark.parametrize("stage", [RunStatus.CREATED, RunStatus.QUEUED, RunStatus.RUNNING])
async def test_matching_unstarted_chat_is_cancelled_once(spine: Any, stage: RunStatus) -> None:
    store, workspace, project = spine
    run = await _admit(store, workspace, project)
    if stage is not RunStatus.CREATED:
        run = await store.transition_run(run.run_id, RunStatus.QUEUED)
    if stage is RunStatus.RUNNING:
        run = await store.transition_run(run.run_id, RunStatus.RUNNING)

    assert await store.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
    settled = await store.get_run(run.run_id)
    assert settled.status is RunStatus.CANCELLED
    assert settled.error == ADMISSION_INCOMPLETE
    assert not await store.cancel_unstarted_chat_run(run, error="must not overwrite")
    assert await store.get_run(run.run_id) == settled


async def test_changed_status_defeats_snapshot(spine: Any) -> None:
    store, workspace, project = spine
    original = await _admit(store, workspace, project)
    queued = await store.transition_run(original.run_id, RunStatus.QUEUED)
    assert not await store.cancel_unstarted_chat_run(original, error=ADMISSION_INCOMPLETE)
    assert await store.get_run(original.run_id) == queued


async def test_changed_timestamp_defeats_snapshot(spine: Any) -> None:
    store, workspace, project = spine
    run = await _admit(store, workspace, project)
    stale = run.model_copy(update={"updated_at": run.updated_at - timedelta(seconds=1)})
    assert not await store.cancel_unstarted_chat_run(stale, error=ADMISSION_INCOMPLETE)
    assert await store.get_run(run.run_id) == run


async def test_foreign_admission_is_never_cancelled(spine: Any) -> None:
    store, workspace, project = spine
    run = await _admit(store, workspace, project, source="schedule")
    assert not await store.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
    assert await store.get_run(run.run_id) == run


async def test_noderun_without_attempt_remains_outside_this_disposition(spine: Any) -> None:
    """Characterize the held ownership decision rather than silently expanding it."""
    store, workspace, project = spine
    run = await _admit(store, workspace, project)
    node = await store.create_node_run(run.run_id, node_id="turn")
    assert await store.list_attempts(node.node_run_id) == []
    assert not await store.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
    assert await store.get_run(run.run_id) == run
    assert await store.get_node_run(node.node_run_id) == node


async def test_missing_run_does_not_hide_a_store_failure(spine: Any) -> None:
    store, workspace, project = spine
    run = await _admit(store, workspace, project)
    await store.transition_run(run.run_id, RunStatus.CANCELLED)
    await store.delete_run(run.run_id)
    with pytest.raises(RunNotFound):
        await store.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)


@pytest.mark.parametrize("cancel_first", [False, True])
@pytest.mark.parametrize("operation", ["create", "advance"])
async def test_sqlite_independent_connections_serialize_creation_and_cancellation(
    tmp_path: Any, cancel_first: bool, operation: str
) -> None:
    projects = InMemoryProjectScopeStore()
    project = await projects.create_root("chat-race")
    path = str(tmp_path / "chat.db")
    first_conn = await aiosqlite.connect(path)
    second_conn = await aiosqlite.connect(path)
    held, release, contender = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class _HoldingStore(SqliteRunStore):
        async def _require_run(self, run_id):
            run = await super()._require_run(run_id)
            # Both creator and canceller must reserve the DB before reading.
            # A Python lock cannot serialize these independent connections.
            assert first_conn.in_transaction
            held.set()
            await release.wait()
            return run

    class _ObservedConnection:
        def __getattr__(self, name):
            return getattr(second_conn, name)

        async def execute(self, sql, parameters=()):
            if sql == "BEGIN IMMEDIATE":
                contender.set()
            return await second_conn.execute(sql, parameters)

    setup = SqliteRunStore(first_conn, project_store=projects)
    await setup.ensure_schema()
    run = await _admit(setup, "chat-race", project.project_id)
    if operation == "advance":
        run = await setup.transition_run(run.run_id, RunStatus.QUEUED)

    async def _compete(store):
        if operation == "advance":
            return await store.transition_run(run.run_id, RunStatus.RUNNING)
        return await store.create_node_run(run.run_id, node_id="turn")

    holder = _HoldingStore(first_conn, project_store=projects)
    other = SqliteRunStore(_ObservedConnection(), project_store=projects)
    tasks: list[asyncio.Task] = []
    try:
        async with asyncio.timeout(5):
            first = asyncio.create_task(
                holder.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
                if cancel_first
                else _compete(holder)
            )
            tasks.append(first)
            await held.wait()
            second = asyncio.create_task(
                _compete(other)
                if cancel_first
                else other.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
            )
            tasks.append(second)
            await contender.wait()
            release.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
        current = await setup.get_run(run.run_id)
        if cancel_first:
            assert results[0] is True
            assert isinstance(results[1], (RunIntegrityError, InvalidLifecycleTransition))
            assert current.status is RunStatus.CANCELLED
            assert await setup.list_node_runs(run.run_id) == []
        else:
            assert not isinstance(results[0], BaseException)
            assert results[1] is False
            assert current.status is (
                RunStatus.RUNNING if operation == "advance" else RunStatus.CREATED
            )
            assert len(await setup.list_node_runs(run.run_id)) == (operation == "create")
        assert not first_conn.in_transaction and not second_conn.in_transaction
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await first_conn.close()
        await second_conn.close()

    # Durable read-back uses a new connection, not either participant's state.
    async with aiosqlite.connect(path) as reopened:
        store = SqliteRunStore(reopened, project_store=projects)
        current = await store.get_run(run.run_id)
        assert current.status is (
            RunStatus.CANCELLED
            if cancel_first
            else RunStatus.RUNNING
            if operation == "advance"
            else RunStatus.CREATED
        )


@pytest.mark.parametrize("cancel_first", [False, True])
async def test_postgres_independent_transactions_serialize_creation_and_cancellation(
    pg_pool: Any, cancel_first: bool
) -> None:
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.pg_store import PgRunStore

    projects = PgProjectScopeStore(pg_pool)
    project = await projects.create_root("chat-pg-race")
    setup = PgRunStore(pg_pool, project_store=projects)
    run = await _admit(setup, "chat-pg-race", project.project_id)
    held, release, contender = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class _HoldingStore(PgRunStore):
        async def _locked(self, conn, table, column, identity):
            payload = await super()._locked(conn, table, column, identity)
            if table == "canonical_runs":
                held.set()
                await release.wait()
            return payload

    class _ContendingStore(PgRunStore):
        async def _locked(self, conn, table, column, identity):
            contender.set()
            return await super()._locked(conn, table, column, identity)

    holder = _HoldingStore(pg_pool, project_store=projects)
    other = _ContendingStore(pg_pool, project_store=projects)
    tasks: list[asyncio.Task] = []
    try:
        async with asyncio.timeout(5):
            first = asyncio.create_task(
                holder.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
                if cancel_first
                else holder.create_node_run(run.run_id, node_id="turn")
            )
            tasks.append(first)
            await held.wait()
            second = asyncio.create_task(
                other.create_node_run(run.run_id, node_id="turn")
                if cancel_first
                else other.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
            )
            tasks.append(second)
            await contender.wait()
            release.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
        current = await setup.get_run(run.run_id)
        if cancel_first:
            assert results[0] is True
            assert isinstance(results[1], RunIntegrityError)
            assert current.status is RunStatus.CANCELLED
            assert await setup.list_node_runs(run.run_id) == []
        else:
            assert not isinstance(results[0], BaseException)
            assert results[1] is False
            assert current.status is RunStatus.CREATED
            assert len(await setup.list_node_runs(run.run_id)) == 1
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_competing_cancellers_only_count_one_repair(spine: Any) -> None:
    store, workspace, project = spine
    run = await _admit(store, workspace, project)
    results = await asyncio.gather(
        store.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE),
        store.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE),
    )
    assert sorted(results) == [False, True]


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("operation", ["cancel", "advance"])
async def test_sqlite_failed_conditional_write_rolls_back_and_releases_connection(
    tmp_path: Any, cancelled: bool, operation: str
) -> None:
    projects = InMemoryProjectScopeStore()
    project = await projects.create_root("chat-rollback")
    async with aiosqlite.connect(str(tmp_path / "chat.db")) as conn:
        store = SqliteRunStore(conn, project_store=projects)
        await store.ensure_schema()
        run = await _admit(store, "chat-rollback", project.project_id)
        if operation == "advance":
            run = await store.transition_run(run.run_id, RunStatus.QUEUED)

        class _BrokenWrite:
            def __getattr__(self, name):
                return getattr(conn, name)

            async def execute(self, sql, parameters=()):
                result = await conn.execute(sql, parameters)
                if sql.startswith("UPDATE canonical_runs"):
                    if cancelled:
                        raise asyncio.CancelledError
                    raise ConnectionError("write failed before commit")
                return result

        broken = SqliteRunStore(_BrokenWrite(), project_store=projects)
        with pytest.raises(asyncio.CancelledError if cancelled else ConnectionError):
            if operation == "advance":
                await broken.transition_run(run.run_id, RunStatus.RUNNING)
            else:
                await broken.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
        assert not conn.in_transaction
        assert await store.get_run(run.run_id) == run
        assert await store.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)


async def test_postgres_failed_conditional_write_rolls_back(pg_pool: Any) -> None:
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.pg_store import PgRunStore

    projects = PgProjectScopeStore(pg_pool)
    project = await projects.create_root("chat-pg-rollback")
    store = PgRunStore(pg_pool, project_store=projects)
    run = await _admit(store, "chat-pg-rollback", project.project_id)

    class _BrokenWriteStore(PgRunStore):
        @staticmethod
        async def _write(conn, table, column, identity, model):
            await PgRunStore._write(conn, table, column, identity, model)
            raise ConnectionError("write failed before commit")

    broken = _BrokenWriteStore(pg_pool, project_store=projects)
    with pytest.raises(ConnectionError):
        await broken.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
    assert await store.get_run(run.run_id) == run
    assert await store.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("operation", ["cancel", "create", "advance"])
async def test_sqlite_lost_begin_response_does_not_leave_a_transaction(
    tmp_path: Any, cancelled: bool, operation: str
) -> None:
    projects = InMemoryProjectScopeStore()
    project = await projects.create_root("chat-begin")
    async with aiosqlite.connect(str(tmp_path / "chat.db")) as conn:
        store = SqliteRunStore(conn, project_store=projects)
        await store.ensure_schema()
        run = await _admit(store, "chat-begin", project.project_id)

        class _BrokenBegin:
            def __getattr__(self, name):
                return getattr(conn, name)

            async def execute(self, sql, parameters=()):
                result = await conn.execute(sql, parameters)
                if sql == "BEGIN IMMEDIATE":
                    if cancelled:
                        raise asyncio.CancelledError
                    raise ConnectionError("BEGIN response lost")
                return result

        broken = SqliteRunStore(_BrokenBegin(), project_store=projects)
        with pytest.raises(asyncio.CancelledError if cancelled else ConnectionError):
            if operation == "cancel":
                await broken.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
            elif operation == "create":
                await broken.create_node_run(run.run_id, node_id="turn")
            else:
                await broken.transition_run(run.run_id, RunStatus.QUEUED)
        assert not conn.in_transaction
        assert await store.get_run(run.run_id) == run
        assert await store.list_node_runs(run.run_id) == []
        # The same connection can perform a later transaction, not just read.
        node = await store.create_node_run(run.run_id, node_id="turn")
        assert node.run_id == run.run_id


@pytest.mark.parametrize("operation", ["cancel", "create", "advance"])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_sqlite_refused_begin_preserves_sibling_transaction_even_when_cancelled(
    tmp_path: Any, operation: str, cancelled: bool
) -> None:
    """A rejected queued BEGIN never gives this operation rollback authority."""
    import sqlite3
    import threading

    projects = InMemoryProjectScopeStore()
    project = await projects.create_root("chat-sibling")
    async with aiosqlite.connect(str(tmp_path / "chat.db")) as conn:
        setup = SqliteRunStore(conn, project_store=projects)
        await setup.ensure_schema()
        run = await _admit(setup, "chat-sibling", project.project_id)
        await conn.execute("CREATE TABLE sibling (value TEXT)")
        await conn.commit()
        await conn.execute("INSERT INTO sibling VALUES ('uncommitted')")
        assert conn.in_transaction

        held, began = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()

        def _hold_worker():
            loop.call_soon_threadsafe(held.set)
            assert release.wait(5), "test did not release the SQLite worker"
            return 1

        await conn.create_function("hold_worker", 0, _hold_worker)

        class _ObservedBegin:
            def __getattr__(self, name):
                return getattr(conn, name)

            async def execute(self, sql, parameters=()):
                if sql == "BEGIN IMMEDIATE":
                    began.set()
                return await conn.execute(sql, parameters)

        store = SqliteRunStore(_ObservedBegin(), project_store=projects)

        async def _operation():
            if operation == "cancel":
                return await store.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
            if operation == "create":
                return await store.create_node_run(run.run_id, node_id="turn")
            return await store.transition_run(run.run_id, RunStatus.QUEUED)

        blocker = asyncio.ensure_future(conn.execute("SELECT hold_worker()"))
        task: asyncio.Task | None = None
        try:
            async with asyncio.timeout(5):
                await held.wait()
                task = asyncio.create_task(_operation())
                await began.wait()
                if cancelled:
                    task.cancel()
                release.set()
                (result,) = await asyncio.gather(task, return_exceptions=True)
                await blocker
            assert isinstance(
                result, asyncio.CancelledError if cancelled else sqlite3.OperationalError
            )
            assert conn.in_transaction
            cursor = await conn.execute("SELECT value FROM sibling")
            assert await cursor.fetchall() == [("uncommitted",)]
            assert await setup.get_run(run.run_id) == run
        finally:
            release.set()
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await asyncio.gather(blocker, return_exceptions=True)
            await conn.rollback()
