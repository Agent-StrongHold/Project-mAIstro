"""Project model + store tests.

Strong-assertion bar:
- Every test checks actual field values, not just "is not None".
- Lifecycle changes (members added, role transitions, deletion) verified
  by re-reading the persisted record.
- Per-user cap enforced + raises the right exception class.
"""

from __future__ import annotations

import pytest

from maistro.projects import (
    AirtableResourceBinding,
    InMemoryProjectStore,
    JiraResourceBinding,
    Project,
    ProjectAccessDenied,
    ProjectMemberRole,
    ProjectNotFound,
    ProjectQuotaExceeded,
    ProjectSettings,
    RepoResourceBinding,
)

# --- Project type — has_member / role_of / can_mutate ---------------------


def test_owner_is_implicit_owner_without_explicit_member_row() -> None:
    p = Project(id="p1", owner_user_id="alice", name="Ship payments")
    assert p.has_member("alice") is True
    assert p.role_of("alice") == ProjectMemberRole.OWNER
    assert p.can_mutate("alice") is True


def test_non_member_has_no_role_and_cannot_mutate() -> None:
    p = Project(id="p1", owner_user_id="alice", name="Ship payments")
    assert p.has_member("eve") is False
    assert p.role_of("eve") is None
    assert p.can_mutate("eve") is False


def test_explicit_editor_can_mutate_but_viewer_cannot() -> None:
    p = Project(id="p1", owner_user_id="alice", name="Ship payments")
    from maistro.projects.types import ProjectMember

    p = p.model_copy(
        update={
            "members": [
                ProjectMember(user_id="bob", role=ProjectMemberRole.EDITOR),
                ProjectMember(user_id="carol", role=ProjectMemberRole.VIEWER),
            ]
        }
    )
    assert p.role_of("bob") == ProjectMemberRole.EDITOR
    assert p.role_of("carol") == ProjectMemberRole.VIEWER
    assert p.can_mutate("bob") is True
    assert p.can_mutate("carol") is False


def test_resource_bindings_carry_descriptions() -> None:
    """Project profile depends on these — verify they round-trip."""
    p = Project(
        id="p1",
        owner_user_id="alice",
        name="Ship payments",
        profile_markdown="Build the next-gen payments engine for ACME Streaming",
        jira_bindings=[
            JiraResourceBinding(
                project_key="PAY", flavor="server", site_url="https://jira.example.com"
            )
        ],
        airtable_bindings=[
            AirtableResourceBinding(
                base_id="app123",
                base_name="Payments Tracker",
                table_descriptions={
                    "Initiatives": "Each row is a top-level payment milestone",
                    "Risks": "Blockers and open security findings",
                },
            )
        ],
        repo_bindings=[
            RepoResourceBinding(
                host="gitlab_enterprise",
                owner="payments",
                name="ledger-service",
                description="Core ledger; primary write path",
            )
        ],
    )
    assert p.profile_markdown.startswith("Build the next-gen")
    assert p.jira_bindings[0].project_key == "PAY"
    assert p.jira_bindings[0].site_url.endswith("example.com")
    assert p.airtable_bindings[0].base_name == "Payments Tracker"
    assert p.airtable_bindings[0].table_descriptions["Risks"].startswith("Blockers")
    assert p.repo_bindings[0].host == "gitlab_enterprise"
    assert "ledger-service" in p.repo_bindings[0].name


def test_settings_defaults_are_safe_conservative() -> None:
    """Make sure the default settings won't burn money or auto-mutate
    topology behind a user's back."""
    s = ProjectSettings()
    assert s.eval_judge_cadence_runs == 5
    assert s.monthly_budget_usd == 100.0
    assert s.edit_lock_days == 30
    assert s.auto_apply_topology_changes is False  # user must opt in


# --- InMemoryProjectStore lifecycle ---------------------------------------


async def test_create_persists_and_returns_full_record() -> None:
    store = InMemoryProjectStore()
    p = await store.create(
        owner_user_id="alice",
        name="Ship payments",
        summary="Q3 launch",
        profile_markdown="Build the payments engine.",
    )
    assert p.owner_user_id == "alice"
    assert p.name == "Ship payments"
    assert p.summary == "Q3 launch"
    assert p.profile_markdown == "Build the payments engine."
    assert p.id  # auto-generated

    # Re-read via get to verify persistence.
    again = await store.get(p.id)
    assert again is not None
    assert again.id == p.id
    assert again.name == "Ship payments"


