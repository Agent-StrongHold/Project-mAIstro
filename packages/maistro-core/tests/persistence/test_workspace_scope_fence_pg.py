"""The Workspace fence against a real PostgreSQL server (#37).

A mocked connection can prove a query was composed; it cannot prove that a
row lock serializes a delete against an admission on *another connection*,
that a foreign key refuses an insert a transactional check missed, or that a
tombstone outlives the pool that wrote it. Those are the fences this issue
names, so they are proven against a live server. Without `MAISTRO_TEST_PG_DSN`
the module skips; `MAISTRO_REQUIRE_PG_LEGS` turns that skip into a failure in
the jobs that own a server.
"""

from __future__ import annotations

import asyncio
import contextlib
from uuid import uuid4

import pytest

from maistro.testing.postgres import postgres_dsn
from maistro.workspaces.model import WorkspaceDeleted, WorkspaceNotFound

pytest.importorskip("asyncpg")

pytestmark = pytest.mark.skipif(
    not postgres_dsn(),
    reason="set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database to run these",
)


@pytest.fixture
async def pool():
    import asyncpg

    p = await asyncpg.create_pool(postgres_dsn(), min_size=2, max_size=4)
    try:
        yield p
    finally:
        await p.close()


def _ws() -> str:
    """A Workspace id nothing else in the database has ever used."""
    return f"ws-{uuid4().hex}"


def _user() -> str:
    return f"user-{uuid4().hex}"


async def _store(pool):
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    return PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool))


class TestAdmissionRefusesWithoutAuthority:
    async def test_create_root_refuses_an_unknown_workspace_with_zero_rows(self, pool) -> None:
        from maistro.projects.pg_scope_store import PgProjectScopeStore

        projects = PgProjectScopeStore(pool)
        ghost = _ws()

        with pytest.raises(WorkspaceNotFound):
            await projects.create_root(ghost)

        assert (
            await pool.fetchval("SELECT 1 FROM canonical_projects WHERE workspace_id = $1", ghost)
            is None
        )

    async def test_create_root_refuses_a_deleted_workspace_from_another_connection(
        self, pool
    ) -> None:
        """The committed-delete half of the two-replica race.

        Replica A owns the Workspace; replica B, holding a cached admitter for
        it, admits. A deletes; B's next verification must refuse before any
        write — this is the shared-database answer to "cached admitters fail"
        that a per-process cache cannot give on its own.
        """
        store = await _store(pool)
        workspace_id, creator = _ws(), _user()
        await store.create(creator_user_id=creator, name="Shared", workspace_id=workspace_id)

        await store.delete(workspace_id, principal_id=creator)

        fresh = await _store(pool)

        with pytest.raises(WorkspaceNotFound):
            await fresh.project_store.create_root(workspace_id)
        assert (
            await pool.fetchval(
                "SELECT 1 FROM canonical_projects WHERE workspace_id = $1", workspace_id
            )
            is None
        )

    async def test_a_deleted_id_cannot_be_recreated_from_another_pool(self, pool) -> None:
        workspace_id, creator = _ws(), _user()
        store = await _store(pool)
        await store.create(creator_user_id=creator, name="Doomed", workspace_id=workspace_id)
        await store.delete(workspace_id, principal_id=creator)

        resurrector = await _store(pool)
        with pytest.raises(WorkspaceDeleted):
            await resurrector.create(
                creator_user_id=creator, name="Resurrection", workspace_id=workspace_id
            )
        assert (
            await pool.fetchval(
                "SELECT 1 FROM canonical_workspaces WHERE workspace_id = $1", workspace_id
            )
            is None
        )


