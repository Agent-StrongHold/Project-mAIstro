"""A deleted Workspace's id is dead, on every store (#37).

`WorkspaceStore.delete` used to leave deletion as a fact an absent row could
carry and nothing else — so any evidence-shaped record could resurrect
deleted authority by minting the row again: a stale Hive convergence mirror
replayed by a lost-journal import, a provisioning helper that kept the id in
configuration, a recovery tool re-running an old plan. #37's contract says
deleted or nonexistent Workspaces cannot regain authority, so every store now
records the deletion (`canonical_workspace_deletions` durably, a set in the
reference) and `create` refuses a tombstoned id.

The reference is in the same suite as its durable twins on purpose: the
tombstone is a contract, and a store that agrees with it only in its
docstring is the failure mode the conformance suites exist to prevent. The
durable legs are also where the *restart* half of the contract lives — a
tombstone that vanishes when the process does would fence exactly nothing,
because resurrection attempts arrive from a later process.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from maistro.testing.postgres import postgres_dsn
from maistro.workspaces.authorization import WorkspaceAuthorizationDenied
from maistro.workspaces.model import WorkspaceDeleted, WorkspaceNotFound


class _MemoryBackend:
    def __init__(self) -> None:
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.workspaces.store import InMemoryWorkspaceStore

        self._store = InMemoryWorkspaceStore(project_store=InMemoryProjectScopeStore())

    async def store(self):
        return self._store

    async def close(self) -> None:
        return None


class _SqliteBackend:
    def __init__(self, tmp_path) -> None:
        self._path = tmp_path / "tombstones.db"
        self._connections: list = []

    async def store(self):
        import aiosqlite

        from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
        from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

        conn = await aiosqlite.connect(self._path)
        self._connections.append(conn)
        scope_store = SqliteProjectScopeStore(conn)
        await scope_store.ensure_schema()
        store = SqliteWorkspaceStore(conn, project_store=scope_store)
        await store.ensure_schema()
        return store

    async def close(self) -> None:
        for conn in self._connections:
            await conn.close()


class _PostgresBackend:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def store(self):
        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.workspaces.pg_store import PgWorkspaceStore

        return PgWorkspaceStore(self._pool, project_store=PgProjectScopeStore(self._pool))

    async def close(self) -> None:
        return None


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def backend(request, tmp_path):
    if request.param == "memory":
        yield _MemoryBackend()
        return

    if request.param == "sqlite":
        made = _SqliteBackend(tmp_path)
        yield made
        await made.close()
        return

    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            msg = (
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
                "the PostgreSQL tombstone leg cannot run and must not be "
                "silently skipped"
            )
            raise RuntimeError(msg)
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")

    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        yield _PostgresBackend(pool)
    finally:
        await pool.close()


def _user(label: str = "") -> str:
    return f"user-{label}{uuid4().hex}"


async def _create(backend, workspace_id: str, creator: str):
    store = await backend.store()
    return await store.create(
        creator_user_id=creator, name=f"W {workspace_id}", workspace_id=workspace_id
    )


class TestADeletedIdIsNeverReCreated:
    async def test_create_refuses_a_deleted_id(self, backend) -> None:
        creator = _user("creator-")
        workspace = await _create(backend, f"ws-{uuid4().hex}", creator)
        store = await backend.store()
        await store.delete(workspace.workspace_id, principal_id=creator)

        with pytest.raises(WorkspaceDeleted):
            await store.create(
                creator_user_id=creator, name="Resurrection", workspace_id=workspace.workspace_id
            )

        # The refusal minted nothing: the id has neither a Workspace row nor a
        # Root Project, so no authority came back through the back door.
        fresh = await backend.store()
        assert await fresh.get(workspace.workspace_id) is None
        from maistro.projects.scope import ProjectNotFound

        with pytest.raises(ProjectNotFound):
            await fresh.project_store.root_for_workspace(workspace.workspace_id)

    async def test_the_tombstone_outlives_the_process_that_deleted(self, backend) -> None:
        """A resurrection attempt comes from a *later* process.

        The durable backends answer from a fresh store on a fresh connection
        to the same database — the closest a test comes to a restart. The
        reference shares the object, which is the whole of its substrate.
        """
        creator = _user("creator-")
        workspace = await _create(backend, f"ws-{uuid4().hex}", creator)
        deleter = await backend.store()
        await deleter.delete(workspace.workspace_id, principal_id=creator)
        close = getattr(deleter, "close", None)
        if close is not None:
            await close()

        resurrector = await backend.store()
        with pytest.raises(WorkspaceDeleted):
            await resurrector.create(
                creator_user_id=creator, name="Resurrection", workspace_id=workspace.workspace_id
            )

    async def test_an_id_that_never_existed_is_not_treated_as_deleted(self, backend) -> None:
        """The tombstone answers 'was this id deleted?', not 'does it exist?'.

        A fresh id — a convergence import minting an identity never seen
        before, a product creating one — must keep working. Only a recorded
        deletion refuses; absence alone is :class:`WorkspaceNotFound`'s
        territory, one layer up in `get`.
        """
        store = await backend.store()
        fresh_id = f"ws-{uuid4().hex}"
        created = await store.create(
            creator_user_id=_user("creator-"), name="Never was", workspace_id=fresh_id
        )
        assert created.workspace_id == fresh_id
        assert await store.get(fresh_id) is not None

    async def test_fresh_ids_are_unaffected_by_a_delete(self, backend) -> None:
        creator = _user("creator-")
        doomed = await _create(backend, f"ws-{uuid4().hex}", creator)
        store = await backend.store()
        await store.delete(doomed.workspace_id, principal_id=creator)

        created = await store.create(creator_user_id=creator, name="Next")
        assert await store.get(created.workspace_id) is not None


class TestTheTombstoneCommitsWithTheDelete:
    async def test_a_failed_delete_leaves_the_id_recreatable(self, backend) -> None:
        """The compensation contract is all-or-nothing, tombstone included.

        A delete that rolls back must not have recorded a tombstone, or the
        Workspace it failed to delete would become un-recreatable while still
        existing. The reference has no transaction, so its tombstone write
        sits behind the same compensation the durable transaction gives for
        free; both are exercised through their own purge seam.
        """

        creator = _user("creator-")
        workspace = await _create(backend, f"ws-{uuid4().hex}", creator)
        store = await backend.store()

        scope = store.project_store
        seam = "purge_workspace_in" if hasattr(scope, "purge_workspace_in") else "purge_workspace"
        original = getattr(scope, seam)
        calls: list = []

        if seam == "purge_workspace_in":

            async def refusing_purge_in(conn, workspace_id: str) -> None:  # type: ignore[no-untyped-def]
                calls.append(workspace_id)
                raise RuntimeError("purge is stuck")

            replacement = refusing_purge_in
        else:

            async def refusing_purge(workspace_id: str) -> None:
                calls.append(workspace_id)
                raise RuntimeError("purge is stuck")

            replacement = refusing_purge

        setattr(scope, seam, replacement)
        try:
            with pytest.raises(RuntimeError, match="purge is stuck"):
                await store.delete(workspace.workspace_id, principal_id=creator)
        finally:
            setattr(scope, seam, original)
        assert calls, "the purge seam was never reached"

        # The rollback restored the Workspace whole — the reference's
        # compensation and the durable transaction agree — so the id is
        # occupied, not tombstoned: create names the duplication, not a
        # deletion.

        assert await store.get(workspace.workspace_id) is not None
        # The reference names the duplication; the durable twins enforce it
        # with the primary key. All refuse the occupied id.
        import sqlite3

        violations: tuple[type[Exception], ...] = (ValueError, sqlite3.IntegrityError)
        try:
            import asyncpg

            violations = (*violations, asyncpg.UniqueViolationError)
        except ImportError:  # pragma: no cover - asyncpg ships with the core deps
            pass

        with pytest.raises(violations):
            await store.create(
                creator_user_id=creator,
                name="Duplicate",
                workspace_id=workspace.workspace_id,
            )

        # And when the delete finally succeeds, the tombstone applies from
        # that moment — not retroactively from the failed attempt.
        await store.delete(workspace.workspace_id, principal_id=creator)
        with pytest.raises(WorkspaceDeleted):
            await store.create(
                creator_user_id=creator,
                name="Resurrection",
                workspace_id=workspace.workspace_id,
            )
        assert await store.get(workspace.workspace_id) is None

    async def test_delete_of_an_absent_workspace_records_nothing(self, backend) -> None:

        creator = _user("creator-")
        ghost = f"ws-{uuid4().hex}"
        store = await backend.store()
        with pytest.raises((WorkspaceNotFound, WorkspaceAuthorizationDenied)):
            await store.delete(ghost, principal_id=creator)

        # A failed delete of an id that never existed records no tombstone:
        # the id is still a fresh, creatable one, not a refused one.
        created = await store.create(creator_user_id=creator, name="Ghost", workspace_id=ghost)
        assert await store.get(created.workspace_id) is not None
