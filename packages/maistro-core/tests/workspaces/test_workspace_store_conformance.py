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

    async def close(self) -> None:
        for conn in self._connections:
            await conn.close()


class _PostgresBackend:
    """A migrated database; each `store()` is a new object on the same pool."""

    supports_concurrent_writers = True

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
        """The Root Project is another store's write and cannot join the
        Workspace's transaction, so `create` compensates. A Workspace without
        one is a Workspace whose Runs can never be filed, which is worse than
        no Workspace at all."""
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
