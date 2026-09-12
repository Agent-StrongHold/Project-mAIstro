"""One suite over all three Workspace stores (#516).

`InMemoryWorkspaceStore` was the only implementation, so every rule it holds --
the owner-of-last-resort refusal, the membership orderings, the compensating
delete when the Root Project fails -- was a rule of the reference and of
nothing else. A durable twin that agrees with it only in its docstring is the
state `PgStrikeTracker` was in when #134 found it unusable, so the bodies below
run against all three: the reference, SQLite, and PostgreSQL.

The in-memory leg is in the same suite rather than in a file of its own on
purpose. It is the definition of the contract; running it here is what makes
"the durable stores behave like the reference" a comparison rather than an
assertion.

The PostgreSQL leg needs a real migrated server and skips without one, and a
skipped leg is untested rather than passing. `MAISTRO_REQUIRE_PG_LEGS` turns
that skip into a failure in the jobs that own a server.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC
from uuid import uuid4

import pytest

from maistro.projects.scope import ProjectNotFound, ProjectScopeDenied
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.testing.postgres import postgres_dsn
from maistro.workspaces.model import (
    WorkspaceAccessDenied,
    WorkspaceNotFound,
    WorkspaceRole,
)


class _MemoryBackend:
    """The reference. Every `store()` is the same object, because an in-memory
    store *is* its own substrate -- a second instance would share nothing, which
    would make the reopen assertions vacuously false rather than meaningfully
    true."""

    supports_concurrent_writers = False
    supports_lifecycle_recovery = False

    def __init__(self) -> None:
        from maistro.workspaces.store import InMemoryWorkspaceStore

        self._store = InMemoryWorkspaceStore(project_store=InMemoryProjectScopeStore())

    async def store(self):
        return self._store

    async def close(self) -> None:
        return None


class _SqliteBackend:
    """A file on disk; each `store()` opens its own connection to it."""

    supports_concurrent_writers = False
    supports_lifecycle_recovery = True

    def __init__(self, tmp_path) -> None:
        self._path = tmp_path / "workspaces.db"
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

    async def independent_project_store(self):
        import aiosqlite

        from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore

        conn = await aiosqlite.connect(self._path)
        self._connections.append(conn)
        store = SqliteProjectScopeStore(conn)
        await store.ensure_schema()
        return store

    def purge_refusal(self) -> Exception:
        """What the driver raises when a foreign key keeps the Project tree."""
        import sqlite3

        return sqlite3.IntegrityError("FOREIGN KEY constraint failed")

    async def insert_pre_journal_workspace(self, workspace, owner) -> None:
        """Write the rows an older release wrote: no lifecycle journal row."""
        import aiosqlite

        from maistro.workspaces.sqlite_store import _iso

        conn = await aiosqlite.connect(self._path)
        self._connections.append(conn)
        await conn.execute(
            """INSERT INTO canonical_workspaces
                   (workspace_id, name, created_at, updated_at, payload)
               VALUES (?, ?, ?, ?, ?)""",
            (
                workspace.workspace_id,
                workspace.name,
                _iso(workspace.created_at),
                _iso(workspace.updated_at),
                workspace.model_dump_json(),
            ),
        )
        await conn.execute(
            """INSERT INTO canonical_workspace_memberships
                   (workspace_id, user_id, role, added_at, payload)
               VALUES (?, ?, ?, ?, ?)""",
            (
                owner.workspace_id,
                owner.user_id,
                owner.role.value,
                _iso(owner.added_at),
                owner.model_dump_json(),
            ),
        )
        await conn.commit()

    async def close(self) -> None:
        for conn in self._connections:
            await conn.close()


class _PostgresBackend:
    """A migrated database; each `store()` is a new object on the same pool."""

    supports_concurrent_writers = True
    supports_lifecycle_recovery = True

    def __init__(self, pool) -> None:
        self._pool = pool

    async def store(self):
        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.workspaces.pg_store import PgWorkspaceStore

        store = PgWorkspaceStore(self._pool, project_store=PgProjectScopeStore(self._pool))
        await store.recover()
        return store

    async def independent_project_store(self):
        from maistro.projects.pg_scope_store import PgProjectScopeStore

        return PgProjectScopeStore(self._pool)

    def purge_refusal(self) -> Exception:
        """What asyncpg raises when `canonical_runs.project_id` RESTRICTs the purge."""
        import asyncpg

        return asyncpg.ForeignKeyViolationError(
            'update or delete on table "canonical_projects" violates foreign key constraint'
        )

    async def insert_pre_journal_workspace(self, workspace, owner) -> None:
        """Write the rows an older release wrote, bypassing the store's staging."""
        from maistro.runs.evidence_json import json_of

        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """INSERT INTO canonical_workspaces
                       (workspace_id, name, created_at, updated_at, payload)
                   VALUES ($1, $2, $3, $4, $5::text::jsonb)""",
                workspace.workspace_id,
                workspace.name,
                workspace.created_at,
                workspace.updated_at,
                json_of(workspace),
            )
            await conn.execute(
                """INSERT INTO canonical_workspace_memberships
                       (workspace_id, user_id, role, added_at, payload)
                   VALUES ($1, $2, $3, $4, $5::text::jsonb)""",
                owner.workspace_id,
                owner.user_id,
                owner.role.value,
                owner.added_at,
                json_of(owner),
            )

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
                "the PostgreSQL Workspace-store leg cannot run and must not be "
                "silently skipped"
            )
            raise RuntimeError(msg)
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")

    asyncpg = pytest.importorskip("asyncpg")
    # `min_size=2`, not 1. asyncpg's pool hands out the connections it has and
    # queues the rest, so a one-connection pool serialises every caller by
    # itself -- and the concurrency test below then passes with the row lock
    # removed, proving only that the pool was the bottleneck. Two connections
    # is the smallest number at which "do two writers race" is a question this
    # fixture can ask.
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=4)
    try:
        yield _PostgresBackend(pool)
    finally:
        await pool.close()


