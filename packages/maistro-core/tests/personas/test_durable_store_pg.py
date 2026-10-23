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

import asyncio
import math
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from maistro.personas.model import Persona
from maistro.personas.store import (
    PersonaAlreadyExists,
    WorkspacePersonaAlreadyExists,
)
from maistro.runs.evidence_json import json_of
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


async def test_the_wired_workspace_delete_needs_no_second_connection() -> None:
    """A one-connection pool is the structural proof that the Persona delete
    joins the Workspace delete's transaction.

    `delete_for_workspace` on its own pooled connection would wait forever for
    the connection the Project transaction already holds — under the old shape
    this test hangs until pytest-timeout kills it, which is the regression
    named. On the ambient connection the same pool completes and the Persona
    is gone.
    """
    dsn = _require_pg_dsn()
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.personas.pg_store import PgPersonaStore
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    workspace_id = _unique("ws")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
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
    finally:
        await pool.close()


class _PurgeBlewUp(RuntimeError):
    pass


async def test_a_failed_workspace_delete_rolls_the_persona_back_with_it() -> None:
    """The Persona delete commits only with the Workspace delete.

    Deleting through a second pooled connection would commit the Persona row
    independently: a Project failure after it leaves a surviving Workspace
    with no Persona — the PostgreSQL shape of the compensation contract the
    in-memory store proves. Poisoning the Project purge proves the rollback
    reaches the Persona rows too.
    """
    dsn = _require_pg_dsn()
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.personas.pg_store import PgPersonaStore
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    class FailingPurgeProjects(PgProjectScopeStore):
        async def purge_workspace_in(self, conn, workspace_id) -> None:
            raise _PurgeBlewUp(workspace_id)

    workspace_id = _unique("ws")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    workspace = None
    try:
        personas = PgPersonaStore(pool)
        workspaces = PgWorkspaceStore(
            pool, project_store=FailingPurgeProjects(pool), persona_store=personas
        )
        workspace = await workspaces.create(
            creator_user_id=_unique("user"), name="Design", workspace_id=workspace_id
        )
        saved = await personas.create(
            Persona(id=_unique("persona"), workspace_id=workspace_id, name="Voice")
        )

        with pytest.raises(_PurgeBlewUp):
            await workspaces.delete(workspace_id)

        assert await personas.get(saved.id) == saved
        assert await workspaces.get(workspace_id) is not None
    finally:
        if workspace is not None:
            await PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool)).delete(
                workspace_id
            )
        await pool.close()


async def test_a_non_finite_persona_payload_survives_the_jsonb_round_trip() -> None:
    """NaN in the payload comes back as NaN, not as `null`.

    The jsonb column rejects the bare `NaN` token, so the lossless codec tags
    non-finites on the way in and restores them on the way out; the read must
    equal what the in-memory store would have kept, or the backends disagree
    about what was recorded (#132 review).
    """
    dsn = _require_pg_dsn()
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.personas.pg_store import PgPersonaStore
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    workspace_id = _unique("ws")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
    persona_id = _unique("persona")
    try:
        await PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool)).create(
            creator_user_id=_unique("user"), name="Design", workspace_id=workspace_id
        )
        personas = PgPersonaStore(pool)
        await personas.create(
            Persona(
                id=persona_id,
                workspace_id=workspace_id,
                name="Voice",
                taste={"dryness": float("nan"), "warmth": float("inf")},
            )
        )
        reloaded = await PgPersonaStore(pool).get(persona_id)

        assert reloaded is not None
        assert math.isnan(reloaded.taste["dryness"])
        assert math.isinf(reloaded.taste["warmth"])
        assert reloaded.taste["warmth"] > 0
        await personas.delete(persona_id)
        assert await personas.get(persona_id) is None
    finally:
        await PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool)).delete(workspace_id)
        await pool.close()


