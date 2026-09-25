from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import stores
from models.schemas import Agent
from models.workspace import Workspace, WorkspaceMember
from services import workspace_authority

from maistro.workspaces.model import WorkspaceMembership
from maistro.workspaces.model import WorkspaceRole as CanonicalWorkspaceRole
from maistro.workspaces.store import InMemoryWorkspaceStore


@pytest.fixture(autouse=True)
def _clear_workspace_test_state():
    for store in (stores.workspaces, stores.agents):
        for key in list(store.keys()):
            store.pop(key, None)
    yield
    for store in (stores.workspaces, stores.agents):
        for key in list(store.keys()):
            store.pop(key, None)


def _legacy_workspace(
    *,
    workspace_id: str = "legacy-ws",
    owner: str = "alice",
    members: list[WorkspaceMember] | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Workspace:
    created = created_at or datetime(2024, 1, 2, 3, 4, tzinfo=UTC)
    updated = updated_at or created + timedelta(days=5)
    return Workspace(
        id=workspace_id,
        persona_template_id="pm_fleet",
        name="Legacy",
        members=members if members is not None else [WorkspaceMember(user_id=owner, role="owner")],
        checklist=["tool:jira"],
        theme_id="default",
        created_at=created,
        updated_at=updated,
    )


def _agent(workspace_id: str) -> Agent:
    now = datetime.now(UTC)
    return Agent(
        id=f"{workspace_id}.intake",
        workspace_id=workspace_id,
        name="pm_fleet.intake",
        description="",
        model="x",
        status="idle",
        created_at=now,
    )


@pytest.mark.asyncio
async def test_legacy_workspace_import_keeps_exact_identity_root_and_chronology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = InMemoryWorkspaceStore()
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)
    legacy = _legacy_workspace()
    stores.workspaces["legacy-ws"] = legacy

    view = await workspace_authority.visible_view("alice", "legacy-ws")
    persisted = await canonical.get("legacy-ws")
    root = await canonical.project_store.root_for_workspace("legacy-ws")

    assert view is not None
    assert view.id == "legacy-ws"
    assert view.created_at == legacy.created_at
    assert view.updated_at == legacy.updated_at
    assert persisted is not None
    assert persisted.workspace_id == "legacy-ws"
    assert persisted.created_at == legacy.created_at
    assert persisted.updated_at == legacy.updated_at
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
async def test_fallback_created_workspace_survives_adapter_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_ref = [InMemoryWorkspaceStore()]
    monkeypatch.setattr(
        workspace_authority,
        "_engine_workspace_store",
        lambda: canonical_ref[0],
    )

    view = await workspace_authority.create_workspace(
        creator_user_id="alice",
        name="Canonical",
        persona_template_id="content_creator",
        checklist=["tool:search"],
        theme_id="default",
        voice_tone_override=None,
    )

    assert await canonical_ref[0].get(view.id) is not None
    assert view.id in workspace_authority.presentation_store()
    assert view.id in stores.workspaces

    # Simulate process-local canonical state disappearing while the persisted
    # Hive recovery record remains available to the next process.
    canonical_ref[0] = InMemoryWorkspaceStore()
    workspace_authority.reset_for_tests()
    recovered = await workspace_authority.visible_view("alice", view.id)

    assert recovered is not None
    assert recovered.id == view.id
    assert recovered.name == "Canonical"
    assert recovered.members == [WorkspaceMember(user_id="alice", role="owner")]
    assert await canonical_ref[0].get(view.id) is not None


@pytest.mark.asyncio
async def test_interrupted_membership_import_resumes_instead_of_dropping_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailOnceStore(InMemoryWorkspaceStore):
        failed = False

        async def set_membership(
            self,
            workspace_id: str,
            *,
            user_id: str,
            role: CanonicalWorkspaceRole,
        ) -> WorkspaceMembership:
            if user_id == "bob" and not self.failed:
                self.failed = True
                raise RuntimeError("transient membership write failure")
            return await super().set_membership(workspace_id, user_id=user_id, role=role)

    canonical = _FailOnceStore()
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)
    stores.workspaces["legacy-ws"] = _legacy_workspace(
        members=[
            WorkspaceMember(user_id="alice", role="owner"),
            WorkspaceMember(user_id="bob", role="editor"),
        ]
    )

    with pytest.raises(RuntimeError, match="transient membership write failure"):
        await workspace_authority.visible_view("alice", "legacy-ws")

    assert await canonical.get("legacy-ws") is not None
    assert await canonical.get_membership("legacy-ws", user_id="bob") is None

    recovered = await workspace_authority.visible_view("bob", "legacy-ws")
    bob = await canonical.get_membership("legacy-ws", user_id="bob")

    assert recovered is not None
    assert bob is not None
    assert bob.role is CanonicalWorkspaceRole.CONTRIBUTOR