async def test_get_unknown_returns_none() -> None:
    store = InMemoryProjectStore()
    assert await store.get("does-not-exist") is None


async def test_per_user_cap_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAISTRO_MAX_PROJECTS_PER_USER", "3")
    store = InMemoryProjectStore()
    for i in range(3):
        await store.create(owner_user_id="alice", name=f"p{i}")
    with pytest.raises(ProjectQuotaExceeded, match="3 projects"):
        await store.create(owner_user_id="alice", name="p4")
    # Different user has their own quota.
    bob_p = await store.create(owner_user_id="bob", name="b1")
    assert bob_p.owner_user_id == "bob"


async def test_list_for_user_returns_owned_and_member_projects() -> None:
    store = InMemoryProjectStore()
    p1 = await store.create(owner_user_id="alice", name="Alpha")
    p2 = await store.create(owner_user_id="bob", name="Beta")
    # Alice gets added to Bob's project as editor.
    await store.add_member(p2.id, user_id="alice", role=ProjectMemberRole.EDITOR)

    alice_projects = await store.list_for_user("alice")
    assert {p.id for p in alice_projects} == {p1.id, p2.id}
    by_id = {p.id: p for p in alice_projects}
    assert by_id[p1.id].role_of("alice") == ProjectMemberRole.OWNER
    assert by_id[p2.id].role_of("alice") == ProjectMemberRole.EDITOR


async def test_add_member_is_idempotent_updates_role() -> None:
    store = InMemoryProjectStore()
    p = await store.create(owner_user_id="alice", name="Alpha")
    await store.add_member(p.id, user_id="bob", role=ProjectMemberRole.VIEWER)
    # Adding bob again with editor should update, not duplicate.
    updated = await store.add_member(p.id, user_id="bob", role=ProjectMemberRole.EDITOR)
    member_user_ids = [m.user_id for m in updated.members]
    assert member_user_ids.count("bob") == 1
    assert updated.role_of("bob") == ProjectMemberRole.EDITOR


async def test_remove_member_refuses_to_remove_owner() -> None:
    store = InMemoryProjectStore()
    p = await store.create(owner_user_id="alice", name="Alpha")
    with pytest.raises(ProjectAccessDenied, match="cannot remove owner"):
        await store.remove_member(p.id, user_id="alice")


async def test_remove_member_drops_a_real_member() -> None:
    store = InMemoryProjectStore()
    p = await store.create(owner_user_id="alice", name="Alpha")
    await store.add_member(p.id, user_id="bob", role=ProjectMemberRole.EDITOR)
    await store.add_member(p.id, user_id="carol", role=ProjectMemberRole.VIEWER)
    updated = await store.remove_member(p.id, user_id="bob")
    assert [m.user_id for m in updated.members] == ["carol"]
    assert updated.role_of("bob") is None
    assert updated.role_of("carol") == ProjectMemberRole.VIEWER


async def test_update_persists_profile_markdown_edit() -> None:
    store = InMemoryProjectStore()
    p = await store.create(owner_user_id="alice", name="Alpha", profile_markdown="v1")
    updated = await store.update(p.model_copy(update={"profile_markdown": "v2 with more context"}))
    assert updated.profile_markdown == "v2 with more context"
    again = await store.get(p.id)
    assert again is not None
    assert again.profile_markdown == "v2 with more context"
    # updated_at advanced.
    assert again.updated_at >= p.updated_at


async def test_update_unknown_raises_project_not_found() -> None:
    store = InMemoryProjectStore()
    ghost = Project(id="nope", owner_user_id="alice", name="x")
    with pytest.raises(ProjectNotFound):
        await store.update(ghost)


async def test_delete_removes_project_from_listings() -> None:
    store = InMemoryProjectStore()
    p = await store.create(owner_user_id="alice", name="Alpha")
    await store.delete(p.id)
    assert await store.get(p.id) is None
    assert [p.id for p in await store.list_for_user("alice")] == []


async def test_delete_unknown_raises_project_not_found() -> None:
    store = InMemoryProjectStore()
    with pytest.raises(ProjectNotFound):
        await store.delete("nope")
