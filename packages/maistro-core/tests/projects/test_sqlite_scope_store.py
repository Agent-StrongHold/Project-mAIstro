from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from maistro.projects.scope import (
    ProjectIntegrityError,
    ProjectMembership,
    ProjectNotEmpty,
    ProjectScopedResource,
)
from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore


@pytest.mark.asyncio
async def test_root_tree_and_creation_defaults_survive_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "projects.db"
    first_conn = await aiosqlite.connect(db_path)
    first = SqliteProjectScopeStore(first_conn)
    await first.ensure_schema()

    root = await first.create_root("workspace-1")
    parent = await first.create(
        workspace_id="workspace-1",
        parent_project_id=root.project_id,
        name="Parent",
        defaults={"model": "root-choice", "temperature": 0.4},
    )
    child = await first.create(
        workspace_id="workspace-1",
        parent_project_id=parent.project_id,
        name="Child",
        defaults={"temperature": 0.2},
    )
    await first_conn.close()

    second_conn = await aiosqlite.connect(db_path)
    second = SqliteProjectScopeStore(second_conn)
    await second.ensure_schema()

    reloaded_root = await second.create_root("workspace-1")
    lineage = await second.lineage(child.project_id)
    defaults = await second.resolve_creation_defaults(
        child.project_id,
        workspace_defaults={"model": "workspace", "max_tokens": 1000},
        persona_defaults={"voice": "technical", "temperature": 0.7},
    )

    assert reloaded_root.project_id == root.project_id
    assert [project.project_id for project in lineage] == [
        root.project_id,
        parent.project_id,
        child.project_id,
    ]
    assert defaults == {
        "model": "root-choice",
        "max_tokens": 1000,
        "voice": "technical",
        "temperature": 0.2,
    }
    await second_conn.close()


@pytest.mark.asyncio
async def test_memberships_and_resources_survive_reopen_with_downward_visibility(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "projects.db"
    first_conn = await aiosqlite.connect(db_path)
    first = SqliteProjectScopeStore(first_conn)
    await first.ensure_schema()

    root = await first.create_root("workspace-1")
    left = await first.create(
        workspace_id="workspace-1",
        parent_project_id=root.project_id,
        name="Left",
    )
    leaf = await first.create(
        workspace_id="workspace-1",
        parent_project_id=left.project_id,
        name="Leaf",
    )
    right = await first.create(
        workspace_id="workspace-1",
        parent_project_id=root.project_id,
        name="Right",
    )
    membership = await first.set_membership(
        ProjectMembership(
            workspace_id="workspace-1",
            project_id=left.project_id,
            principal_id="principal-1",
            grants={"publish"},
            delegable_grants={"publish"},
        )
    )
    await first.put_resource(
        ProjectScopedResource(
            resource_id="root-credential",
            workspace_id="workspace-1",
            project_id=root.project_id,
            resource_type="credential",
        )
    )
    await first.put_resource(
        ProjectScopedResource(
            resource_id="left-binding",
            workspace_id="workspace-1",
            project_id=left.project_id,
            resource_type="binding",
        )
    )
    await first.put_resource(
        ProjectScopedResource(
            resource_id="leaf-secret",
            workspace_id="workspace-1",
            project_id=leaf.project_id,
            resource_type="credential",
        )
    )
    await first_conn.close()

    second_conn = await aiosqlite.connect(db_path)
    second = SqliteProjectScopeStore(second_conn)
    await second.ensure_schema()

    reloaded_memberships = await second.memberships_for(
        left.project_id,
        principal_id="principal-1",
    )
    leaf_visible = {item.resource_id for item in await second.visible_resources(leaf.project_id)}
    left_visible = {item.resource_id for item in await second.visible_resources(left.project_id)}
    right_visible = {item.resource_id for item in await second.visible_resources(right.project_id)}

    assert [item.membership_id for item in reloaded_memberships] == [membership.membership_id]
    assert reloaded_memberships[0].grants == {"publish"}
    assert leaf_visible == {"root-credential", "left-binding", "leaf-secret"}
    assert left_visible == {"root-credential", "left-binding"}
    assert right_visible == {"root-credential"}
    await second_conn.close()


@pytest.mark.asyncio
async def test_project_tree_rejects_cross_workspace_moves_cycles_and_root_mutation(
    tmp_path: Path,
) -> None:
    conn = await aiosqlite.connect(tmp_path / "projects.db")
    store = SqliteProjectScopeStore(conn)
    await store.ensure_schema()
    root_a = await store.create_root("workspace-a")
    root_b = await store.create_root("workspace-b")
    parent = await store.create(
        workspace_id="workspace-a",
        parent_project_id=root_a.project_id,
        name="Parent",
    )
    child = await store.create(
        workspace_id="workspace-a",
        parent_project_id=parent.project_id,
        name="Child",
    )

    with pytest.raises(ProjectIntegrityError, match="Root Project cannot be moved"):
        await store.move_project(root_a.project_id, parent_project_id=parent.project_id)
    with pytest.raises(ProjectIntegrityError, match="across Workspaces"):
        await store.move_project(parent.project_id, parent_project_id=root_b.project_id)
    with pytest.raises(ProjectIntegrityError, match="cycle"):
        await store.move_project(parent.project_id, parent_project_id=child.project_id)
    with pytest.raises(ProjectIntegrityError, match="Root Project cannot be deleted"):
        await store.delete(root_a.project_id)
    await conn.close()


@pytest.mark.asyncio
async def test_delete_requires_an_explicitly_empty_project(tmp_path: Path) -> None:
    conn = await aiosqlite.connect(tmp_path / "projects.db")
    store = SqliteProjectScopeStore(conn)
    await store.ensure_schema()
    root = await store.create_root("workspace-1")
    parent = await store.create(
        workspace_id="workspace-1",
        parent_project_id=root.project_id,
        name="Parent",
    )
    child = await store.create(
        workspace_id="workspace-1",
        parent_project_id=parent.project_id,
        name="Child",
    )

    with pytest.raises(ProjectNotEmpty, match="child Projects"):
        await store.delete(parent.project_id)

    await store.delete(child.project_id)
    await store.delete(parent.project_id)
    assert await store.get(parent.project_id) is None
    await conn.close()
