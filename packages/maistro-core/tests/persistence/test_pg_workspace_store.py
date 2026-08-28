from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from maistro.workspaces import WorkspaceAccessDenied, WorkspaceOwnershipError, WorkspaceRole
from maistro.workspaces.pg_store import PgWorkspaceStore

pytestmark = pytest.mark.asyncio


def _identity(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


async def _require_pg(pg_pool: Any) -> Any:
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    return pg_pool


async def _cleanup_workspace(pg_pool: Any, workspace_id: str) -> None:
    async with pg_pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "DELETE FROM canonical_projects WHERE workspace_id = $1",
            workspace_id,
        )
        await conn.execute(
            "DELETE FROM canonical_workspaces WHERE workspace_id = $1",
            workspace_id,
        )


async def test_pg_workspace_persists_identity_membership_and_root_across_store_instances(
    pg_pool: Any,
) -> None:
    pool = await _require_pg(pg_pool)
    store = PgWorkspaceStore(pool)
    workspace = await store.create(
        creator_user_id=_identity("owner"),
        name=_identity("workspace"),
    )

    try:
        fresh_store = PgWorkspaceStore(pool)
        persisted = await fresh_store.get(workspace.workspace_id)
        memberships = await fresh_store.list_memberships(workspace.workspace_id)
        root = await fresh_store.project_store.root_for_workspace(workspace.workspace_id)

        assert persisted == workspace
        assert len(memberships) == 1
        assert memberships[0].workspace_id == workspace.workspace_id
        assert memberships[0].role is WorkspaceRole.OWNER
        assert root.workspace_id == workspace.workspace_id
        assert root.is_root
    finally:
        await _cleanup_workspace(pool, workspace.workspace_id)


async def test_pg_workspace_creation_rolls_back_identity_and_membership_when_root_fails(
    pg_pool: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = await _require_pg(pg_pool)
    store = PgWorkspaceStore(pool)
    owner_id = _identity("rollback-owner")
    name = _identity("rollback-workspace")

    async def fail_root(conn: Any, workspace_id: str) -> Any:
        raise RuntimeError("injected root failure")

    monkeypatch.setattr(PgWorkspaceStore, "_create_root", staticmethod(fail_root))

    with pytest.raises(RuntimeError, match="injected root failure"):
        await store.create(creator_user_id=owner_id, name=name)

    async with pool.acquire() as conn:
        workspace_count = await conn.fetchval(
            "SELECT count(*) FROM canonical_workspaces WHERE payload->>'name' = $1",
            name,
        )
        membership_count = await conn.fetchval(
            "SELECT count(*) FROM canonical_workspace_memberships WHERE user_id = $1",
            owner_id,
        )
    assert workspace_count == 0
    assert membership_count == 0


async def test_pg_workspace_serializes_concurrent_last_owner_changes(pg_pool: Any) -> None:
    pool = await _require_pg(pg_pool)
    store_a = PgWorkspaceStore(pool)
    store_b = PgWorkspaceStore(pool)
    alice = _identity("alice")
    bob = _identity("bob")
    workspace = await store_a.create(creator_user_id=alice, name=_identity("workspace"))
    await store_a.set_membership(workspace.workspace_id, user_id=bob, role=WorkspaceRole.OWNER)

    try:
        outcomes = await asyncio.gather(
            store_a.set_membership(
                workspace.workspace_id,
                user_id=alice,
                role=WorkspaceRole.MEMBER,
            ),
            store_b.set_membership(
                workspace.workspace_id,
                user_id=bob,
                role=WorkspaceRole.MEMBER,
            ),
            return_exceptions=True,
        )
        denied = [outcome for outcome in outcomes if isinstance(outcome, WorkspaceAccessDenied)]
        assert len(denied) == 1

        memberships = await store_a.list_memberships(workspace.workspace_id)
        owners = [membership for membership in memberships if membership.role is WorkspaceRole.OWNER]
        assert len(owners) == 1
    finally:
        await _cleanup_workspace(pool, workspace.workspace_id)


async def test_pg_workspace_delete_refuses_child_project_state(pg_pool: Any) -> None:
    pool = await _require_pg(pg_pool)
    store = PgWorkspaceStore(pool)
    workspace = await store.create(
        creator_user_id=_identity("owner"),
        name=_identity("workspace"),
    )
    root = await store.project_store.root_for_workspace(workspace.workspace_id)
    child = await store.project_store.create(
        workspace_id=workspace.workspace_id,
        parent_project_id=root.project_id,
        name="Child",
    )

    try:
        with pytest.raises(WorkspaceOwnershipError, match="child Projects"):
            await store.delete(workspace.workspace_id)
        assert await store.get(workspace.workspace_id) is not None
    finally:
        await store.project_store.delete(child.project_id)
        await store.delete(workspace.workspace_id)