#: How long the owner check is held open in the race test below. Long enough
#: that two sub-millisecond transactions overlap inside it with room to spare,
#: short enough that the test costs a blink.
_RACE_WINDOW_SECONDS = 0.25


def _user(label: str = "") -> str:
    """A user id nothing else in the database has used.

    PostgreSQL keeps its rows between tests and between runs -- that is the
    point of it -- so a fixed id would inherit memberships an earlier run made.
    """
    return f"user-{label}{uuid4().hex}"


class TestIdentityAndMembershipSurviveTheObjectThatWroteThem:
    async def test_a_workspace_its_owner_and_its_root_project_are_readable_from_a_fresh_store(
        self, backend
    ) -> None:
        creator = _user("creator-")
        first = await backend.store()

        workspace = await first.create(creator_user_id=creator, name="Engineering")

        second = await backend.store()
        reloaded = await second.get(workspace.workspace_id)
        membership = await second.get_membership(workspace.workspace_id, user_id=creator)
        root = await second.project_store.root_for_workspace(workspace.workspace_id)

        assert reloaded is not None
        assert reloaded.workspace_id == workspace.workspace_id
        assert reloaded.name == "Engineering"
        assert membership is not None
        assert membership.role is WorkspaceRole.OWNER
        assert root.workspace_id == workspace.workspace_id
        assert root.is_root

    async def test_timestamps_come_back_timezone_aware_in_utc(self, backend) -> None:
        """A naive column reads back as a value that compares unequal to what
        was written, and the model builds every timestamp with `datetime.now(UTC)`."""
        first = await backend.store()
        workspace = await first.create(creator_user_id=_user(), name="Timestamps")

        reloaded = await (await backend.store()).get(workspace.workspace_id)

        assert reloaded is not None
        assert reloaded.created_at.tzinfo is not None
        assert reloaded.created_at.utcoffset() == UTC.utcoffset(None)
        assert reloaded.created_at == workspace.created_at

    async def test_update_persists_and_moves_updated_at_forward(self, backend) -> None:
        first = await backend.store()
        workspace = await first.create(creator_user_id=_user(), name="Before")

        renamed = await first.update(workspace.model_copy(update={"name": "After"}))
        reloaded = await (await backend.store()).get(workspace.workspace_id)

        assert renamed.name == "After"
        assert renamed.updated_at >= workspace.updated_at
        assert reloaded is not None
        assert reloaded.name == "After"

    async def test_delete_removes_the_workspace_and_cascades_its_memberships(self, backend) -> None:
        creator = _user("creator-")
        first = await backend.store()
        workspace = await first.create(creator_user_id=creator, name="Doomed")

        await first.delete(workspace.workspace_id)

        second = await backend.store()
        assert await second.get(workspace.workspace_id) is None
        # Reached through the membership accessor rather than by counting rows,
        # because the cascade is the durable stores' and the loop is the
        # reference's -- the question is whether the membership is gone, not how.
        with pytest.raises(WorkspaceNotFound):
            await second.get_membership(workspace.workspace_id, user_id=creator)

    async def test_delete_purges_the_whole_project_tree_it_owns(self, backend) -> None:
        """The clause `delete`'s contract states and no durable store honoured.

        `purge_workspace` was reached through
        `getattr(store, "purge_workspace", None)`, and only the in-memory
        reference defined it. So this passed on the reference and silently did
        nothing on PostgreSQL and SQLite, leaving the Project tree, its
        memberships and its scoped resources behind with no Workspace to reach
        them by (Codex, #516).

        A *nested* child, not just the Root Project: both schemas declare
        `ON DELETE RESTRICT` on the self-referencing parent link, so a purge
        that deletes in the wrong order fails on the parent rather than
        silently under-deleting. One level is enough to tell those apart.
        """
        from maistro.projects.scope import ProjectMembership, ProjectScopedResource

        creator = _user("creator-")
        first = await backend.store()
        workspace = await first.create(creator_user_id=creator, name="Doomed")
        projects = first.project_store

        root = await projects.root_for_workspace(workspace.workspace_id)
        child = await projects.create(
            workspace_id=workspace.workspace_id,
            parent_project_id=root.project_id,
            name="Child",
        )
        await projects.set_membership(
            ProjectMembership(
                workspace_id=workspace.workspace_id,
                project_id=child.project_id,
                principal_id=creator,
            )
        )
        await projects.put_resource(
            ProjectScopedResource(
                resource_id=f"res-{uuid4().hex[:8]}",
                workspace_id=workspace.workspace_id,
                project_id=child.project_id,
                resource_type="secret",
            )
        )

        await first.delete(workspace.workspace_id)

        second = await backend.store()
        assert await second.get(workspace.workspace_id) is None
        # Read back through the Project store rather than by counting rows: the
        # question is whether anything can still reach them.
        assert await second.project_store.get(child.project_id) is None
        assert await second.project_store.get(root.project_id) is None