async def test_a_lost_create_race_is_the_domain_error_not_the_driver_s() -> None:
    """An insert-after-check race reads as `WorkspacePersonaAlreadyExists`.

    The SELECT checks make sequential duplicates typed errors; the leftover
    case is another writer committing between the check and the INSERT. Held
    open here literally: one connection inserts the conflicting row without
    committing (invisible to the store's READ COMMITTED check), the store's
    INSERT blocks on the unique index, and the commit turns the waiting insert
    into `UniqueViolationError` — which the store must translate. If the
    interleaving ever lands the other way, the check itself raises the same
    domain error, so the contract holds either way.
    """
    dsn = _require_pg_dsn()
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.personas.pg_store import PgPersonaStore
    from maistro.personas.store import WorkspacePersonaAlreadyExists
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    workspace_id = _unique("ws")
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=2)
    try:
        await PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool)).create(
            creator_user_id=_unique("user"), name="Design", workspace_id=workspace_id
        )
        holder = await pool.acquire()
        tx = holder.transaction()
        await tx.start()
        await holder.execute(
            """INSERT INTO canonical_personas
               (persona_id, workspace_id, name, created_at, updated_at, payload)
               VALUES ($1, $2, $3, $4, $5, $6::text::jsonb)""",
            _unique("persona"),
            workspace_id,
            "Earlier writer",
            datetime.now(UTC),
            datetime.now(UTC),
            json_of(Persona(id="race", workspace_id=workspace_id, name="Earlier writer")),
        )

        personas = PgPersonaStore(pool)
        loser = asyncio.create_task(
            personas.create(Persona(id=_unique("persona"), workspace_id=workspace_id, name="Loser"))
        )
        await asyncio.sleep(0.1)  # let the loser's INSERT queue on the index
        await tx.commit()
        await pool.release(holder)

        with pytest.raises(WorkspacePersonaAlreadyExists):
            await loser
    finally:
        await PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool)).delete(workspace_id)
        await pool.close()


async def test_a_reparent_update_into_an_occupied_workspace_is_rejected() -> None:
    """The one-Persona invariant holds on re-parent, not just on create.

    The FOR UPDATE row lock plus the occupant check make the move atomic; the
    rollback must leave the Persona on the Workspace it tried to leave.
    """
    dsn = _require_pg_dsn()
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.personas.pg_store import PgPersonaStore
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    first, second = _unique("ws"), _unique("ws")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        workspaces = PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool))
        await workspaces.create(creator_user_id=_unique("user"), name="Design", workspace_id=first)
        await workspaces.create(
            creator_user_id=_unique("user"), name="Research", workspace_id=second
        )
        await PgPersonaStore(pool).create(
            Persona(id=_unique("persona"), workspace_id=first, name="Voice")
        )
        squatter = await PgPersonaStore(pool).create(
            Persona(id=_unique("persona"), workspace_id=second, name="Other")
        )

        with pytest.raises(WorkspacePersonaAlreadyExists):
            await PgPersonaStore(pool).update(
                Persona(id=squatter.id, workspace_id=first, name="Other")
            )

        restored = await PgPersonaStore(pool).get(squatter.id)
        assert restored == squatter
    finally:
        await PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool)).delete(first)
        await PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool)).delete(second)
        await pool.close()


async def test_deleting_an_absent_persona_is_a_domain_error() -> None:
    dsn = _require_pg_dsn()
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.personas.pg_store import PgPersonaStore
    from maistro.personas.store import PersonaNotFound

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
    try:
        with pytest.raises(PersonaNotFound):
            await PgPersonaStore(pool).delete(_unique("persona"))
    finally:
        await pool.close()


