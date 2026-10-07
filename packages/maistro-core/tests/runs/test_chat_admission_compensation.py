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


@pytest.mark.parametrize("shared_cursor", [False, True])
@pytest.mark.parametrize(
    "operation", ["cancel_after_create", "cancel_after_advance", "create", "advance"]
)
async def test_sqlite_physical_writes_preserve_compensation_winner(
    tmp_path: Any, operation: str, shared_cursor: bool
) -> None:
    """A shipped sibling can end BEGIN, but cannot authorize a stale write."""
    from maistro.events.consumer_cursor import SqliteConsumerCursorStore

    projects = InMemoryProjectScopeStore()
    project = await projects.create_root("chat-shared-cursor")
    path = str(tmp_path / "shared-chat.db")
    async with aiosqlite.connect(path) as first, aiosqlite.connect(path) as second:
        setup = SqliteRunStore(first, project_store=projects)
        peer = SqliteRunStore(second, project_store=projects)
        # Container wires this actual cursor store to the Run store's same
        # connection. Its public claim commits, with no shared Python lock.
        sibling = SqliteConsumerCursorStore(first)
        await setup.ensure_schema()
        await sibling.ensure_schema()
        run = await _admit(setup, "chat-shared-cursor", project.project_id)
        if operation in ("advance", "cancel_after_advance"):
            run = await setup.transition_run(run.run_id, RunStatus.QUEUED)
        interleaved = False

        class _BeforePhysicalWrite:
            def __getattr__(self, name):
                return getattr(first, name)

            async def execute(self, sql, parameters=()):
                nonlocal interleaved
                guarded_write = (
                    "INSERT INTO canonical_node_runs"
                    if operation == "create"
                    else "UPDATE canonical_runs"
                )
                if sql.startswith(guarded_write) and not interleaved:
                    interleaved = True
                    if shared_cursor:
                        assert await sibling.claim("chat-review", holder="cursor-worker")
                        assert not first.in_transaction
                    if operation == "cancel_after_create":
                        await peer.create_node_run(run.run_id, node_id="turn")
                    elif operation == "cancel_after_advance":
                        await peer.transition_run(run.run_id, RunStatus.RUNNING)
                    else:
                        assert await peer.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
                return await first.execute(sql, parameters)

        actor = SqliteRunStore(_BeforePhysicalWrite(), project_store=projects)
        if operation.startswith("cancel_after_"):
            assert not await actor.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
        else:
            with pytest.raises(
                RunIntegrityError if operation == "create" else InvalidLifecycleTransition,
                match="Run changed",
            ):
                if operation == "create":
                    await actor.create_node_run(run.run_id, node_id="turn")
                else:
                    await actor.transition_run(run.run_id, RunStatus.RUNNING)
        assert interleaved
        assert not first.in_transaction and not second.in_transaction

    async with aiosqlite.connect(path) as reopened:
        store = SqliteRunStore(reopened, project_store=projects)
        current = await store.get_run(run.run_id)
        assert current is not None
        assert (
            current.status
            is {
                "cancel_after_create": RunStatus.CREATED,
                "cancel_after_advance": RunStatus.RUNNING,
                "create": RunStatus.CANCELLED,
                "advance": RunStatus.CANCELLED,
            }[operation]
        )
        nodes = await store.list_node_runs(run.run_id)
        assert len(nodes) == (operation == "cancel_after_create")
        assert all(node.status is RunStatus.CREATED for node in nodes)
        # A losing conditional write neither rolls back nor overwrites the
        # cursor claim that committed between the reads and the write.
        cursor = await reopened.execute(
            "SELECT holder FROM consumer_cursors WHERE consumer_id = 'chat-review'"
        )
        assert await cursor.fetchone() == (("cursor-worker",) if shared_cursor else None)


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