class TestWorkspaceLifecycleRecovery:
    async def test_restart_completes_creation_after_the_workspace_boundary(self, backend) -> None:
        """A committed `creating` row is not visible until recovery has a Root."""
        if not backend.supports_lifecycle_recovery:
            pytest.skip("the in-memory reference has no durable restart boundary")

        from maistro.workspaces.model import Workspace, WorkspaceMembership

        store = await backend.store()
        workspace = Workspace(name="Interrupted create")
        owner = WorkspaceMembership(
            workspace_id=workspace.workspace_id,
            user_id=_user("creator-"),
            role=WorkspaceRole.OWNER,
            added_at=workspace.created_at,
        )
        # This is the durable commit boundary in create(); stopping here is the
        # failure a process crash creates before the Root Project write.
        await store._stage_workspace_create(workspace, owner)
        assert await store.get(workspace.workspace_id) is None
        with pytest.raises(ProjectNotFound):
            await store.project_store.root_for_workspace(workspace.workspace_id)

        recovered = await backend.store()
        assert await recovered.get(workspace.workspace_id) is not None
        root = await recovered.project_store.root_for_workspace(workspace.workspace_id)
        assert root.workspace_id == workspace.workspace_id
        assert root.is_root

    async def test_restart_rolls_back_visible_workspace_when_root_is_missing(self, backend) -> None:
        """A pre-journal active orphan is rolled back, never given a new root."""
        if not backend.supports_lifecycle_recovery:
            pytest.skip("the in-memory reference has no durable restart boundary")

        from maistro.workspaces.model import Workspace, WorkspaceMembership

        store = await backend.store()
        workspace = Workspace(name="Legacy orphan")
        owner = WorkspaceMembership(
            workspace_id=workspace.workspace_id,
            user_id=_user("creator-"),
            role=WorkspaceRole.OWNER,
            added_at=workspace.created_at,
        )
        # An older database had no lifecycle row, so migration would mark this
        # committed Workspace active even though its Root Project was missing.
        await store._stage_workspace_create(workspace, owner)
        await store._set_state(workspace.workspace_id, store._ACTIVE)
        assert await store.get(workspace.workspace_id) is not None
        with pytest.raises(ProjectNotFound):
            await store.project_store.root_for_workspace(workspace.workspace_id)

        recovered = await backend.store()
        assert await recovered.get(workspace.workspace_id) is None
        with pytest.raises(ProjectNotFound):
            await recovered.project_store.root_for_workspace(workspace.workspace_id)

    async def test_durable_creation_recovers_when_compensation_also_fails(self, backend) -> None:
        """A failed compensator leaves a staged row for restart reconciliation."""
        if not backend.supports_lifecycle_recovery:
            pytest.skip("the in-memory reference has no durable restart boundary")

        store = await backend.store()
        original_create_root = store.project_store.create_root
        original_purge = store.project_store.purge_workspace
        seen: list[str] = []

        async def fail_create_root(workspace_id: str) -> None:
            seen.append(workspace_id)
            raise RuntimeError(f"root failed for {workspace_id}")

        async def fail_purge(workspace_id: str) -> None:
            raise RuntimeError(f"purge failed for {workspace_id}")

        store.project_store.create_root = fail_create_root  # type: ignore[method-assign]
        store.project_store.purge_workspace = fail_purge  # type: ignore[method-assign]
        try:
            with pytest.raises(RuntimeError, match="root failed"):
                await store.create(creator_user_id=_user("creator-"), name="Staged failure")
        finally:
            store.project_store.create_root = original_create_root  # type: ignore[method-assign]
            store.project_store.purge_workspace = original_purge  # type: ignore[method-assign]

        recovered = await backend.store()
        # The failed compensator left the identity in `creating`; recovery
        # must finish it with the original Workspace ID rather than erase it.
        assert len(seen) == 1
        staged = await recovered.get(seen[0])
        assert staged is not None
        root = await recovered.project_store.root_for_workspace(seen[0])
        assert root.workspace_id == seen[0]

    async def test_sqlite_lifecycle_write_failures_rollback(self, backend) -> None:
        """SQLite's helper failures roll back and leave a retryable database."""
        store = await backend.store()
        if type(store).__name__ != "SqliteWorkspaceStore":
            pytest.skip("this exercises SQLite transaction rollback details")

        with pytest.raises(WorkspaceNotFound):
            await store._set_state("missing", store._ACTIVE)

        workspace = await store.create(creator_user_id=_user("creator-"), name="Rollback")
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            await store.create(
                creator_user_id=_user("duplicate-"),
                name="Duplicate",
                workspace_id=workspace.workspace_id,
            )
        assert await store.get(workspace.workspace_id) is not None

        await store._set_state_if_active(workspace.workspace_id, store._DELETING)
        original_execute = store._conn.execute

        async def fail_final_delete(sql, *args, **kwargs):
            if isinstance(sql, str) and sql.lstrip().startswith("DELETE FROM canonical_workspaces"):
                raise RuntimeError("final delete failed")
            return await original_execute(sql, *args, **kwargs)

        store._conn.execute = fail_final_delete  # type: ignore[method-assign]
        try:
            with pytest.raises(RuntimeError, match="final delete failed"):
                await store._delete_workspace(workspace.workspace_id, store._DELETING)
        finally:
            store._conn.execute = original_execute  # type: ignore[method-assign]

        recovered = await backend.store()
        assert await recovered.get(workspace.workspace_id) is None
        with pytest.raises(ProjectNotFound):
            await recovered.project_store.root_for_workspace(workspace.workspace_id)

    async def test_restart_finishes_delete_when_project_purge_failed_before_it(
        self, backend
    ) -> None:
        if not backend.supports_lifecycle_recovery:
            pytest.skip("the in-memory reference has no durable restart boundary")

        store = await backend.store()
        workspace = await store.create(creator_user_id=_user("creator-"), name="Interrupted delete")
        original = store.project_store.purge_workspace

        async def fail_purge(workspace_id: str) -> None:
            raise RuntimeError(f"purge failed for {workspace_id}")

        store.project_store.purge_workspace = fail_purge  # type: ignore[method-assign]
        try:
            with pytest.raises(RuntimeError, match="purge failed"):
                await store.delete(workspace.workspace_id)
        finally:
            store.project_store.purge_workspace = original  # type: ignore[method-assign]

        assert await store.get(workspace.workspace_id) is None
        recovered = await backend.store()
        assert await recovered.get(workspace.workspace_id) is None
        with pytest.raises(ProjectNotFound):
            await recovered.project_store.root_for_workspace(workspace.workspace_id)

    async def test_failed_purge_quarantines_projects_until_restart_recovery(self, backend) -> None:
        """A deleting Workspace cannot admit Project reads or writes."""
        if not backend.supports_lifecycle_recovery:
            pytest.skip("the in-memory reference has no durable restart boundary")

        store = await backend.store()
        workspace = await store.create(creator_user_id=_user("creator-"), name="Quarantine")
        root = await store.project_store.root_for_workspace(workspace.workspace_id)
        original = store.project_store.purge_workspace

        async def fail_purge(workspace_id: str) -> None:
            raise RuntimeError(f"purge failed for {workspace_id}")

        store.project_store.purge_workspace = fail_purge  # type: ignore[method-assign]
        try:
            with pytest.raises(RuntimeError, match="purge failed"):
                await store.delete(workspace.workspace_id)

            with pytest.raises(ProjectScopeDenied, match="not active"):
                await store.project_store.root_for_workspace(workspace.workspace_id)
            with pytest.raises(ProjectScopeDenied, match="not active"):
                await store.project_store.get(root.project_id)
            with pytest.raises(ProjectScopeDenied, match="not active"):
                await store.project_store.create(
                    workspace_id=workspace.workspace_id,
                    parent_project_id=root.project_id,
                    name="must not be admitted",
                )

            # A separately constructed durable Project store must consult the
            # database journal itself; the Workspace store's callback is not an
            # authorization boundary.
            independent = await backend.independent_project_store()
            with pytest.raises(ProjectScopeDenied, match="not active"):
                await independent.root_for_workspace(workspace.workspace_id)
            with pytest.raises(ProjectScopeDenied, match="not active"):
                await independent.create(
                    workspace_id=workspace.workspace_id,
                    parent_project_id=root.project_id,
                    name="independent store must not admit",
                )
        finally:
            store.project_store.purge_workspace = original  # type: ignore[method-assign]

        recovered = await backend.store()
        assert await recovered.get(workspace.workspace_id) is None
        assert await recovered.project_store.get(root.project_id) is None

    async def test_restart_finishes_delete_after_project_purge_before_workspace_delete(
        self, backend
    ) -> None:
        if not backend.supports_lifecycle_recovery:
            pytest.skip("the in-memory reference has no durable restart boundary")

        store = await backend.store()
        workspace = await store.create(creator_user_id=_user("creator-"), name="Interrupted delete")
        original = store._delete_workspace

        async def fail_finalize(workspace_id: str, state: str) -> None:
            raise RuntimeError(f"finalize failed for {workspace_id}")

        store._delete_workspace = fail_finalize  # type: ignore[method-assign]
        try:
            with pytest.raises(RuntimeError, match="finalize failed"):
                await store.delete(workspace.workspace_id)
        finally:
            store._delete_workspace = original  # type: ignore[method-assign]

        assert await store.get(workspace.workspace_id) is None
        recovered = await backend.store()
        assert await recovered.get(workspace.workspace_id) is None
        with pytest.raises(ProjectNotFound):
            await recovered.project_store.root_for_workspace(workspace.workspace_id)


