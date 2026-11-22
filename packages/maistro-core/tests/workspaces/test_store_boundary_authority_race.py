"""The authority re-check on the writing connection (#1150, P1).

The Workspace store boundary decided the acting principal's authority
*before* the write took the Workspace's serialization point, so an owner
demoted or removed in between could still add, promote or demote members:
the check had answered about a roster that had already changed.

The re-check is a second read of the same question, on the connection that
will do the write, after the lock. These tests pin it without depending on
timing: the owner's membership is revoked *between* the two reads, so the
pre-write check answers from the stale membership and the write must still
be refused. The control beside it shows the same mutation succeeds when the
authority is intact, so a refusal cannot be vacuous.

The in-memory reference is not in this suite: there is no await between its
decision and its write, so it cannot be the store that races.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import uuid4

import pytest

from maistro.testing.postgres import postgres_dsn
from maistro.workspaces.authorization import WorkspaceAuthorizationDenied
from maistro.workspaces.model import WorkspaceRole

Revoke = Callable[[str, str], Awaitable[None]]


def _user(label: str) -> str:
    """A user id nothing else in the database has used.

    PostgreSQL keeps its rows between tests and between runs, so a fixed id
    would inherit a membership an earlier run made.
    """
    return f"user-{label}{uuid4().hex}"


@pytest.fixture(params=["sqlite", "postgres"])
async def durable_store(request, tmp_path) -> AsyncIterator[tuple[object, Revoke]]:
    """The two durable Workspace stores, each with a way to revoke behind them.

    ``revoke(workspace_id, user_id)`` removes one membership row and commits
    it -- the revocation a concurrent demotion would perform -- so a test can
    put it between the store's two reads.
    """
    if request.param == "sqlite":
        import aiosqlite

        from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
        from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

        conn = await aiosqlite.connect(tmp_path / "authority-race.db")
        scope_store = SqliteProjectScopeStore(conn)
        await scope_store.ensure_schema()
        store = SqliteWorkspaceStore(conn, project_store=scope_store)
        await store.ensure_schema()

        async def revoke(workspace_id: str, user_id: str) -> None:
            await conn.execute(
                """DELETE FROM canonical_workspace_memberships
                   WHERE workspace_id = ? AND user_id = ?""",
                (workspace_id, user_id),
            )
            await conn.commit()

        try:
            yield store, revoke
        finally:
            await conn.close()
        return

    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            msg = (
                "MAISTRO_REQUIRE_PG_LEGS is set but the PostgreSQL DSN is empty: "
                "the durable Workspace-store leg cannot run and must not be "
                "silently skipped"
            )
            raise RuntimeError(msg)
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")

    asyncpg = pytest.importorskip("asyncpg")
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=4)
    store = PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool))

    async def revoke(workspace_id: str, user_id: str) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                """DELETE FROM canonical_workspace_memberships
                   WHERE workspace_id = $1 AND user_id = $2""",
                workspace_id,
                user_id,
            )

    try:
        yield store, revoke
    finally:
        await pool.close()


def _stale_after_revoking(store, revoke: Revoke, workspace_id: str, owner: str):
    """Answer the first membership read from before the revocation.

    The store's pre-write check reads the roster through ``get_membership``;
    the re-check reads it again on the writing connection. Revoking between
    the two is exactly the window the review names, and making the first
    read answer from the stale membership reproduces it deterministically
    instead of hoping a race lands.
    """
    original = store.get_membership
    revoked: list[bool] = []

    async def stale_get_membership(workspace_id_, *, user_id, principal_id=None):
        membership = await original(workspace_id_, user_id=user_id, principal_id=principal_id)
        if not revoked and user_id == owner and workspace_id_ == workspace_id:
            revoked.append(True)
            await revoke(workspace_id_, user_id)
        return membership

    store.get_membership = stale_get_membership
    return revoked


async def test_a_revoked_owner_cannot_add_a_member(durable_store) -> None:
    """The window: revoked between the check and the write, so no write."""
    store, revoke = durable_store
    owner = _user("owner")
    other = _user("other")
    workspace = await store.create(creator_user_id=owner, name="WS")

    revoked = _stale_after_revoking(store, revoke, workspace.workspace_id, owner)

    with pytest.raises(WorkspaceAuthorizationDenied):
        await store.set_membership(
            workspace.workspace_id,
            user_id=other,
            role=WorkspaceRole.MEMBER,
            principal_id=owner,
        )

    assert revoked == [True], "the revocation never happened, so the test proves nothing"
    assert await store.get_membership(workspace.workspace_id, user_id=other) is None


async def test_a_revoked_owner_cannot_demote_a_member(durable_store) -> None:
    """The same window on the removal path: no membership is touched."""
    store, revoke = durable_store
    owner = _user("owner")
    member = _user("member")
    workspace = await store.create(creator_user_id=owner, name="WS")
    await store.set_membership(
        workspace.workspace_id,
        user_id=member,
        role=WorkspaceRole.MEMBER,
        principal_id=owner,
    )

    revoked = _stale_after_revoking(store, revoke, workspace.workspace_id, owner)

    with pytest.raises(WorkspaceAuthorizationDenied):
        await store.remove_membership(workspace.workspace_id, user_id=member, principal_id=owner)

    assert revoked == [True], "the revocation never happened, so the test proves nothing"
    assert await store.get_membership(workspace.workspace_id, user_id=member) is not None


async def test_an_owner_with_intact_authority_still_writes(durable_store) -> None:
    """The control: the same mutation succeeds when nobody was revoked."""
    store, _ = durable_store
    owner = _user("owner")
    other = _user("other")
    workspace = await store.create(creator_user_id=owner, name="WS")

    membership = await store.set_membership(
        workspace.workspace_id,
        user_id=other,
        role=WorkspaceRole.MEMBER,
        principal_id=owner,
    )

    assert membership.user_id == other
    assert await store.get_membership(workspace.workspace_id, user_id=other) is not None
