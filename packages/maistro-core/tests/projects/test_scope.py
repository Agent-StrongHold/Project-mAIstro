"""Acceptance tests for the canonical Workspace Project scope tree."""

from __future__ import annotations

import pytest

from maistro.graph.definitions import GraphTemplate, Node
from maistro.projects.authorization import (
    require_delegable_grant,
    resolve_project_authorization,
)
from maistro.projects.scope import (
    ProjectIntegrityError,
    ProjectMembership,
    ProjectNotEmpty,
    ProjectScopeDenied,
    ProjectScopedResource,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.workspaces import InMemoryWorkspaceStore


@pytest.mark.asyncio
async def test_workspace_creation_provisions_exactly_one_persisted_root_project() -> None:
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)

    workspace = await workspaces.create(creator_user_id="alice", name="Alpha")
    root = await projects.root_for_workspace(workspace.workspace_id)
    same_root = await projects.create_root(workspace.workspace_id)

    assert root.project_id == same_root.project_id
    assert root.workspace_id == workspace.workspace_id
    assert root.is_root is True
    assert root.parent_project_id is None


@pytest.mark.asyncio
async def test_root_project_cannot_move_or_delete() -> None:
    store = InMemoryProjectScopeStore()
    root = await store.create_root("ws-1")
    other_root = await store.create_root("ws-2")

    with pytest.raises(ProjectIntegrityError, match="cannot be moved"):
        await store.move_project(root.project_id, parent_project_id=other_root.project_id)

    with pytest.raises(ProjectIntegrityError, match="cannot be deleted"):
        await store.delete(root.project_id)


@pytest.mark.asyncio
async def test_projects_nest_only_inside_the_same_workspace_without_cycles() -> None:
    store = InMemoryProjectScopeStore()
    root = await store.create_root("ws-1")
    other_root = await store.create_root("ws-2")
    parent = await store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Parent",
    )
    child = await store.create(
        workspace_id="ws-1",
        parent_project_id=parent.project_id,
        name="Child",
    )

    assert [item.project_id for item in await store.lineage(child.project_id)] == [
        root.project_id,
        parent.project_id,
        child.project_id,
    ]

    with pytest.raises(ProjectIntegrityError, match="same Workspace"):
        await store.create(
            workspace_id="ws-1",
            parent_project_id=other_root.project_id,
            name="Crossed",
        )

    with pytest.raises(ProjectIntegrityError, match="cycle"):
        await store.move_project(parent.project_id, parent_project_id=child.project_id)


@pytest.mark.asyncio
async def test_project_deletion_requires_scope_records_to_be_empty() -> None:
    store = InMemoryProjectScopeStore()
    root = await store.create_root("ws-1")
    parent = await store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Parent",
    )
    child = await store.create(
        workspace_id="ws-1",
        parent_project_id=parent.project_id,
        name="Child",
    )

    with pytest.raises(ProjectNotEmpty, match="child Projects"):
        await store.delete(parent.project_id)

    await store.delete(child.project_id)
    await store.delete(parent.project_id)
    assert await store.get(parent.project_id) is None


@pytest.mark.asyncio
async def test_creation_defaults_resolve_once_from_workspace_persona_and_project_ancestry() -> None:
    store = InMemoryProjectScopeStore()
    root = await store.create_root("ws-1")
    await store.update_defaults(root.project_id, defaults={"model": "root", "temperature": 0.3})
    child = await store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Child",
        defaults={"temperature": 0.7, "format": "json"},
    )

    created_config = await store.resolve_creation_defaults(
        child.project_id,
        workspace_defaults={"model": "workspace", "retries": 2},
        persona_defaults={"model": "persona", "voice": "technical"},
    )

    assert created_config == {
        "model": "root",
        "retries": 2,
        "voice": "technical",
        "temperature": 0.7,
        "format": "json",
    }

    await store.update_defaults(child.project_id, defaults={"temperature": 0.1})
    assert created_config["temperature"] == 0.7