class TestLifecycleUnderRefusalsAndRaces:
    """The #1121 review cases: a refused purge, a rollback over an imported
    tree, recovery racing the creator's compensator, and a pre-journal writer.
    """

    async def test_a_workspace_whose_history_cannot_be_purged_is_restored_not_stuck(
        self, backend, monkeypatch
    ) -> None:
        """`ON DELETE RESTRICT` on Run history is an answer, not an interruption.

        Left `deleting`, the Workspace would be hidden for good and every
        startup would fail on the same purge. Both the request path and the
        recovery path put it back to `active` instead.
        """
        if not backend.supports_lifecycle_recovery:
            pytest.skip("the in-memory reference has no durable restart boundary")

        from maistro.workspaces.model import WorkspaceRetainsHistory

        store = await backend.store()
        workspace = await store.create(creator_user_id=_user("creator-"), name="Has history")
        root = await store.project_store.root_for_workspace(workspace.workspace_id)
        refusal = backend.purge_refusal()

        async def refuse(_self, workspace_id: str) -> None:
            raise refusal

        monkeypatch.setattr(type(store.project_store), "purge_workspace", refuse)

        with pytest.raises(WorkspaceRetainsHistory, match="must be retained"):
            await store.delete(workspace.workspace_id)
        assert await store.get(workspace.workspace_id) is not None
        assert (
            await store.project_store.root_for_workspace(workspace.workspace_id)
        ).project_id == root.project_id

        # A crash after the journal write leaves `deleting`; recovery meets the
        # same refusal and restores the Workspace rather than failing startup.
        await store._set_state_if_active(workspace.workspace_id, store._DELETING)
        assert await store.get(workspace.workspace_id) is None
        recovered = await backend.store()
        assert await recovered.get(workspace.workspace_id) is not None
        assert (
            await recovered.project_store.root_for_workspace(workspace.workspace_id)
        ).project_id == root.project_id

    async def test_create_rollback_keeps_a_pre_existing_project_tree(
        self, backend, monkeypatch
    ) -> None:
        """A convergence import over a legacy tree fails without eating the tree."""
        if not backend.supports_lifecycle_recovery:
            pytest.skip("the in-memory reference has no durable restart boundary")

        store = await backend.store()
        workspace_id = f"legacy-{uuid4().hex}"
        root = await store.project_store.create_root(workspace_id)
        child = await store.project_store.create(
            workspace_id=workspace_id, parent_project_id=root.project_id, name="Imported child"
        )

        async def refuse_activation(_workspace_id: str) -> None:
            raise RuntimeError("journal write failed")

        monkeypatch.setattr(store, "_activate", refuse_activation)
        with pytest.raises(RuntimeError, match="journal write failed"):
            await store.create(
                creator_user_id=_user("importer-"), name="Imported", workspace_id=workspace_id
            )

        assert await store.get(workspace_id) is None
        assert await store.project_store.get(root.project_id) is not None
        assert await store.project_store.get(child.project_id) is not None
        recovered = await backend.store()
        assert await recovered.get(workspace_id) is None
        assert await recovered.project_store.get(child.project_id) is not None

    async def test_recovery_does_not_orphan_a_root_after_the_creator_compensated(
        self, backend, monkeypatch
    ) -> None:
        """Recovery read `creating`; the creator rolled back before it acted.

        Recovery's Root must not survive as an orphan, and its activation must
        not resurrect a Workspace the creator removed.
        """
        if not backend.supports_lifecycle_recovery:
            pytest.skip("the in-memory reference has no durable restart boundary")

        from maistro.workspaces.model import Workspace, WorkspaceMembership

        creator = await backend.store()
        workspace = Workspace(name="Raced create")
        owner = WorkspaceMembership(
            workspace_id=workspace.workspace_id,
            user_id=_user("creator-"),
            role=WorkspaceRole.OWNER,
            added_at=workspace.created_at,
        )
        await creator._stage_workspace_create(workspace, owner)
        scope_cls = type(creator.project_store)
        original_create_root = scope_cls.create_root

        async def compensate_then_create(self_store, workspace_id: str):
            if workspace_id == workspace.workspace_id:
                # The creator's compensator wins after recovery took its snapshot.
                await creator._compensate_staged_create(workspace_id, purge_projects=True)
            return await original_create_root(self_store, workspace_id)

        monkeypatch.setattr(scope_cls, "create_root", compensate_then_create)
        recovered = await backend.store()

        assert await recovered.get(workspace.workspace_id) is None
        with pytest.raises(ProjectNotFound):
            await recovered.project_store.root_for_workspace(workspace.workspace_id)

    async def test_a_creator_steps_aside_when_recovery_activated_first(
        self, backend, monkeypatch
    ) -> None:
        """The other order of the same race: the row is active, so the
        compensator must not purge the Root recovery just gave it."""
        if not backend.supports_lifecycle_recovery:
            pytest.skip("the in-memory reference has no durable restart boundary")

        store = await backend.store()
        seen: list[str] = []
        original_activate = store._activate

        async def recovered_elsewhere_then_fail(workspace_id: str) -> None:
            seen.append(workspace_id)
            # Another replica's recovery completed the row before this write.
            await original_activate(workspace_id)
            raise RuntimeError("this replica lost its connection")

        monkeypatch.setattr(store, "_activate", recovered_elsewhere_then_fail)
        with pytest.raises(RuntimeError, match="lost its connection"):
            await store.create(creator_user_id=_user("creator-"), name="Finished elsewhere")

        (workspace_id,) = seen
        assert await store.get(workspace_id) is not None
        root = await store.project_store.root_for_workspace(workspace_id)
        assert root.is_root

    async def test_a_pre_journal_writer_s_workspace_becomes_visible(self, backend) -> None:
        """A row an older release wrote without a journal entry is not lost."""
        if not backend.supports_lifecycle_recovery:
            pytest.skip("the in-memory reference has no durable restart boundary")

        from maistro.workspaces.model import Workspace, WorkspaceMembership

        store = await backend.store()
        workspace = Workspace(name="Older writer")
        owner = WorkspaceMembership(
            workspace_id=workspace.workspace_id,
            user_id=_user("creator-"),
            role=WorkspaceRole.OWNER,
            added_at=workspace.created_at,
        )
        await backend.insert_pre_journal_workspace(workspace, owner)
        await store.project_store.create_root(workspace.workspace_id)

        recovered = await backend.store()
        assert await recovered.get(workspace.workspace_id) is not None
        assert (
            await recovered.get_membership(workspace.workspace_id, user_id=owner.user_id)
            is not None
        )