@pytest.mark.asyncio
async def test_ownerless_legacy_row_is_quarantined_without_blocking_valid_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = InMemoryWorkspaceStore()
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)
    stores.workspaces["bad"] = _legacy_workspace(workspace_id="bad", members=[])
    stores.workspaces["good"] = _legacy_workspace(workspace_id="good")

    visible = await workspace_authority.list_views_for_user("alice")

    assert {workspace.id for workspace in visible} == {"good"}
    assert "bad" in stores.workspaces
    quarantined = workspace_authority.quarantine_store().get("bad")
    assert quarantined is not None
    assert "no owner" in quarantined["reason"]


@pytest.mark.asyncio
async def test_durable_import_leaves_the_mirror_and_materialized_agents_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = InMemoryWorkspaceStore()
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)
    monkeypatch.setattr(workspace_authority, "_is_durable_store", lambda store: True)
    legacy = _legacy_workspace()
    stores.workspaces["legacy-ws"] = legacy
    agent = _agent("legacy-ws")
    stores.agents[agent.id] = agent

    view = await workspace_authority.visible_view("alice", "legacy-ws")

    assert view is not None
    assert stores.workspaces.get("legacy-ws") == legacy
    assert stores.agents.get(agent.id) is not None


@pytest.mark.asyncio
async def test_preexisting_canonical_workspace_wins_over_stale_legacy_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = InMemoryWorkspaceStore()
    await canonical.create(
        creator_user_id="canonical-owner",
        name="Canonical",
        workspace_id="legacy-ws",
    )
    monkeypatch.setattr(workspace_authority, "_engine_workspace_store", lambda: canonical)
    stores.workspaces["legacy-ws"] = _legacy_workspace(
        owner="legacy-owner",
        members=[WorkspaceMember(user_id="legacy-owner", role="owner")],
    )

    assert await workspace_authority.is_member("canonical-owner", "legacy-ws")
    assert not await workspace_authority.is_member("legacy-owner", "legacy-ws")


@pytest.mark.asyncio
async def test_member_writes_fail_closed_when_the_view_cannot_compose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A membership write whose presentation no longer composes is an error.

    The canonical membership itself is durable, but returning a half-truth
    view would let a caller believe a write landed on a Workspace that no
    longer exists, so the authority raises instead. Both write paths — add
    and remove — hold the HITL serialization lock across that decision.
    """
    workspace = await workspace_authority.create_workspace(
        creator_user_id="alice",
        name="View compose guard",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    # A second member first, so the guarded remove below is not refused
    # earlier by the canonical at-least-one-owner rule.
    await workspace_authority.set_member(workspace.id, user_id="bob", role="editor")

    async def _no_view(_workspace_id: str) -> Workspace | None:
        return None

    monkeypatch.setattr(workspace_authority, "get_view", _no_view)

    with pytest.raises(KeyError):
        await workspace_authority.set_member(workspace.id, user_id="carol", role="editor")
    with pytest.raises(KeyError):
        await workspace_authority.remove_member(workspace.id, user_id="bob")


@pytest.mark.asyncio
async def test_delete_workspace_retires_a_hive_projection_row_when_one_exists() -> None:
    """Deletion cleans the Hive projection row too, and tolerates its absence.

    A canonical Workspace created without a legacy Hive row takes the same
    deletion path as one that still carries a projection row; only the latter
    must pop from `stores.workspaces`.
    """
    projected = await workspace_authority.create_workspace(
        creator_user_id="alice",
        name="Projected",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    stores.workspaces[projected.id] = _legacy_workspace(workspace_id=projected.id)
    unprojected = await workspace_authority.create_workspace(
        creator_user_id="alice",
        name="Unprojected",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )

    await workspace_authority.delete_workspace(projected.id)
    await workspace_authority.delete_workspace(unprojected.id)

    assert projected.id not in stores.workspaces
    assert await workspace_authority.get_view(projected.id) is None
    assert await workspace_authority.get_view(unprojected.id) is None