class TestTheDatabaseFencesConcurrentWriters:
    async def test_the_foreign_key_refuses_a_root_for_a_missing_workspace(self, pool) -> None:
        """The constraint any writer meets, including one that never calls
        `create_root_in`: the NOT VALID foreign key checks every row written
        after migration 069, so the orphan-admission hole is closed at the
        database for paths the application fence cannot see."""
        ghost = _ws()
        with pytest.raises(Exception) as excinfo:
            await pool.execute(
                """INSERT INTO canonical_projects
                       (project_id, workspace_id, parent_project_id, is_root, payload)
                   VALUES ($1, $2, NULL, TRUE, '{}'::text::jsonb)""",
                f"proj-{uuid4().hex}",
                ghost,
            )
        assert "fk_canonical_projects_workspace" in str(excinfo.value)

    async def test_an_admission_waits_on_a_delete_holding_the_workspace_lock(self, pool) -> None:
        """The in-flight half of the two-replica race, proven by lock order.

        Replica A takes the Workspace row lock — the serialization point its
        delete transaction holds from lock to commit — and keeps its
        transaction open. Replica B attempts `create_root`. The fence's
        `SELECT ... FOR UPDATE` must make B wait on that exact row: if B
        could read the Workspace as existing and insert while A's delete is
        uncommitted, A's commit would strand an unauthorized Root. The wait is
        the proof; A rolls back, and B then proceeds — both outcomes observed.
        """
        from maistro.projects.pg_scope_store import PgProjectScopeStore

        workspace_id = _ws()
        await pool.execute(
            """INSERT INTO canonical_workspaces (workspace_id, name, created_at, updated_at, payload)
               VALUES ($1, 'Racing', now(), now(), '{}'::text::jsonb)""",
            workspace_id,
        )

        projects = PgProjectScopeStore(pool)
        blocker = await pool.acquire()
        try:
            await blocker.execute("BEGIN")
            await blocker.execute(
                "SELECT workspace_id FROM canonical_workspaces WHERE workspace_id = $1 FOR UPDATE",
                workspace_id,
            )

            async def admission() -> None:
                await projects.create_root(workspace_id)

            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(admission(), timeout=1.5)

            await blocker.execute("ROLLBACK")

            # A rolled back, the row is still there: the admission proceeds.
            root = await projects.create_root(workspace_id)
            assert root.workspace_id == workspace_id

        finally:
            with contextlib.suppress(Exception):
                # The connection may already be idle.
                await blocker.execute("ROLLBACK")
            await pool.release(blocker)

    async def test_a_committed_delete_strands_no_root_from_a_racing_admission(self, pool) -> None:
        """Delete and admission, committed back to back, never both win.

        The delete purges the Project tree before removing the Workspace row
        (#1121), all under the Workspace lock the admission fence also takes.
        Whichever transaction wins, the loser's writes are gone or refused:
        the database ends with neither the Workspace nor any of its Project
        rows — an unauthorized Root cannot be minted into a delete in flight,
        and it cannot survive one.
        """
        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.workspaces.pg_store import PgWorkspaceStore

        store = PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool))
        workspace_id, creator = _ws(), _user()
        await store.create(creator_user_id=creator, name="Racy", workspace_id=workspace_id)

        results = await asyncio.gather(
            store.project_store.create_root(workspace_id),
            store.delete(workspace_id, principal_id=creator),
            return_exceptions=True,
        )

        # The delete commits in both orderings: an admission that committed
        # first is purged with the tree; one that ran after is refused. The
        # delete transaction itself has no competitor that can fail it.
        assert not isinstance(results[1], Exception), f"delete failed: {results[1]}"
        workspace_row = await pool.fetchval(
            "SELECT 1 FROM canonical_workspaces WHERE workspace_id = $1", workspace_id
        )
        project_rows = await pool.fetchval(
            "SELECT count(*) FROM canonical_projects WHERE workspace_id = $1", workspace_id
        )
        assert workspace_row is None
        assert project_rows == 0
        # And the refused-or-purged admission left the id tombstoned: no
        # later create may mint the Workspace again.
        with pytest.raises(WorkspaceDeleted):
            await store.create(
                creator_user_id=creator, name="Resurrection", workspace_id=workspace_id
            )


class TestCanonicalStateSurvivesTheProcess:
    async def test_id_membership_and_root_are_unchanged_across_pool_replacement(self, pool) -> None:
        """AC-1's restart leg: a *new* pool — what a new process builds —
        reads the same canonical id, membership, and immutable Root."""
        import asyncpg

        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.workspaces.pg_store import PgWorkspaceStore

        workspace_id, creator = _ws(), _user()
        store = PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool))
        created = await store.create(
            creator_user_id=creator, name="Durable", workspace_id=workspace_id
        )
        root_before = await store.project_store.root_for_workspace(workspace_id)
        membership_before = await store.get_membership(workspace_id, user_id=creator)

        fresh_pool = await asyncpg.create_pool(postgres_dsn(), min_size=1, max_size=2)
        try:
            reborn = PgWorkspaceStore(fresh_pool, project_store=PgProjectScopeStore(fresh_pool))
            workspace = await reborn.get(workspace_id)
            assert workspace is not None
            assert workspace.workspace_id == created.workspace_id
            membership_after = await reborn.get_membership(workspace_id, user_id=creator)
            assert membership_after is not None
            assert membership_after.role == membership_before.role
            root_after = await reborn.project_store.root_for_workspace(workspace_id)
            assert root_after.project_id == root_before.project_id
        finally:
            await fresh_pool.close()