class TestTheRosterOrderingsTheProtocolPromises:
    async def test_list_for_user_returns_only_that_users_workspaces_newest_first(
        self, backend
    ) -> None:
        member = _user("member-")
        stranger = _user("stranger-")
        store = await backend.store()

        older = await store.create(creator_user_id=member, name="Older")
        newer = await store.create(creator_user_id=member, name="Newer")
        await store.create(creator_user_id=stranger, name="Not theirs")

        listed = await store.list_for_user(member)

        assert [item.workspace_id for item in listed] == [
            newer.workspace_id,
            older.workspace_id,
        ]

    async def test_list_memberships_orders_by_added_at_then_user_id(self, backend) -> None:
        creator = _user("a-creator-")
        store = await backend.store()
        workspace = await store.create(creator_user_id=creator, name="Roster")

        second = _user("b-")
        third = _user("c-")
        await store.set_membership(
            workspace.workspace_id, user_id=second, role=WorkspaceRole.CONTRIBUTOR
        )
        await store.set_membership(workspace.workspace_id, user_id=third, role=WorkspaceRole.MEMBER)

        memberships = await store.list_memberships(workspace.workspace_id)

        assert [item.user_id for item in memberships] == [creator, second, third]
        assert [item.role for item in memberships] == [
            WorkspaceRole.OWNER,
            WorkspaceRole.CONTRIBUTOR,
            WorkspaceRole.MEMBER,
        ]

    async def test_setting_an_existing_membership_keeps_its_original_added_at(
        self, backend
    ) -> None:
        """Otherwise a role change silently reorders the roster."""
        creator = _user("creator-")
        store = await backend.store()
        workspace = await store.create(creator_user_id=creator, name="Promotion")
        member = _user("member-")

        first = await store.set_membership(
            workspace.workspace_id, user_id=member, role=WorkspaceRole.MEMBER
        )
        promoted = await store.set_membership(
            workspace.workspace_id, user_id=member, role=WorkspaceRole.CONTRIBUTOR
        )

        assert promoted.added_at == first.added_at
        assert promoted.role is WorkspaceRole.CONTRIBUTOR


