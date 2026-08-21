from __future__ import annotations

import pytest

from maistro.workspaces import InMemoryWorkspaceStore, WorkspaceAccessDenied, WorkspaceRole


@pytest.mark.asyncio
async def test_workspace_store_keeps_identity_and_membership_separate() -> None:
    store = InMemoryWorkspaceStore()
    workspace = await store.create(creator_user_id="alice", name="Alpha")

    await store.set_membership(
        workspace.workspace_id,
        user_id="bob",
        role=WorkspaceRole.CONTRIBUTOR,
    )
    await store.set_membership(
        workspace.workspace_id,
        user_id="cara",
        role=WorkspaceRole.MEMBER,
    )

    persisted = await store.get(workspace.workspace_id)
    assert persisted is not None
    assert not hasattr(persisted, "owner_user_id")

    memberships = await store.list_memberships(workspace.workspace_id)
    assert {item.user_id: item.role for item in memberships} == {
        "alice": WorkspaceRole.OWNER,
        "bob": WorkspaceRole.CONTRIBUTOR,
        "cara": WorkspaceRole.MEMBER,
    }


@pytest.mark.asyncio
async def test_workspace_can_have_multiple_owners_and_last_owner_is_protected() -> None:
    store = InMemoryWorkspaceStore()
    workspace = await store.create(creator_user_id="alice", name="Alpha")

    with pytest.raises(WorkspaceAccessDenied):
        await store.set_membership(
            workspace.workspace_id,
            user_id="alice",
            role=WorkspaceRole.MEMBER,
        )

    await store.set_membership(
        workspace.workspace_id,
        user_id="bob",
        role=WorkspaceRole.OWNER,
    )
    alice = await store.set_membership(
        workspace.workspace_id,
        user_id="alice",
        role=WorkspaceRole.MEMBER,
    )

    assert alice.role is WorkspaceRole.MEMBER
    bob = await store.get_membership(workspace.workspace_id, user_id="bob")
    assert bob is not None
    assert bob.role is WorkspaceRole.OWNER


@pytest.mark.asyncio
async def test_workspace_listing_is_membership_driven() -> None:
    store = InMemoryWorkspaceStore()
    personal = await store.create(creator_user_id="alice", name="Personal")
    shared = await store.create(creator_user_id="bob", name="Shared")
    await store.set_membership(shared.workspace_id, user_id="alice", role=WorkspaceRole.MEMBER)

    visible = await store.list_for_user("alice")

    assert {workspace.workspace_id for workspace in visible} == {
        personal.workspace_id,
        shared.workspace_id,
    }
