from __future__ import annotations

from datetime import UTC, datetime

import pytest

import stores
from models.workspace import Workspace, WorkspaceMember
from services import workspace_authority

from maistro.workspaces.store import InMemoryWorkspaceStore


def _legacy_workspace(*, workspace_id: str = "legacy-ws", owner: str = "alice") -> Workspace:
    now = datetime.now(UTC)
    return Workspace(
        id=workspace_id,
        persona_template_id="pm_fleet",
        name="Legacy",
        members=[WorkspaceMember(user_id=owner, role="owner")],
        checklist=["tool:jira"],
        theme_id="default",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_legacy_workspace_import_keeps_exact_canonical_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = InMemoryWorkspaceStore()
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)
    stores.workspaces["legacy-ws"] = _legacy_workspace()

    view = await workspace_authority.visible_view("alice", "legacy-ws")
    persisted = await canonical.get("legacy-ws")
    root = await canonical.project_store.root_for_workspace("legacy-ws")

    assert view is not None
    assert view.id == "legacy-ws"
    assert persisted is not None
    assert persisted.workspace_id == "legacy-ws"
    assert root.workspace_id == "legacy-ws"


@pytest.mark.asyncio
async def test_live_membership_authority_does_not_follow_legacy_store_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = InMemoryWorkspaceStore()
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)
    stores.workspaces["legacy-ws"] = _legacy_workspace()

    assert await workspace_authority.is_member("alice", "legacy-ws")

    legacy = stores.workspaces["legacy-ws"]
    stores.workspaces["legacy-ws"] = legacy.model_copy(
        update={
            "members": [
                *legacy.members,
                WorkspaceMember(user_id="intruder", role="owner"),
            ]
        }
    )

    assert not await workspace_authority.is_member("intruder", "legacy-ws")


@pytest.mark.asyncio
async def test_new_workspace_writes_canonical_identity_and_hive_presentation_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = InMemoryWorkspaceStore()
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)

    view = await workspace_authority.create_workspace(
        creator_user_id="alice",
        name="Canonical",
        persona_template_id="content_creator",
        checklist=["tool:search"],
        theme_id="default",
        voice_tone_override=None,
    )

    assert await canonical.get(view.id) is not None
    assert view.id in workspace_authority.presentation_store()
    assert view.id not in stores.workspaces
    membership = await canonical.get_membership(view.id, user_id="alice")
    assert membership is not None