class TestAWorkspaceKeepsAnOwner:
    async def test_the_last_owner_cannot_demote_themselves(self, backend) -> None:
        creator = _user("creator-")
        store = await backend.store()
        workspace = await store.create(creator_user_id=creator, name="Sole owner")

        with pytest.raises(WorkspaceAccessDenied):
            await store.set_membership(
                workspace.workspace_id, user_id=creator, role=WorkspaceRole.MEMBER
            )

        still_owner = await store.get_membership(workspace.workspace_id, user_id=creator)
        assert still_owner is not None
        assert still_owner.role is WorkspaceRole.OWNER

    async def test_the_last_owner_cannot_be_removed(self, backend) -> None:
        creator = _user("creator-")
        store = await backend.store()
        workspace = await store.create(creator_user_id=creator, name="Sole owner")

        with pytest.raises(WorkspaceAccessDenied):
            await store.remove_membership(workspace.workspace_id, user_id=creator)

    async def test_an_owner_may_step_down_once_another_exists(self, backend) -> None:
        creator = _user("creator-")
        successor = _user("successor-")
        store = await backend.store()
        workspace = await store.create(creator_user_id=creator, name="Handover")

        await store.set_membership(
            workspace.workspace_id, user_id=successor, role=WorkspaceRole.OWNER
        )
        await store.remove_membership(workspace.workspace_id, user_id=creator)

        remaining = await store.list_memberships(workspace.workspace_id)
        assert [item.user_id for item in remaining] == [successor]

    async def test_two_concurrent_demotions_cannot_both_win(self, backend) -> None:
        """The rule is about a set, and a read-then-write cannot hold it.

        Two owners demoted at the same moment: both read one *other* owner,
        both consider themselves safe, and the Workspace ends with none -- a
        Workspace no route can administer, produced by two operations that each
        obeyed the rule.

        The interleaving is forced rather than hoped for. `asyncio.gather` alone
        does not reproduce it: each store call is a handful of sub-millisecond
        round trips, so the scheduler runs them back to back and the second
        reads a roster the first has already changed. That version of this test
        passed with the row lock removed, which makes it evidence of nothing.
        So the owner check is held open for a beat. With the lock, the second
        demotion is still waiting on the Workspace row when the first commits,
        and reads the roster it left behind; without it, both read the roster
        inside the same window and both proceed.
        """
        if not backend.supports_concurrent_writers:
            pytest.skip("single-writer backend; the interleaving under test cannot occur")

        from maistro.workspaces.pg_store import PgWorkspaceStore

        first_owner = _user("first-")
        second_owner = _user("second-")
        store = await backend.store()
        workspace = await store.create(creator_user_id=first_owner, name="Race")
        await store.set_membership(
            workspace.workspace_id, user_id=second_owner, role=WorkspaceRole.OWNER
        )

        held = PgWorkspaceStore._require_another_owner

        async def hold_the_check(self, conn, workspace_id, *, excluding_user_id):
            await asyncio.sleep(_RACE_WINDOW_SECONDS)
            await held(self, conn, workspace_id, excluding_user_id=excluding_user_id)

        # Separate store objects so the two writes take separate connections
        # from the pool; one object would serialise them by accident.
        left = await backend.store()
        right = await backend.store()
        PgWorkspaceStore._require_another_owner = hold_the_check  # type: ignore[method-assign]
        try:
            results = await asyncio.gather(
                left.set_membership(
                    workspace.workspace_id, user_id=first_owner, role=WorkspaceRole.MEMBER
                ),
                right.set_membership(
                    workspace.workspace_id, user_id=second_owner, role=WorkspaceRole.MEMBER
                ),
                return_exceptions=True,
            )
        finally:
            PgWorkspaceStore._require_another_owner = held  # type: ignore[method-assign]

        refused = [item for item in results if isinstance(item, WorkspaceAccessDenied)]
        assert len(refused) == 1, results

        owners = [
            item
            for item in await store.list_memberships(workspace.workspace_id)
            if item.role is WorkspaceRole.OWNER
        ]
        assert len(owners) == 1


