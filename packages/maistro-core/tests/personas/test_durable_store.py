"""Durable live Persona ownership across the SQLite restart boundary."""

from __future__ import annotations

import aiosqlite
import pytest

from maistro.personas.model import Persona
from maistro.personas.sqlite_store import SqlitePersonaStore
from maistro.personas.store import InMemoryPersonaStore, WorkspacePersonaAlreadyExists
from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
from maistro.workspaces.sqlite_store import SqliteWorkspaceStore
from maistro.workspaces.store import InMemoryWorkspaceStore


async def _stores(path):
    conn = await aiosqlite.connect(path)
    projects = SqliteProjectScopeStore(conn)
    await projects.ensure_schema()
    workspaces = SqliteWorkspaceStore(conn, project_store=projects)
    await workspaces.ensure_schema()
    personas = SqlitePersonaStore(conn)
    await personas.ensure_schema()
    return conn, workspaces, personas


@pytest.mark.asyncio
async def test_persona_survives_reopen_and_workspace_has_one_live_record(tmp_path) -> None:
    path = tmp_path / "canonical.db"
    first_conn, workspaces, personas = await _stores(path)
    try:
        workspace = await workspaces.create(creator_user_id="alice", name="Design")
        saved = await personas.create(
            Persona(id="persona-1", workspace_id=workspace.workspace_id, name="Design voice")
        )
        with pytest.raises(WorkspacePersonaAlreadyExists):
            await personas.create(
                Persona(id="persona-2", workspace_id=workspace.workspace_id, name="Other")
            )
    finally:
        await first_conn.close()

    second_conn, _, reopened = await _stores(path)
    try:
        assert await reopened.get("persona-1") == saved
        assert await reopened.get_for_workspace(workspace.workspace_id) == saved
    finally:
        await second_conn.close()


@pytest.mark.asyncio
async def test_in_memory_workspace_delete_purges_its_persona() -> None:
    personas = InMemoryPersonaStore()
    workspaces = InMemoryWorkspaceStore(persona_store=personas)
    workspace = await workspaces.create(creator_user_id="alice", name="Design")
    await personas.create(
        Persona(id="persona-1", workspace_id=workspace.workspace_id, name="Voice")
    )

    await workspaces.delete(workspace.workspace_id)

    assert await personas.get_for_workspace(workspace.workspace_id) is None


@pytest.mark.asyncio
async def test_persona_update_keeps_snapshot_and_workspace_delete_cascades(tmp_path) -> None:
    path = tmp_path / "canonical.db"
    conn, workspaces, personas = await _stores(path)
    try:
        workspace = await workspaces.create(creator_user_id="alice", name="Design")
        saved = await personas.create(
            Persona(id="persona-1", workspace_id=workspace.workspace_id, name="Initial")
        )
        updated = await personas.update(saved.model_copy(update={"name": "Updated"}))
        assert updated.name == "Updated"
        assert saved.name == "Initial"

        await workspaces.delete(workspace.workspace_id)
        assert await personas.get(saved.id) is None
    finally:
        await conn.close()
