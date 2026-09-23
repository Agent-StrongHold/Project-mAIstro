"""WorkspaceAuthorizer: the principal-carrying Workspace access seam (#1150).

Two principals, two Workspaces, every Workspace store backend. The PostgreSQL
leg needs a migrated server and skips without one, unless
`MAISTRO_REQUIRE_PG_LEGS` makes that skip a failure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import uuid4

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.testing.postgres import postgres_dsn
from maistro.workspaces import (
    InMemoryWorkspaceStore,
    WorkspaceAction,
    WorkspaceAuthorizationDenied,
    WorkspaceAuthorizer,
    WorkspaceMembership,
    WorkspaceRole,
    WorkspaceStore,
)


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryWorkspaceStore(project_store=InMemoryProjectScopeStore())
        return

    if request.param == "sqlite":
        import aiosqlite

        from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
        from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

        conn = await aiosqlite.connect(tmp_path / "workspaces.db")
        try:
            scope_store = SqliteProjectScopeStore(conn)
            await scope_store.ensure_schema()
            sqlite_store = SqliteWorkspaceStore(conn, project_store=scope_store)
            await sqlite_store.ensure_schema()
            yield sqlite_store
        finally:
            await conn.close()
        return

    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            raise RuntimeError(
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
                "the PostgreSQL WorkspaceAuthorizer leg must not be silently skipped"
            )
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")

    asyncpg = pytest.importorskip("asyncpg")
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        yield PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool))
    finally:
        await pool.close()


@dataclass
class _World:
    authorizer: WorkspaceAuthorizer
    store: WorkspaceStore
    alice: str
    bob: str
    alice_ws: str
    bob_ws: str


@pytest.fixture
async def world(store: WorkspaceStore) -> _World:
    # PostgreSQL keeps rows between runs, so ids must be fresh per test.
    alice, bob = f"alice-{uuid4().hex}", f"bob-{uuid4().hex}"
    alice_ws = await store.create(creator_user_id=alice, name="Alice")
    bob_ws = await store.create(creator_user_id=bob, name="Bob")
    return _World(
        WorkspaceAuthorizer(store), store, alice, bob, alice_ws.workspace_id, bob_ws.workspace_id
    )


async def test_member_may_view_own_workspace(world: _World) -> None:
    membership = await world.authorizer.require(world.alice, world.alice_ws, WorkspaceAction.VIEW)

    assert membership.workspace_id == world.alice_ws
    assert membership.user_id == world.alice


async def test_foreign_and_unknown_workspace_are_indistinguishable(world: _World) -> None:
    with pytest.raises(WorkspaceAuthorizationDenied) as foreign:
        await world.authorizer.require(world.alice, world.bob_ws, WorkspaceAction.VIEW)
    with pytest.raises(WorkspaceAuthorizationDenied) as unknown:
        await world.authorizer.require(world.alice, f"missing-{uuid4().hex}", WorkspaceAction.VIEW)

    assert type(foreign.value) is type(unknown.value)
    assert str(foreign.value) == str(unknown.value)
    assert isinstance(foreign.value, LookupError)


@pytest.mark.parametrize("principal", ["", "   "])
async def test_blank_principal_is_denied(world: _World, principal: str) -> None:
    for action in WorkspaceAction:
        with pytest.raises(WorkspaceAuthorizationDenied):
            await world.authorizer.require(principal, world.alice_ws, action)
    assert await world.authorizer.visible_workspace_ids(principal) == frozenset()


async def test_administer_requires_owner(world: _World) -> None:
    await world.store.set_membership(world.alice_ws, user_id=world.bob, role=WorkspaceRole.MEMBER)

    owner = await world.authorizer.require(world.alice, world.alice_ws, WorkspaceAction.ADMINISTER)
    assert owner.role is WorkspaceRole.OWNER

    await world.authorizer.require(world.bob, world.alice_ws, WorkspaceAction.VIEW)
    with pytest.raises(WorkspaceAuthorizationDenied) as denied:
        await world.authorizer.require(world.bob, world.alice_ws, WorkspaceAction.ADMINISTER)
    assert denied.value.membership is not None
    assert denied.value.membership.role is WorkspaceRole.MEMBER


async def test_removed_membership_is_revoked_on_next_call(world: _World) -> None:
    await world.store.set_membership(world.alice_ws, user_id=world.bob, role=WorkspaceRole.MEMBER)
    await world.authorizer.require(world.bob, world.alice_ws, WorkspaceAction.VIEW)

    await world.store.remove_membership(world.alice_ws, user_id=world.bob)

    with pytest.raises(WorkspaceAuthorizationDenied):
        await world.authorizer.require(world.bob, world.alice_ws, WorkspaceAction.VIEW)
    assert world.alice_ws not in await world.authorizer.visible_workspace_ids(world.bob)


async def test_visible_workspace_ids_match_list_for_user(world: _World) -> None:
    await world.store.set_membership(world.bob_ws, user_id=world.alice, role=WorkspaceRole.MEMBER)

    for principal in (world.alice, world.bob):
        expected = {ws.workspace_id for ws in await world.store.list_for_user(principal)}
        assert await world.authorizer.visible_workspace_ids(principal) == frozenset(expected)
    assert await world.authorizer.visible_workspace_ids(world.alice) == {
        world.alice_ws,
        world.bob_ws,
    }
    assert await world.authorizer.visible_workspace_ids(world.bob) == {world.bob_ws}


class _NoMembershipStore(InMemoryWorkspaceStore):
    """A store that answers every membership lookup with 'none'."""

    async def get_membership(
        self, workspace_id: str, *, user_id: str
    ) -> WorkspaceMembership | None:
        return None


async def test_store_without_membership_is_always_denied() -> None:
    store = _NoMembershipStore()
    workspace = await store.create(creator_user_id="alice", name="Alice")
    authorizer = WorkspaceAuthorizer(store)

    for action in WorkspaceAction:
        with pytest.raises(WorkspaceAuthorizationDenied):
            await authorizer.require("alice", workspace.workspace_id, action)