class TestAnAbsentWorkspaceIsRefusedTheSameWayEverywhere:
    async def test_get_returns_none(self, backend) -> None:
        assert await (await backend.store()).get("no-such-workspace") is None

    @pytest.mark.parametrize(
        "call",
        [
            "list_memberships",
            "get_membership",
            "set_membership",
            "remove_membership",
            "delete",
        ],
    )
    async def test_the_membership_accessors_raise_workspace_not_found(
        self, backend, call: str
    ) -> None:
        store = await backend.store()
        missing = f"no-such-workspace-{uuid4().hex}"
        arguments: dict[str, dict] = {
            "list_memberships": {},
            "get_membership": {"user_id": "someone"},
            "set_membership": {"user_id": "someone", "role": WorkspaceRole.MEMBER},
            "remove_membership": {"user_id": "someone"},
            "delete": {},
        }

        with pytest.raises(WorkspaceNotFound):
            await getattr(store, call)(missing, **arguments[call])

    async def test_update_of_an_absent_workspace_raises(self, backend) -> None:
        from maistro.workspaces.model import Workspace

        store = await backend.store()

        with pytest.raises(WorkspaceNotFound):
            await store.update(Workspace(name="never created"))

    async def test_removing_an_absent_membership_from_a_real_workspace_is_a_no_op(
        self, backend
    ) -> None:
        """Distinct from the case above: the Workspace exists, the membership
        does not, and the reference returns rather than raising."""
        store = await backend.store()
        workspace = await store.create(creator_user_id=_user(), name="Quiet")

        await store.remove_membership(workspace.workspace_id, user_id="never-a-member")


class TestARootProjectFailureLeavesNoWorkspaceBehind:
    async def test_create_rolls_back_when_the_root_project_cannot_be_made(self, backend) -> None:
        """A normal Root Project failure rolls back the staged lifecycle.

        A process crash skips that compensator; the durable lifecycle tests
        above cover the restart path that completes the staged state instead.
        A Workspace without a Root is one whose Runs can never be filed.
        """
        store = await backend.store()
        original = store.project_store.create_root
        seen: list[str] = []

        async def refuse(workspace_id: str):
            seen.append(workspace_id)
            raise RuntimeError("scope store is down")

        store.project_store.create_root = refuse  # type: ignore[method-assign]
        try:
            with pytest.raises(RuntimeError, match="scope store is down"):
                await store.create(creator_user_id=_user(), name="Doomed")
        finally:
            store.project_store.create_root = original  # type: ignore[method-assign]

        assert len(seen) == 1
        second = await backend.store()
        assert await second.get(seen[0]) is None