@pytest.mark.asyncio
async def test_project_resources_flow_downward_not_upward_or_to_siblings() -> None:
    store = InMemoryProjectScopeStore()
    root = await store.create_root("ws-1")
    left = await store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Left",
    )
    left_child = await store.create(
        workspace_id="ws-1",
        parent_project_id=left.project_id,
        name="Left Child",
    )
    right = await store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Right",
    )

    root_credential = ProjectScopedResource(
        resource_id="credential-root",
        workspace_id="ws-1",
        project_id=root.project_id,
        resource_type="credential",
    )
    left_credential = ProjectScopedResource(
        resource_id="credential-left",
        workspace_id="ws-1",
        project_id=left.project_id,
        resource_type="credential",
    )
    await store.put_resource(root_credential)
    await store.put_resource(left_credential)

    assert {item.resource_id for item in await store.visible_resources(left_child.project_id)} == {
        "credential-root",
        "credential-left",
    }
    assert {item.resource_id for item in await store.visible_resources(root.project_id)} == {
        "credential-root"
    }
    assert {item.resource_id for item in await store.visible_resources(right.project_id)} == {
        "credential-root"
    }


@pytest.mark.asyncio
async def test_destination_move_validation_rejects_invisible_required_resources() -> None:
    store = InMemoryProjectScopeStore()
    root = await store.create_root("ws-1")
    left = await store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Left",
    )
    right = await store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Right",
    )
    await store.put_resource(
        ProjectScopedResource(
            resource_id="twitter-production",
            workspace_id="ws-1",
            project_id=left.project_id,
            resource_type="binding",
        )
    )

    await store.validate_required_resources(left.project_id, {"twitter-production"})
    with pytest.raises(ProjectScopeDenied, match="twitter-production"):
        await store.validate_required_resources(right.project_id, {"twitter-production"})


@pytest.mark.asyncio
async def test_project_grants_accumulate_inside_scope_and_never_leak_to_sibling() -> None:
    store = InMemoryProjectScopeStore()
    root = await store.create_root("ws-1")
    publishing = await store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Publishing",
    )
    other = await store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Other",
    )

    await store.set_membership(
        ProjectMembership(
            workspace_id="ws-1",
            project_id=publishing.project_id,
            principal_id="alice",
            grants={"publish"},
        )
    )

    publishing_auth = await resolve_project_authorization(
        store,
        project_id=publishing.project_id,
        principal_id="alice",
        workspace_grants={"read"},
    )
    other_auth = await resolve_project_authorization(
        store,
        project_id=other.project_id,
        principal_id="alice",
        workspace_grants={"read"},
    )

    assert publishing_auth.grants == frozenset({"read", "publish"})
    assert other_auth.grants == frozenset({"read"})


@pytest.mark.asyncio
async def test_denies_accumulate_and_win_over_descendant_grants() -> None:
    store = InMemoryProjectScopeStore()
    root = await store.create_root("ws-1")
    child = await store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Publishing",
    )

    await store.set_membership(
        ProjectMembership(
            workspace_id="ws-1",
            project_id=root.project_id,
            principal_id="alice",
            grants={"read"},
            denies={"publish"},
        )
    )
    await store.set_membership(
        ProjectMembership(
            workspace_id="ws-1",
            project_id=child.project_id,
            principal_id="alice",
            grants={"publish"},
        )
    )

    effective = await resolve_project_authorization(
        store,
        project_id=child.project_id,
        principal_id="alice",
    )

    assert effective.allows("read")
    assert not effective.allows("publish")
    assert "publish" in effective.denies


@pytest.mark.asyncio
async def test_delegation_requires_separate_delegable_authority() -> None:
    store = InMemoryProjectScopeStore()
    root = await store.create_root("ws-1")

    await store.set_membership(
        ProjectMembership(
            workspace_id="ws-1",
            project_id=root.project_id,
            principal_id="alice",
            grants={"publish"},
        )
    )
    with pytest.raises(PermissionError, match="cannot delegate"):
        await require_delegable_grant(
            store,
            project_id=root.project_id,
            principal_id="alice",
            action="publish",
        )

    await store.set_membership(
        ProjectMembership(
            workspace_id="ws-1",
            project_id=root.project_id,
            principal_id="bob",
            grants={"publish"},
            delegable_grants={"publish"},
        )
    )
    await require_delegable_grant(
        store,
        project_id=root.project_id,
        principal_id="bob",
        action="publish",
    )


def test_graph_templates_are_workspace_wide_not_project_filed() -> None:
    template = GraphTemplate(
        workspace_id="ws-1",
        name="Reusable",
        nodes=[Node(node_id="node", node_type="agent")],
    )

    assert template.workspace_id == "ws-1"
    assert "project_id" not in template.model_dump()