@pytest.mark.parametrize("operation", ["cancel", "create", "advance"])
async def test_sqlite_refused_operation_preserves_pending_sibling_claim(
    tmp_path: Any, operation: str
) -> None:
    """A validation refusal has no authority to roll back another store's write."""
    from maistro.events.consumer_cursor import SqliteConsumerCursorStore

    projects = InMemoryProjectScopeStore()
    project = await projects.create_root("chat-sibling-refusal")
    path = str(tmp_path / "sibling-refusal.db")
    async with aiosqlite.connect(path) as conn:
        setup = SqliteRunStore(conn, project_store=projects)
        await setup.ensure_schema()
        run = await _admit(setup, "chat-sibling-refusal", project.project_id)
        inserted, release = asyncio.Event(), asyncio.Event()

        class _HeldCursor:
            def __init__(self, inner):
                self.inner = inner

            async def fetchone(self):
                row = await self.inner.fetchone()
                inserted.set()
                await release.wait()
                return row

        class _HeldConnection:
            def __getattr__(self, name):
                return getattr(conn, name)

            async def execute(self, sql, parameters=()):
                cursor = await conn.execute(sql, parameters)
                return _HeldCursor(cursor) if "INSERT INTO consumer_cursors" in sql else cursor

        sibling = SqliteConsumerCursorStore(_HeldConnection())
        await sibling.ensure_schema()
        pending: asyncio.Task | None = None

        class _InterleavedStore(SqliteRunStore):
            async def _fetchone(self, sql, parameters=()):
                nonlocal pending
                row = await super()._fetchone(sql, parameters)
                if pending is None and sql.startswith("SELECT payload FROM canonical_runs"):
                    pending = asyncio.create_task(sibling.claim("victim", holder="sibling"))
                    await inserted.wait()
                return row

        actor = _InterleavedStore(conn, project_store=projects)
        try:
            async with asyncio.timeout(5):
                if operation == "cancel":
                    stale = run.model_copy(
                        update={"updated_at": run.updated_at - timedelta(seconds=1)}
                    )
                    assert not await actor.cancel_unstarted_chat_run(
                        stale, error=ADMISSION_INCOMPLETE
                    )
                elif operation == "create":
                    with pytest.raises(RunIntegrityError, match="not present"):
                        await actor.create_node_run(run.run_id, node_id="missing")
                else:
                    with pytest.raises(InvalidLifecycleTransition):
                        await actor.transition_run(run.run_id, RunStatus.RUNNING)
        finally:
            release.set()
            assert pending is not None
            assert await pending is not None

    async with aiosqlite.connect(path) as reopened:
        cursor = await reopened.execute(
            "SELECT holder FROM consumer_cursors WHERE consumer_id = 'victim'"
        )
        assert await cursor.fetchone() == ("sibling",)
        assert await SqliteRunStore(reopened, project_store=projects).get_run(run.run_id) == run


@pytest.mark.parametrize("operation", ["cancel", "create", "advance"])
async def test_sqlite_guard_compares_exact_historical_payload(
    tmp_path: Any, operation: str
) -> None:
    """Hydration defaults/JSON formatting do not make an unchanged snapshot stale."""
    import json

    projects = InMemoryProjectScopeStore()
    project = await projects.create_root("chat-legacy-payload")
    async with aiosqlite.connect(str(tmp_path / "legacy.db")) as conn:
        store = SqliteRunStore(conn, project_store=projects)
        await store.ensure_schema()
        run = await _admit(store, "chat-legacy-payload", project.project_id)
        payload = run.model_dump(mode="json")
        del payload["result"]
        del payload["error"]
        await conn.execute(
            "UPDATE canonical_runs SET payload = ? WHERE run_id = ?",
            (json.dumps(payload, indent=2, sort_keys=True), run.run_id),
        )
        await conn.commit()
        if operation == "cancel":
            assert await store.cancel_unstarted_chat_run(run, error=ADMISSION_INCOMPLETE)
        elif operation == "create":
            assert (await store.create_node_run(run.run_id, node_id="turn")).run_id == run.run_id
        else:
            assert (
                await store.transition_run(run.run_id, RunStatus.QUEUED)
            ).status is RunStatus.QUEUED


async def test_sqlite_cancellation_service_reconciles_a_cas_loser(tmp_path: Any) -> None:
    """A stale lifecycle write keeps the service's cancellation-race exception contract."""
    from maistro.runs.service import RunExecutionService
    from maistro.runtime import PythonExecutionRuntime

    projects = InMemoryProjectScopeStore()
    project = await projects.create_root("chat-cancel-service")
    path = str(tmp_path / "cancel-service.db")
    async with aiosqlite.connect(path) as first, aiosqlite.connect(path) as second:
        setup = SqliteRunStore(first, project_store=projects)
        peer = SqliteRunStore(second, project_store=projects)
        await setup.ensure_schema()
        run = await _admit(setup, "chat-cancel-service", project.project_id)
        await setup.transition_run(run.run_id, RunStatus.QUEUED)
        await setup.transition_run(run.run_id, RunStatus.RUNNING)
        interleaved = False

        class _BeforeWrite:
            def __getattr__(self, name):
                return getattr(first, name)

            async def execute(self, sql, parameters=()):
                nonlocal interleaved
                if sql.startswith("UPDATE canonical_runs") and not interleaved:
                    interleaved = True
                    await peer.transition_run(run.run_id, RunStatus.CANCELLED)
                return await first.execute(sql, parameters)

        actor = SqliteRunStore(_BeforeWrite(), project_store=projects)
        service = RunExecutionService(store=actor, runtime=PythonExecutionRuntime())
        settled = await service.cancel_run(run.run_id)
        assert settled.status is RunStatus.CANCELLED
        assert interleaved
        assert not first.in_transaction and not second.in_transaction

    async with aiosqlite.connect(path) as reopened:
        persisted = await SqliteRunStore(reopened, project_store=projects).get_run(run.run_id)
        assert persisted == settled
