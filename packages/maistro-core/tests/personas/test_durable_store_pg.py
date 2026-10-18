"""The durable Persona contract against live PostgreSQL (#12).

The SQLite twin (`test_durable_store.py`) proves the durable contract across a
reopen; this leg proves the same ownership rules on the backend a real
deployment uses, where the invariants are enforced by a migrated schema rather
than by `ensure_schema` DDL. Like every PostgreSQL leg in this repository it
needs a real migrated server, skips without one, and a skipped leg is untested
rather than passing — `MAISTRO_REQUIRE_PG_LEGS` turns that skip into a failure
in the jobs that own a server.
"""

from __future__ import annotations

import os
from datetime import UTC
from uuid import uuid4

import pytest

from maistro.personas.model import Persona
from maistro.personas.store import (
    PersonaAlreadyExists,
    WorkspacePersonaAlreadyExists,
)
from maistro.testing.postgres import postgres_dsn


def _require_pg_dsn() -> str:
    """The DSN of a migrated server, or a skip — never a silent fallback."""
    dsn = postgres_dsn()
    if dsn:
        return dsn
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
            "the PostgreSQL Persona-store leg cannot run and must not be "
            "silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")


def _unique(prefix: str) -> str:
    """An id nothing else in the database has used.

    PostgreSQL keeps its rows between tests and between runs — that is the
    point of it — so a fixed id would inherit the Persona a workspace from an
    earlier run already owns, and the uniqueness assertions below would pass
    against yesterday's data instead of today's code.
    """
    return f"{prefix}-{uuid4().hex}"


async def test_a_persona_survives_the_store_that_wrote_it_and_workspace_keeps_one() -> None:
    dsn = _require_pg_dsn()
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.personas.pg_store import PgPersonaStore
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    workspace_id = _unique("ws")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    workspace = None
    try:
        workspaces = PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool))
        personas = PgPersonaStore(pool)
        workspace = await workspaces.create(
            creator_user_id=_unique("user"), name="Design", workspace_id=workspace_id
        )
        saved = await personas.create(
            Persona(
                id=_unique("persona"),
                workspace_id=workspace_id,
                name="Design voice",
                purpose="Keep the Workspace's taste stable across restarts",
                taste={"tone": "dry"},
                surfaces={"ui"},
                node_template_ids=["node-tpl-1"],
                graph_template_ids=["graph-tpl-1"],
            )
        )

        # A different store object on the same pool: durability is a property
        # of the database, not of the instance that happened to write it.
        reloaded = await PgPersonaStore(pool).get(saved.id)

        assert reloaded is not None
        assert reloaded == saved
        assert reloaded.taste == {"tone": "dry"}
        assert reloaded.surfaces == {"ui"}
        assert reloaded.node_template_ids == ["node-tpl-1"]
        assert reloaded.graph_template_ids == ["graph-tpl-1"]
        assert reloaded.created_at.tzinfo is not None
        assert reloaded.created_at == saved.created_at

        # One live Persona per Workspace, enforced by the store.
        with pytest.raises(WorkspacePersonaAlreadyExists):
            await personas.create(
                Persona(id=_unique("persona"), workspace_id=workspace_id, name="Other")
            )
        # The Persona id is its own identity, independent of the Workspace key.
        with pytest.raises(PersonaAlreadyExists):
            await personas.create(saved.model_copy(update={"workspace_id": _unique("ws")}))
    finally:
        if workspace is not None:
            await PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool)).delete(
                workspace_id
            )
        await pool.close()


async def test_update_persists_a_snapshot_and_moves_updated_at_forward() -> None:
    dsn = _require_pg_dsn()
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.personas.pg_store import PgPersonaStore
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    workspace_id = _unique("ws")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    workspace = None
    try:
        workspaces = PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool))
        personas = PgPersonaStore(pool)
        workspace = await workspaces.create(
            creator_user_id=_unique("user"), name="Design", workspace_id=workspace_id
        )
        saved = await personas.create(
            Persona(id=_unique("persona"), workspace_id=workspace_id, name="Initial")
        )

        # Updated from a *second* store object, so passing is persistence
        # rather than a mutated in-process cache.
        updated = await PgPersonaStore(pool).update(saved.model_copy(update={"name": "Updated"}))
        reloaded = await personas.get(saved.id)

        assert updated.name == "Updated"
        assert updated.updated_at >= saved.updated_at
        assert reloaded is not None
        assert reloaded.name == "Updated"
        assert reloaded.updated_at >= saved.updated_at
        # The write is a snapshot: the caller's earlier object is unchanged.
        assert saved.name == "Initial"
        assert saved.updated_at.tzinfo is not None
        assert saved.updated_at.utcoffset() == UTC.utcoffset(None)

        from maistro.personas.store import PersonaNotFound

        with pytest.raises(PersonaNotFound):
            await personas.update(
                saved.model_copy(update={"id": _unique("missing"), "name": "Ghost"})
            )
    finally:
        if workspace is not None:
            await PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool)).delete(
                workspace_id
            )
        await pool.close()


async def test_workspace_delete_purges_its_persona_through_the_ownership_path() -> None:
    dsn = _require_pg_dsn()
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.personas.pg_store import PgPersonaStore
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    workspace_id = _unique("ws")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        personas = PgPersonaStore(pool)
        workspaces = PgWorkspaceStore(
            pool, project_store=PgProjectScopeStore(pool), persona_store=personas
        )
        await workspaces.create(
            creator_user_id=_unique("user"), name="Design", workspace_id=workspace_id
        )
        saved = await personas.create(
            Persona(id=_unique("persona"), workspace_id=workspace_id, name="Voice")
        )

        await workspaces.delete(workspace_id)

        assert await personas.get(saved.id) is None
        assert await personas.get_for_workspace(workspace_id) is None
    finally:
        await pool.close()


async def test_persona_migration_cascade_is_enforced_by_the_database_itself() -> None:
    """Deleting the Workspace row without any store code must still take the
    Persona with it — the foreign key of migration 064 is the durable cleanup
    path, so a store that forgets `delete_for_workspace` cannot strand a
    Persona pointing at a deleted Workspace."""
    dsn = _require_pg_dsn()
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.personas.pg_store import PgPersonaStore
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    workspace_id = _unique("ws")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        personas = PgPersonaStore(pool)
        workspaces = PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool))
        await workspaces.create(
            creator_user_id=_unique("user"), name="Design", workspace_id=workspace_id
        )
        saved = await personas.create(
            Persona(id=_unique("persona"), workspace_id=workspace_id, name="Voice")
        )

        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM canonical_workspaces WHERE workspace_id = $1", workspace_id
            )
            survivor = await conn.fetchval(
                "SELECT persona_id FROM canonical_personas WHERE persona_id = $1", saved.id
            )
            await conn.execute(
                "DELETE FROM canonical_projects WHERE workspace_id = $1", workspace_id
            )

        assert survivor is None
    finally:
        await pool.close()


async def test_wire_persona_store_selects_postgres_on_a_migrated_pool() -> None:
    dsn = _require_pg_dsn()
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.personas.pg_store import PgPersonaStore
    from maistro.personas.wiring import wire_persona_store
    from maistro.projects.pg_scope_store import PgProjectScopeStore

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        store = await wire_persona_store(
            None, project_store=PgProjectScopeStore(pool), pg_pool=pool
        )

        assert isinstance(store, PgPersonaStore)
    finally:
        await pool.close()
