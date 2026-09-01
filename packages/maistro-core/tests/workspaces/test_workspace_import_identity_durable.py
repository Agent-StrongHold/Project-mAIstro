from __future__ import annotations

import os
from uuid import uuid4

import pytest

from maistro.testing.postgres import postgres_dsn


@pytest.mark.asyncio
async def test_sqlite_import_preserves_workspace_and_root_project_identity(tmp_path) -> None:
    import aiosqlite

    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
    from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

    workspace_id = f"legacy-{uuid4().hex}"
    conn = await aiosqlite.connect(tmp_path / "workspace-import.db")
    try:
        projects = SqliteProjectScopeStore(conn)
        await projects.ensure_schema()
        store = SqliteWorkspaceStore(conn, project_store=projects)
        await store.ensure_schema()

        workspace = await store.create(
            creator_user_id="legacy-owner",
            name="Imported",
            workspace_id=workspace_id,
        )
        root = await projects.root_for_workspace(workspace_id)

        assert workspace.workspace_id == workspace_id
        assert root.workspace_id == workspace_id
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_postgres_import_preserves_workspace_and_root_project_identity() -> None:
    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            raise RuntimeError(
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
                "the PostgreSQL Workspace-import leg must run"
            )
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")

    asyncpg = pytest.importorskip("asyncpg")
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    workspace_id = f"legacy-{uuid4().hex}"
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    store = PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool))
    created = False
    try:
        workspace = await store.create(
            creator_user_id="legacy-owner",
            name="Imported",
            workspace_id=workspace_id,
        )
        created = True
        root = await store.project_store.root_for_workspace(workspace_id)

        assert workspace.workspace_id == workspace_id
        assert root.workspace_id == workspace_id
    finally:
        if created:
            await store.delete(workspace_id)
        await pool.close()
