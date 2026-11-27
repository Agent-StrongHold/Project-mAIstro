"""A Root Project is minted only for a Workspace that exists (#37).

`create_root` is the write every admission path rides on — the task router,
chat wiring, design scopes — and it used to mint a Root for any non-blank id,
which is how a Workspace id that no canonical row owned could end up owning
scope anyway. Migration 019's docstring called the missing constraint out and
deferred it here; this is here.

The three stores enforce it differently and this suite holds them to the same
answer. The reference checks its bound Workspace store — an *unbound*
reference store has no authority to ask, and keeps the pre-#37 behaviour,
which bare test wiring relies on. The SQLite store checks the table on its
own connection inside the caller's transaction, with one explicit escape: a
database where the Workspace authority was never provisioned (no
`canonical_workspaces` table) has never owned a Workspace, so there is
nothing to verify against yet. Once provisioned, the table exists forever and
the fence is unconditional. PostgreSQL's fence is exercised against a real
server in `tests/persistence/test_workspace_scope_fence_pg.py`, because a
connection-mocked query cannot prove a row lock fences a concurrent delete.
"""

from __future__ import annotations

import aiosqlite
import pytest

from maistro.projects.scope import ProjectNotFound
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
from maistro.workspaces.model import WorkspaceNotFound
from maistro.workspaces.store import InMemoryWorkspaceStore


async def test_the_reference_refuses_an_unknown_workspace_when_an_authority_is_bound() -> None:
    projects = InMemoryProjectScopeStore()
    InMemoryWorkspaceStore(project_store=projects)  # binds itself

    with pytest.raises(WorkspaceNotFound):
        await projects.create_root("ws-never-provisioned")

    # Zero resulting rows: the refusal happened before the tree was touched.
    with pytest.raises(ProjectNotFound):
        await projects.root_for_workspace("ws-never-provisioned")


async def test_the_reference_mints_for_a_workspace_the_bound_authority_owns() -> None:
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)

    workspace = await workspaces.create(creator_user_id="u1", name="Owned")
    root = await projects.create_root(workspace.workspace_id)
    assert root.workspace_id == workspace.workspace_id
    assert root.is_root


async def test_an_unbound_reference_store_keeps_the_legacy_behaviour() -> None:
    """The documented escape, pinned so it cannot silently widen.

    This is the shape bare test wiring and stores constructed before their
    Workspace authority exist in. It is *not* the shape production wiring
    uses: `InMemoryWorkspaceStore.__init__` binds its project store, so every
    wired in-memory deployment gets the fence. If this test starts failing
    because the unbound case now refuses, that is a deliberate contract
    change — go change the wiring first, not the test.
    """
    projects = InMemoryProjectScopeStore()
    assert projects._workspace_store is None

    root = await projects.create_root("ws-bare-wiring")
    assert root.workspace_id == "ws-bare-wiring"


class TestSqliteFence:
    async def _store(self, tmp_path):
        conn = await aiosqlite.connect(tmp_path / "fence.db")
        scope = SqliteProjectScopeStore(conn)
        await scope.ensure_schema()
        return conn, scope

    async def test_a_provisioned_database_refuses_an_unknown_workspace(self, tmp_path) -> None:
        from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

        conn, scope = await self._store(tmp_path)
        try:
            workspaces = SqliteWorkspaceStore(conn, project_store=scope)
            await workspaces.ensure_schema()  # provision the authority
            await workspaces.create(creator_user_id="u1", name="Real", workspace_id="ws-real")

            root = await scope.create_root("ws-real")
            assert root.workspace_id == "ws-real"
            with pytest.raises(WorkspaceNotFound):
                await scope.create_root("ws-unknown")
            with pytest.raises(ProjectNotFound):
                await scope.root_for_workspace("ws-unknown")
        finally:
            await conn.close()

    async def test_a_deleted_workspace_is_refused_on_the_same_connection(self, tmp_path) -> None:
        from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

        conn, scope = await self._store(tmp_path)
        try:
            workspaces = SqliteWorkspaceStore(conn, project_store=scope)
            await workspaces.ensure_schema()
            workspace = await workspaces.create(
                creator_user_id="u1", name="Doomed", workspace_id="ws-doomed"
            )
            await workspaces.delete(workspace.workspace_id, principal_id="u1")

            with pytest.raises(WorkspaceNotFound):
                await scope.create_root("ws-doomed")
        finally:
            await conn.close()

    async def test_a_database_with_no_workspace_authority_is_not_refused(self, tmp_path) -> None:
        """The bootstrap escape: no `canonical_workspaces` table, no authority
        to consult — the pre-#37 behaviour on a database that has never owned
        a Workspace. The wired container provisions the authority before the
        first admission, so production never leans on this branch; see the
        module docstring."""
        conn, scope = await self._store(tmp_path)
        try:
            async with conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='canonical_workspaces'"
            ) as cursor:
                assert await cursor.fetchone() is None

            root = await scope.create_root("ws-unprovisioned")
            assert root.workspace_id == "ws-unprovisioned"
        finally:
            await conn.close()

    async def test_an_operational_error_that_is_not_the_missing_table_propagates(self) -> None:
        """A real database fault is not the bootstrap escape.

        `_workspace_row` reads exactly one OperationalError as "no authority
        provisioned yet": the missing `canonical_workspaces` table. Any other
        OperationalError — a locked database, an I/O failure — must
        propagate. Swallowing it into the None answer would misread a
        mid-fault database as never-provisioned and mint a Root under an id
        nothing verified.
        """
        import sqlite3

        class _FaultingConn:
            # aiosqlite's `execute` returns the cursor awaitable without
            # awaiting, so the fault must fire on the call itself.
            def execute(self, *_args: object, **_kwargs: object) -> object:
                raise sqlite3.OperationalError("database is locked")

        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            await SqliteProjectScopeStore._workspace_row(_FaultingConn(), "ws-any")