async def test_the_plain_workspace_delete_removes_the_persona() -> None:
    """`delete_for_workspace` is the store's own API, wired callers aside.

    The wired Workspace delete rides `delete_for_workspace_in` so the Persona
    commits with the Workspace; this is the same purge on the store's own
    connection, for callers that own the transaction themselves.
    """
    dsn = _require_pg_dsn()
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.personas.pg_store import PgPersonaStore
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    workspace_id = _unique("ws")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1)
    try:
        await PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool)).create(
            creator_user_id=_unique("user"), name="Design", workspace_id=workspace_id
        )
        personas = PgPersonaStore(pool)
        saved = await personas.create(
            Persona(id=_unique("persona"), workspace_id=workspace_id, name="Voice")
        )

        await personas.delete_for_workspace(workspace_id)

        assert await personas.get(saved.id) is None
    finally:
        await PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool)).delete(workspace_id)
        await pool.close()


async def test_a_lost_create_race_on_the_persona_id_is_the_domain_error() -> None:
    """The persona_id twin of the Workspace race.

    Another writer commits an INSERT with the same persona_id between the
    store's SELECT check and its INSERT: the loser waits on the primary key
    and must surface `PersonaAlreadyExists`, not the driver's
    `UniqueViolationError`.
    """
    dsn = _require_pg_dsn()
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.personas.pg_store import PgPersonaStore
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    workspace_id, other_workspace = _unique("ws"), _unique("ws")
    persona_id = _unique("persona")
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=2)
    try:
        workspaces = PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool))
        await workspaces.create(
            creator_user_id=_unique("user"), name="Design", workspace_id=workspace_id
        )
        await workspaces.create(
            creator_user_id=_unique("user"), name="Research", workspace_id=other_workspace
        )
        holder = await pool.acquire()
        tx = holder.transaction()
        await tx.start()
        await holder.execute(
            """INSERT INTO canonical_personas
               (persona_id, workspace_id, name, created_at, updated_at, payload)
               VALUES ($1, $2, $3, $4, $5, $6::text::jsonb)""",
            persona_id,
            other_workspace,
            "Earlier writer",
            datetime.now(UTC),
            datetime.now(UTC),
            json_of(Persona(id=persona_id, workspace_id=other_workspace, name="Earlier writer")),
        )

        personas = PgPersonaStore(pool)
        loser = asyncio.create_task(
            personas.create(Persona(id=persona_id, workspace_id=workspace_id, name="Loser"))
        )
        await asyncio.sleep(0.1)  # let the loser's INSERT queue on the key
        await tx.commit()
        await pool.release(holder)

        with pytest.raises(PersonaAlreadyExists):
            await loser
    finally:
        await PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool)).delete(workspace_id)
        await PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool)).delete(
            other_workspace
        )
        await pool.close()


async def test_a_violation_on_another_constraint_keeps_the_driver_error() -> None:
    """Only the Persona table's own keys translate to domain errors.

    A uniqueness race on some other constraint must not be rewritten into a
    Persona error — the caller would debug the wrong layer. The store's checks
    are faked here (a real other-key violation on this two-constraint table is
    not reachable), so the translation map itself is what is under test.
    """
    from contextlib import asynccontextmanager

    pytest.importorskip("asyncpg")
    from asyncpg.exceptions import UniqueViolationError

    from maistro.personas.pg_store import PgPersonaStore

    foreign = UniqueViolationError("duplicate key value violates unique constraint")
    foreign.constraint_name = "canonical_project_memberships_pkey"

    class _RaisingConn:
        @staticmethod
        async def fetchval(*_args: object) -> None:
            return None  # both SELECT checks pass

        @staticmethod
        @asynccontextmanager
        async def transaction():
            yield

        @staticmethod
        async def execute(*_args: object) -> str:
            raise foreign

    class _RaisingPool:
        @staticmethod
        @asynccontextmanager
        async def acquire():
            yield _RaisingConn()

    with pytest.raises(UniqueViolationError) as raised:
        await PgPersonaStore(_RaisingPool()).create(  # type: ignore[arg-type]
            Persona(id="persona-x", workspace_id="ws-x", name="Voice")
        )

    assert raised.value is foreign
