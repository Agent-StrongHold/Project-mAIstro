"""Two-tenant behavioral conformance for the Canvas and Asset stores (#857).

The Defect Ladder found that mutations dropping ``org_id`` survived the whole
Canvas suite: nothing ever ran the durable stores against two orgs and asked
whether one could see the other's rows. ``PgCanvasStore`` in particular had
never run at all — no test, no migration, no wiring — so its scope claims were
unfalsifiable.

This suite is behavioral, not structural: two orgs, real rows, and the
question "can org B reach org A's canvas/layer/job/composite/definition/
sheet/instance/profile/book by id?" The answer must be *absence* — ``None`` /
``NotFound`` — never the row and never a 403-shaped confirmation that it
exists somewhere. Every test is a mutation-removal arc: deleting the
``org_id`` predicate from any store query flips its assertion.

Backends:

- ``postgres`` — ``PgCanvasStore`` and ``PostgresAssetStore`` against a real
  server, in a throwaway schema so the run cannot disturb the database it
  borrows. Skips without ``MAISTRO_TEST_PG_DSN``; ``MAISTRO_REQUIRE_PG_LEGS``
  turns the skip into a failure where a server is guaranteed (the same
  contract as ``maestro-core``'s conformance suites).
- ``inmemory`` — ``InMemoryAssetStore`` only. There is no supported SQLite
  twin of the canvas store; the in-memory *asset* twin exists and runs the
  same asset bodies so the two flavours cannot drift. ``PgCanvasStore`` has
  no twin and therefore only the PostgreSQL leg.
"""

from __future__ import annotations

import dataclasses
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from typing import Any, ClassVar

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.testing.postgres import postgres_dsn
from maistro_canvas.auth import CurrentUser
from maistro_canvas.canvas.asset_store import InMemoryAssetStore
from maistro_canvas.canvas.store import PgCanvasStore
from maistro_canvas.layers import (
    AssetDefinition,
    AssetInstance,
    AssetSheet,
    ChildProfile,
    LayerKind,
    StyleVolume,
    WorldStyle,
)
from maistro_canvas.types import (
    AssetDefinitionNotFoundError,
    CanvasNotFoundError,
    CanvasRecord,
    CompositeResult,
    GenerationJobRecord,
    JobNotFoundError,
    LayerNotFoundError,
    LayerRecord,
    LayerType,
)

ORG_A = "org-alpha"
ORG_B = "org-beta"

# asyncio_mode=auto runs the async tests; an explicit module-level mark would
# fire PytestWarnings on the deliberately-synchronous static tests below.


# ─────────────────────────────────────────────────────────────────────
# Canvas-store schema — the legacy product tables no migration owns
# ─────────────────────────────────────────────────────────────────────

_CANVAS_DDL = """
CREATE TABLE canvases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    background_color TEXT NOT NULL DEFAULT '#FFFFFF',
    org_id TEXT NOT NULL DEFAULT '',
    layer_count INTEGER NOT NULL DEFAULT 0,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE layers (
    id TEXT PRIMARY KEY,
    canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    layer_type TEXT NOT NULL DEFAULT 'background',
    z_index INTEGER NOT NULL DEFAULT 0,
    x DOUBLE PRECISION NOT NULL DEFAULT 0,
    y DOUBLE PRECISION NOT NULL DEFAULT 0,
    scale DOUBLE PRECISION NOT NULL DEFAULT 1,
    rotation DOUBLE PRECISION NOT NULL DEFAULT 0,
    opacity DOUBLE PRECISION NOT NULL DEFAULT 1,
    blend_mode TEXT NOT NULL DEFAULT 'normal',
    visible BOOLEAN NOT NULL DEFAULT TRUE,
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    image_path TEXT,
    prompt TEXT,
    negative_prompt TEXT,
    model_id TEXT,
    tier TEXT DEFAULT 'draft',
    generation_seed INTEGER,
    text_config JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (canvas_id, z_index)
);
CREATE TABLE generation_jobs (
    id TEXT PRIMARY KEY,
    layer_id TEXT NOT NULL REFERENCES layers(id) ON DELETE CASCADE,
    canvas_id TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'generate',
    status TEXT NOT NULL DEFAULT 'pending',
    model_id TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    params JSONB NOT NULL DEFAULT '{}',
    result_paths JSONB NOT NULL DEFAULT '[]',
    selected_index INTEGER,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    leased_by TEXT,
    lease_expires_at TIMESTAMPTZ
);
CREATE TABLE composite_records (
    id TEXT PRIMARY KEY,
    canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    image_bytes BYTEA NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    layer_snapshot JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# The asset tables as migrations 002 + 032 declare them.
_ASSET_DDL = """
CREATE TABLE child_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    pronouns TEXT,
    likeness_refs JSONB NOT NULL DEFAULT '[]',
    accommodations JSONB NOT NULL DEFAULT '[]',
    age_range TEXT,
    reading_level TEXT,
    org_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE asset_definitions (
    asset_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    base_prompt TEXT NOT NULL,
    sockets JSONB NOT NULL DEFAULT '[]',
    skin_set JSONB,
    default_world_style JSONB,
    pose_geometry JSONB,
    org_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_asset_definitions_kind ON asset_definitions (kind);
CREATE TABLE asset_sheets (
    asset_id TEXT PRIMARY KEY REFERENCES asset_definitions(asset_id) ON DELETE CASCADE,
    refs JSONB NOT NULL,
    sheet_image TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    generation_params JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE asset_instances (
    instance_id TEXT PRIMARY KEY,
    canvas_id TEXT NOT NULL,
    definition_id TEXT REFERENCES asset_definitions(asset_id) ON DELETE RESTRICT,
    inline_definition JSONB,
    parent_id TEXT REFERENCES asset_instances(instance_id) ON DELETE SET NULL,
    parent_socket TEXT,
    transform JSONB NOT NULL DEFAULT '{}',
    slot JSONB,
    anchor TEXT,
    occlusion JSONB NOT NULL DEFAULT '{"in_front_of": [], "behind": []}',
    personalization JSONB,
    skin_binding JSONB,
    prompt_nudge TEXT,
    visible BOOLEAN NOT NULL DEFAULT TRUE,
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    history JSONB NOT NULL DEFAULT '[]',
    z_index INTEGER NOT NULL DEFAULT 0,
    org_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((definition_id IS NULL) <> (inline_definition IS NULL))
);
CREATE INDEX ix_asset_instances_canvas ON asset_instances (canvas_id);
CREATE INDEX ix_asset_instances_org ON asset_instances (org_id);
CREATE TABLE books (
    book_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    world_style JSONB NOT NULL,
    style_volumes JSONB NOT NULL DEFAULT '[]',
    profile_id TEXT REFERENCES child_profiles(profile_id) ON DELETE SET NULL,
    org_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _require_pg() -> str:
    dsn = postgres_dsn()
    if dsn:
        return dsn
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
            "the canvas/asset scope conformance PostgreSQL leg cannot run and "
            "must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_PG_DSN is unset; the PostgreSQL leg needs a real server")


# One event loop for the whole module: the module-scoped engine pools
# connections that are bound to the loop that created them, and with
# pytest-asyncio's default function-scoped loops every test after the
# first would drive them from a foreign loop ("another operation is in
# progress").
pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pg_engine():
    """One engine per module, bound to a throwaway schema."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    dsn = _require_pg()
    schema = f"canvas_scope_conf_{uuid.uuid4().hex[:12]}"
    engine = create_async_engine(
        # Same normalization as the core persistence fixtures: the shared
        # env DSN is driver-neutral (`postgresql://`), and left verbatim
        # SQLAlchemy resolves the sync psycopg2 dialect, which is absent
        # from lean CI environments. asyncpg is the declared driver.
        dsn.replace("postgresql://", "postgresql+asyncpg://", 1),
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        # asyncpg speaks prepared statements: a multi-statement blob fails
        # with `cannot insert multiple commands into a prepared statement`,
        # so run each DDL statement on its own. The DDL strings carry no
        # semicolons inside literals (asserted by these suites passing).
        for ddl in (_CANVAS_DDL, _ASSET_DDL):
            for statement in ddl.split(";"):
                if statement.strip():
                    await conn.execute(text(statement))
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()


# ─────────────────────────────────────────────────────────────────────
# Canvas: two tenants against PgCanvasStore
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def canvas_store(pg_engine: Any) -> PgCanvasStore:
    return PgCanvasStore(pg_engine)


async def _canvas(store: PgCanvasStore, org: str, name: str = "A's canvas") -> CanvasRecord:
    return await store.create_canvas(name=name, width=64, height=64, org_id=org)


async def _layer(store: PgCanvasStore, canvas_id: str, org: str, name: str = "L") -> LayerRecord:
    return await store.add_layer(canvas_id, org_id=org, name=name, layer_type=LayerType.BACKGROUND)


class TestCanvasTwoTenants:
    async def test_a_canvas_reads_only_inside_its_org(self, canvas_store: PgCanvasStore) -> None:
        canvas = await _canvas(canvas_store, ORG_A)
        assert await canvas_store.get_canvas(canvas.id, org_id=ORG_B) is None, (
            "org B read org A's canvas by id"
        )
        assert await canvas_store.get_canvas(canvas.id, org_id=ORG_A) is not None

    async def test_listing_shows_only_the_callers_org(self, canvas_store: PgCanvasStore) -> None:
        await _canvas(canvas_store, ORG_A)
        await _canvas(canvas_store, ORG_B, name="B's canvas")
        names_a = {c.name for c in await canvas_store.list_canvases(ORG_A)}
        names_b = {c.name for c in await canvas_store.list_canvases(ORG_B)}
        assert names_a == {"A's canvas"}
        assert names_b == {"B's canvas"}

    async def test_another_orgs_canvas_cannot_be_updated(self, canvas_store: PgCanvasStore) -> None:
        canvas = await _canvas(canvas_store, ORG_A)
        canvas.name = "hijacked"
        with pytest.raises(CanvasNotFoundError):
            await canvas_store.update_canvas(canvas, org_id=ORG_B)
        fresh = await canvas_store.get_canvas(canvas.id, org_id=ORG_A)
        assert fresh is not None and fresh.name == "A's canvas"

    async def test_layers_read_only_inside_their_org(self, canvas_store: PgCanvasStore) -> None:
        canvas = await _canvas(canvas_store, ORG_A)
        layer = await _layer(canvas_store, canvas.id, ORG_A)
        assert await canvas_store.get_layer(layer.id, org_id=ORG_B) is None
        assert await canvas_store.get_layer(layer.id, org_id=ORG_A) is not None
        assert await canvas_store.list_layers(canvas.id, org_id=ORG_B) == []
        assert len(await canvas_store.list_layers(canvas.id, org_id=ORG_A)) == 1

    async def test_layers_cannot_be_added_to_another_orgs_canvas(
        self, canvas_store: PgCanvasStore
    ) -> None:
        canvas = await _canvas(canvas_store, ORG_A)
        with pytest.raises(CanvasNotFoundError):
            await _layer(canvas_store, canvas.id, ORG_B)
        assert await canvas_store.list_layers(canvas.id, org_id=ORG_A) == []

    async def test_layers_cannot_be_mutated_from_another_org(
        self, canvas_store: PgCanvasStore
    ) -> None:
        canvas = await _canvas(canvas_store, ORG_A)
        layer = await _layer(canvas_store, canvas.id, ORG_A)
        layer.name = "hijacked"
        with pytest.raises(LayerNotFoundError):
            await canvas_store.update_layer(layer, org_id=ORG_B)
        with pytest.raises(LayerNotFoundError):
            await canvas_store.remove_layer(layer.id, org_id=ORG_B)
        survivor = await canvas_store.get_layer(layer.id, org_id=ORG_A)
        assert survivor is not None and survivor.name == "L"

    async def test_reorder_outside_the_org_sees_no_layers(
        self, canvas_store: PgCanvasStore
    ) -> None:
        canvas = await _canvas(canvas_store, ORG_A)
        layer = await _layer(canvas_store, canvas.id, ORG_A)
        from maistro_canvas.types import IncompleteReorderError

        with pytest.raises(IncompleteReorderError):
            await canvas_store.reorder_layers(
                canvas.id, [{"layer_id": layer.id, "z_index": 0}], org_id=ORG_B
            )

    async def _job(self, store: PgCanvasStore, org: str) -> GenerationJobRecord:
        canvas = await _canvas(store, org)
        layer = await _layer(store, canvas.id, org)
        return await store.create_job(
            GenerationJobRecord(
                id=f"job-{uuid.uuid4().hex[:8]}",
                layer_id=layer.id,
                canvas_id=canvas.id,
                org_id=org,
            ),
            org_id=org,
        )

    async def test_jobs_read_only_inside_their_org(self, canvas_store: PgCanvasStore) -> None:
        job = await self._job(canvas_store, ORG_A)
        assert await canvas_store.get_job(job.id, org_id=ORG_B) is None
        assert await canvas_store.get_job(job.id, org_id=ORG_A) is not None
        assert await canvas_store.active_job_for_layer(job.layer_id, org_id=ORG_B) is None
        assert await canvas_store.active_job_for_layer(job.layer_id, org_id=ORG_A) is not None
        assert await canvas_store.list_jobs_for_layer(job.layer_id, org_id=ORG_B) == []
        assert len(await canvas_store.list_jobs_for_layer(job.layer_id, org_id=ORG_A)) == 1

    async def test_jobs_cannot_be_written_from_another_org(
        self, canvas_store: PgCanvasStore
    ) -> None:
        job = await self._job(canvas_store, ORG_A)
        job.status = "cancelled"
        with pytest.raises(JobNotFoundError):
            await canvas_store.update_job(job, org_id=ORG_B)
        fresh = await canvas_store.get_job(job.id, org_id=ORG_A)
        assert fresh is not None and fresh.status != "cancelled"

    async def test_a_job_cannot_be_created_on_another_orgs_canvas(
        self, canvas_store: PgCanvasStore
    ) -> None:
        canvas = await _canvas(canvas_store, ORG_A)
        with pytest.raises(CanvasNotFoundError):
            await canvas_store.create_job(
                GenerationJobRecord(
                    id=f"job-{uuid.uuid4().hex[:8]}",
                    layer_id="any",
                    canvas_id=canvas.id,
                    org_id=ORG_B,
                ),
                org_id=ORG_B,
            )

    async def test_composites_read_only_inside_their_org(self, canvas_store: PgCanvasStore) -> None:
        canvas = await _canvas(canvas_store, ORG_A)
        await canvas_store.save_composite(
            CompositeResult(canvas_id=canvas.id, image_bytes=b"x", width=8, height=8),
            org_id=ORG_A,
        )
        assert await canvas_store.latest_composite(canvas.id, org_id=ORG_B) is None
        assert await canvas_store.latest_composite(canvas.id, org_id=ORG_A) is not None

    async def test_a_canvas_can_be_updated_inside_its_org(
        self, canvas_store: PgCanvasStore
    ) -> None:
        canvas = await _canvas(canvas_store, ORG_A)
        canvas.name = "Renamed in place"
        await canvas_store.update_canvas(canvas, org_id=ORG_A)
        fresh = await canvas_store.get_canvas(canvas.id, org_id=ORG_A)
        assert fresh is not None and fresh.name == "Renamed in place"

    async def test_a_layer_can_be_updated_inside_its_org(self, canvas_store: PgCanvasStore) -> None:
        canvas = await _canvas(canvas_store, ORG_A)
        layer = await _layer(canvas_store, canvas.id, ORG_A)
        layer.name = "Retitled"
        layer.z_index = 4
        await canvas_store.update_layer(layer, org_id=ORG_A)
        fresh = await canvas_store.get_layer(layer.id, org_id=ORG_A)
        assert fresh is not None and fresh.name == "Retitled" and fresh.z_index == 4

    async def test_a_job_can_be_updated_inside_its_org(self, canvas_store: PgCanvasStore) -> None:
        job = await self._job(canvas_store, ORG_A)
        job.status = "done"
        job.result_paths = ["/done/a.png"]
        await canvas_store.update_job(job, org_id=ORG_A)
        fresh = await canvas_store.get_job(job.id, org_id=ORG_A)
        assert (
            fresh is not None and fresh.status == "done" and fresh.result_paths == ["/done/a.png"]
        )

    async def test_a_job_update_from_another_org_is_refused(
        self, canvas_store: PgCanvasStore
    ) -> None:
        from maistro_canvas.types import JobNotFoundError

        job = await self._job(canvas_store, ORG_A)
        job.status = "cancelled"
        with pytest.raises(JobNotFoundError):
            await canvas_store.update_job(job, org_id=ORG_B)

    async def test_a_composite_cannot_be_saved_for_another_orgs_canvas(
        self, canvas_store: PgCanvasStore
    ) -> None:
        canvas = await _canvas(canvas_store, ORG_A)
        with pytest.raises(CanvasNotFoundError):
            await canvas_store.save_composite(
                CompositeResult(canvas_id=canvas.id, image_bytes=b"x", width=8, height=8),
                org_id=ORG_B,
            )


# ─────────────────────────────────────────────────────────────────────
# Assets: the same two tenants over both store flavours
# ─────────────────────────────────────────────────────────────────────


def _definition(asset_id: str = "farmhouse") -> AssetDefinition:
    return AssetDefinition(
        asset_id=asset_id, kind=LayerKind.STRUCTURE, base_prompt="a small red farmhouse"
    )


def _instance(
    instance_id: str = "i1", canvas_id: str = "c1", definition: Any = "farmhouse"
) -> AssetInstance:
    return AssetInstance(instance_id=instance_id, canvas_id=canvas_id, definition=definition)


def _world_style() -> WorldStyle:
    return WorldStyle(
        era="modern",
        realism="watercolor",
        architectural_register="cottage",
        vehicle_register="1970s-pickup",
        palette_anchors=("sage", "cream"),
        fauna_realism="cute",
    )


def _profile(profile_id: str = "p1") -> ChildProfile:
    return ChildProfile(profile_id=profile_id, name="Sarah")


class TestAssetTwoTenants:
    """One body over both flavours: the in-memory twin runs it always, the
    PostgreSQL store runs it whenever a server exists, and the assertions are
    the mutation-removal arcs — remove an org predicate and one of these
    fails on both legs at once."""

    @pytest.fixture(params=["inmemory", "postgres"])
    async def store(self, request: pytest.FixtureRequest) -> AsyncIterator[Any]:
        if request.param == "inmemory":
            # Runs always: the twin must not skip when no server exists, or a
            # scope regression hides behind the PostgreSQL skip.
            yield InMemoryAssetStore()
            return
        pg_engine = request.getfixturevalue("pg_engine")
        from sqlalchemy.ext.asyncio import AsyncSession

        session = AsyncSession(pg_engine)
        try:
            yield _PgAssetFacade(session)
        finally:
            await session.rollback()
            await session.close()

    @pytest.fixture(autouse=True)
    async def _pg_tables_fresh_per_test(
        self, request: pytest.FixtureRequest
    ) -> AsyncIterator[None]:
        """Give the PostgreSQL leg the same freshness the in-memory twin
        gets from its per-test store: without this, the rows one test
        commits (book b1, farmhouse, instance i1) collide with the next
        test's setup on the shared throwaway schema."""
        yield
        params = getattr(getattr(request.node, "callspec", None), "params", {}) or {}
        if params.get("store") != "postgres":
            return
        pg_engine = request.getfixturevalue("pg_engine")
        from sqlalchemy import text

        async with pg_engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE books, asset_instances, asset_sheets, "
                    "asset_definitions, child_profiles, composite_records, "
                    "generation_jobs, layers, canvases CASCADE"
                )
            )

    # ── definitions ────────────────────────────────────────────────

    async def test_a_definition_reads_only_inside_its_org(self, store: Any) -> None:
        await store.register_definition(_definition(), org_id=ORG_A)
        assert await store.get_definition("farmhouse", org_id=ORG_B) is None
        assert await store.get_definition("farmhouse", org_id=ORG_A) is not None
        assert await store.list_definitions_by_kind("structure", org_id=ORG_B) == []
        assert len(await store.list_definitions_by_kind("structure", org_id=ORG_A)) == 1

    async def test_a_definition_cannot_be_updated_from_another_org(self, store: Any) -> None:
        await store.register_definition(_definition(), org_id=ORG_A)
        defn = await store.get_definition("farmhouse", org_id=ORG_A)
        assert defn is not None
        with pytest.raises(AssetDefinitionNotFoundError):
            await store.update_definition(defn, org_id=ORG_B)

    async def test_the_same_asset_id_cannot_be_shadowed_in_another_org(self, store: Any) -> None:
        """Ids are globally unique: org B cannot create its own row under org
        A's asset_id, which would make cross-org reads ambiguous."""
        await store.register_definition(_definition(), org_id=ORG_A)
        with pytest.raises(ValueError, match="another scope"):
            await store.register_definition(_definition(), org_id=ORG_B)

    # ── sheets ─────────────────────────────────────────────────────

    async def test_a_sheet_reads_only_inside_its_org(self, store: Any) -> None:
        await store.register_definition(_definition(), org_id=ORG_A)
        await store.upsert_sheet(
            AssetSheet(asset_id="farmhouse", refs=("/r.png",), sheet_image="/s.png"),
            org_id=ORG_A,
        )
        assert await store.get_sheet("farmhouse", org_id=ORG_B) is None
        assert await store.get_sheet("farmhouse", org_id=ORG_A) is not None

    async def test_a_sheet_cannot_be_written_or_regenerated_from_another_org(
        self, store: Any
    ) -> None:
        await store.register_definition(_definition(), org_id=ORG_A)
        with pytest.raises(AssetDefinitionNotFoundError):
            await store.upsert_sheet(
                AssetSheet(asset_id="farmhouse", refs=(), sheet_image="/x.png"),
                org_id=ORG_B,
            )
        with pytest.raises(AssetDefinitionNotFoundError):
            await store.regenerate_sheet("farmhouse", "/x.png", refs=("/r.png",), org_id=ORG_B)
        assert await store.get_sheet("farmhouse", org_id=ORG_A) is None

    # ── instances ──────────────────────────────────────────────────

    async def test_an_instance_reads_only_inside_its_org(self, store: Any) -> None:
        await store.register_definition(_definition(), org_id=ORG_A)
        await store.upsert_instance(_instance(), org_id=ORG_A)
        assert await store.get_instance("i1", org_id=ORG_B) is None
        assert await store.get_instance("i1", org_id=ORG_A) is not None
        assert await store.list_instances("c1", org_id=ORG_B) == []
        assert len(await store.list_instances("c1", org_id=ORG_A)) == 1

    async def test_an_instance_cannot_point_at_another_orgs_definition(self, store: Any) -> None:
        """The render plan resolves definitions by id; letting org B bind org
        A's definition would leak its prompt and sheet geometry."""
        await store.register_definition(_definition(), org_id=ORG_A)
        with pytest.raises(AssetDefinitionNotFoundError):
            await store.upsert_instance(_instance(), org_id=ORG_B)

    async def test_an_instance_cannot_be_removed_from_another_org(self, store: Any) -> None:
        await store.register_definition(_definition(), org_id=ORG_A)
        await store.upsert_instance(_instance(), org_id=ORG_A)
        await store.remove_instance("i1", org_id=ORG_B)
        assert await store.get_instance("i1", org_id=ORG_A) is not None

    # ── profiles ───────────────────────────────────────────────────

    async def test_a_profile_reads_only_inside_its_org(self, store: Any) -> None:
        await store.upsert_profile(_profile(), org_id=ORG_A)
        assert await store.get_profile("p1", org_id=ORG_B) is None
        assert await store.get_profile("p1", org_id=ORG_A) is not None

    async def test_a_profile_cannot_be_rewritten_from_another_org(self, store: Any) -> None:
        await store.upsert_profile(_profile(), org_id=ORG_A)
        with pytest.raises(ValueError):
            await store.upsert_profile(_profile(), org_id=ORG_B)

    # ── books ──────────────────────────────────────────────────────

    async def _book(self, store: Any, org: str, book_id: str = "b1") -> Any:
        return await store.create_book(
            book_id=book_id,
            title="T",
            world_style=_world_style(),
            style_volumes=(StyleVolume(page_range=(1, 2)),),
            org_id=org,
        )

    async def test_a_book_reads_only_inside_its_org(self, store: Any) -> None:
        await self._book(store, ORG_A)
        assert await store.get_book("b1", org_id=ORG_B) is None
        assert await store.get_book("b1", org_id=ORG_A) is not None

    async def test_a_book_cannot_be_updated_from_another_org(self, store: Any) -> None:
        book = await self._book(store, ORG_A)
        book.title = "hijacked"
        with pytest.raises(KeyError):
            await store.update_book(book, org_id=ORG_B)
        fresh = await store.get_book("b1", org_id=ORG_A)
        assert fresh is not None and fresh.title == "T"

    async def test_a_book_cannot_be_created_under_another_orgs_id(self, store: Any) -> None:
        await self._book(store, ORG_A)
        with pytest.raises(ValueError, match="another scope"):
            await self._book(store, ORG_B)

    async def test_a_book_cannot_moved_between_orgs_by_update(self, store: Any) -> None:
        """A book carrying org B's scope cannot be re-scoped in org A: the
        owner's own update that tries to move the row out is refused."""
        book = await self._book(store, ORG_A)
        book.org_id = ORG_B
        with pytest.raises(ValueError, match="cannot move"):
            await store.update_book(book, org_id=ORG_A)

    # ── success arcs the refusal tests never reach ─────────────────

    async def test_a_definition_can_be_updated_inside_its_org(self, store: Any) -> None:
        await store.register_definition(_definition(), org_id=ORG_A)
        defn = await store.get_definition("farmhouse", org_id=ORG_A)
        assert defn is not None
        updated = dataclasses.replace(defn, base_prompt="a red farmhouse")
        await store.update_definition(updated, org_id=ORG_A)
        fresh = await store.get_definition("farmhouse", org_id=ORG_A)
        assert fresh is not None and fresh.base_prompt == "a red farmhouse"

    async def test_register_definition_requires_a_non_empty_id(self, store: Any) -> None:
        with pytest.raises(ValueError, match="non-empty asset_id"):
            await store.register_definition(_definition(asset_id=""), org_id=ORG_A)

    async def test_a_book_requires_a_scope_to_be_created(self, store: Any) -> None:
        with pytest.raises(ValueError, match="within a scope"):
            await store.create_book(
                book_id="b0",
                title="Scopeless",
                world_style=_world_style(),
                org_id="",
            )

    async def test_a_book_id_cannot_collide_inside_one_org(self, store: Any) -> None:
        await self._book(store, ORG_A)
        with pytest.raises(ValueError, match="already exists"):
            await self._book(store, ORG_A)

    async def test_a_book_can_be_updated_inside_its_org(self, store: Any) -> None:
        book = await self._book(store, ORG_A)
        book.title = "Second edition"
        await store.update_book(book, org_id=ORG_A)
        fresh = await store.get_book("b1", org_id=ORG_A)
        assert fresh is not None and fresh.title == "Second edition"

    async def test_a_sheet_can_be_regenerated_inside_its_org(self, store: Any) -> None:
        await store.register_definition(_definition(), org_id=ORG_A)
        await store.upsert_sheet(
            AssetSheet(asset_id="farmhouse", refs=("/r.png",), sheet_image="/s.png"),
            org_id=ORG_A,
        )
        regen = await store.regenerate_sheet(
            "farmhouse", "/s2.png", refs=("/r.png", "/r2.png"), org_id=ORG_A
        )
        assert regen.sheet_image == "/s2.png"
        stored = await store.get_sheet("farmhouse", org_id=ORG_A)
        assert stored is not None and stored.sheet_image == "/s2.png"


class _PgAssetFacade:
    """``PostgresAssetStore`` over one session; commits after each call so the
    next call (new store or same) sees durable rows, like production wiring."""

    def __init__(self, session: Any) -> None:
        from maistro_canvas.canvas.asset_store import PostgresAssetStore

        self._session = session
        self._store = PostgresAssetStore(session)

    async def _run(self, coro: Any) -> Any:
        try:
            return await coro
        finally:
            await self._session.commit()

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._store, name)
        if not callable(attr):
            return attr

        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            return await self._run(attr(*args, **kwargs))

        return wrapped


# ─────────────────────────────────────────────────────────────────────
# The routes — scope resolved from the principal, never the request body
# ─────────────────────────────────────────────────────────────────────


class TestRoutesCarryThePrincipalScope:
    """The store predicates are only half the contract (#857): the HTTP edge
    must resolve the tenant from the authenticated principal — never a
    body-provided id — and must refuse unauthenticated calls before any
    store access. Two principals share one router/store; org B's view of
    org A's rows is 404, and an anonymous request never reaches the store.
    """

    @pytest.fixture
    def _app(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[FastAPI, InMemoryAssetStore]]:
        from fastapi import FastAPI

        from maistro_canvas.auth import get_current_user
        from maistro_canvas.canvas.asset_routes import make_router

        store = InMemoryAssetStore()
        app = FastAPI()
        app.include_router(make_router(get_store=lambda: store))

        def principal_for(org: str) -> Callable[[], CurrentUser]:
            async def _principal() -> CurrentUser:
                return CurrentUser(user_id=f"u-{org}", org_id=org)

            return _principal

        app.dependency_overrides[get_current_user] = principal_for(ORG_A)
        self._principal_for = principal_for
        yield app, store
        app.dependency_overrides.clear()

    @contextmanager
    def _as(self, client: TestClient, org: str) -> Iterator[TestClient]:
        """Re-scope an existing client's principal to ``org`` for a block."""
        from maistro_canvas.auth import get_current_user

        app = client.app
        previous = app.dependency_overrides.get(get_current_user)
        app.dependency_overrides[get_current_user] = self._principal_for(org)
        try:
            yield client
        finally:
            if previous is None:
                app.dependency_overrides.pop(get_current_user, None)
            else:
                app.dependency_overrides[get_current_user] = previous

    def _definition_body(self, asset_id: str = "farmhouse") -> dict[str, Any]:
        return {"asset_id": asset_id, "kind": "structure", "base_prompt": "a red barn"}

    def test_cross_tenant_reads_are_404_not_the_row(
        self, _app: tuple[FastAPI, InMemoryAssetStore]
    ) -> None:
        app, _ = _app
        with TestClient(app) as client:
            assert (
                client.post(
                    "/v2/canvas/asset-definitions", json=self._definition_body()
                ).status_code
                == 201
            )
            assert client.get("/v2/canvas/asset-definitions/farmhouse").status_code == 200
            with self._as(client, ORG_B):
                r = client.get("/v2/canvas/asset-definitions/farmhouse")
                assert r.status_code == 404, "org B read org A's definition"
                assert client.get("/v2/canvas/child-profiles/p1").status_code == 404

    def test_cross_tenant_writes_are_refused(
        self, _app: tuple[FastAPI, InMemoryAssetStore]
    ) -> None:
        app, _ = _app
        with TestClient(app) as client:
            client.post("/v2/canvas/asset-definitions", json=self._definition_body())
            with self._as(client, ORG_B):
                # Rewrite A's definition under B's principal.
                r = client.put(
                    "/v2/canvas/asset-definitions/farmhouse",
                    json=self._definition_body(),
                )
                assert r.status_code == 404, "org B rewrote org A's definition"
                # Bind an instance to A's definition — leaks its prompt.
                r = client.post(
                    "/v2/canvas/asset-instances",
                    json={
                        "instance_id": "i-b",
                        "canvas_id": "c-b",
                        "definition": "farmhouse",
                    },
                )
                assert r.status_code == 404, "org B bound org A's definition"
                # Shadow A's definition id in B's own scope.
                r = client.post(
                    "/v2/canvas/asset-definitions",
                    json=self._definition_body(),
                )
                assert r.status_code == 400, "org B shadowed org A's asset_id"

    def test_a_body_provided_org_id_is_a_selection_not_an_authority(
        self, _app: tuple[FastAPI, InMemoryAssetStore]
    ) -> None:
        app, _ = _app
        book = {
            "book_id": "b1",
            "title": "T",
            "world_style": {
                "era": "modern",
                "realism": "watercolor",
                "architectural_register": "cottage",
                "vehicle_register": "pickup",
                "palette_anchors": ["sage"],
                "fauna_realism": "cute",
            },
        }
        with TestClient(app) as client:
            r = client.post("/v2/canvas/books", json={**book, "org_id": ORG_B})
            assert r.status_code == 403, "body org_id overrode the principal's scope"
            assert client.post("/v2/canvas/books", json=book).status_code == 201
            with self._as(client, ORG_B):
                assert client.get("/v2/canvas/books/b1").status_code == 404


class TestRoutesRefuseUnauthenticatedRequests:
    """No principal, no store access (#857, audit 3.2): a missing or wrong
    token is 401 and an unconfigured deployment fails closed with 503."""

    @pytest.fixture
    def app(self, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
        from fastapi import FastAPI

        from maistro_canvas.canvas.asset_routes import make_router

        monkeypatch.setenv("CANVAS_API_TOKEN", "test-token")
        application = FastAPI()
        application.include_router(make_router(get_store=InMemoryAssetStore))
        return application

    def test_no_token_is_401(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            for path in (
                "/v2/canvas/asset-definitions",
                "/v2/canvas/asset-definitions/farmhouse",
                "/v2/canvas/asset-instances/i1",
                "/v2/canvas/child-profiles/p1",
                "/v2/canvas/books/b1",
                "/v2/canvas/canvases/c1/instances",
            ):
                r = client.get(path)
                assert r.status_code == 401, f"GET {path} served {r.status_code} anonymously"
            r = client.post("/v2/canvas/asset-definitions", json=self._definition_body())
            assert r.status_code == 401

    def test_wrong_token_is_401(self, app: FastAPI) -> None:
        with TestClient(app, headers={"Authorization": "Bearer not-the-token"}) as client:
            r = client.get("/v2/canvas/asset-definitions?kind=structure")
            assert r.status_code == 401

    def test_unconfigured_fails_closed_503(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastapi import FastAPI

        from maistro_canvas.canvas.asset_routes import make_router

        monkeypatch.delenv("CANVAS_API_TOKEN", raising=False)
        app = FastAPI()
        app.include_router(make_router(get_store=InMemoryAssetStore))
        with TestClient(app) as client:
            r = client.get("/v2/canvas/asset-definitions?kind=structure")
            assert r.status_code == 503

    def _definition_body(self) -> dict[str, Any]:
        return {"asset_id": "farmhouse", "kind": "structure", "base_prompt": "a red barn"}


# ─────────────────────────────────────────────────────────────────────
# The predicates themselves — the arc that runs without a server
# ─────────────────────────────────────────────────────────────────────


class TestThePredicatesExist:
    """Static half of the ratchet (#857).

    The PostgreSQL legs above need a server and skip without one; a skip is
    untested, not passing. These source-level assertions run everywhere and
    fail the day an ID-addressed query in the durable stores loses its org
    predicate — the exact mutation the Defect Ladder planted and the suite
    missed.
    """

    #: method -> a fragment that must appear in its SQL.
    _CANVAS_FRAGMENTS: ClassVar[dict[str, str]] = {
        "get_canvas": "AND org_id = :org",
        "update_canvas": "AND org_id = :org",
        "get_layer": "c.org_id = :org",
        "list_layers": "c.org_id = :org",
        "update_layer": "org_id = :org",
        "remove_layer": "c.org_id = :org",
        "reorder_layers": "c.org_id = :org",
        "create_job": "AND org_id = :org",
        "get_job": "c.org_id = :org",
        "update_job": "c.org_id = :org",
        "active_job_for_layer": "c.org_id = :org",
        "list_jobs_for_layer": "c.org_id = :org",
        "save_composite": "AND org_id = :org",
        "latest_composite": "c.org_id = :org",
        "add_layer": "AND org_id = :org",
    }

    def test_every_canvas_read_and_mutation_predicates_on_org(self) -> None:
        import inspect

        for name, fragment in self._CANVAS_FRAGMENTS.items():
            source = inspect.getsource(getattr(PgCanvasStore, name))
            assert fragment in source, (
                f"PgCanvasStore.{name} lost its org predicate "
                f"(no {fragment!r} in its SQL) — cross-tenant reads would return rows"
            )

    def test_the_canvas_protocol_makes_org_a_required_keyword(self) -> None:
        """A wiring that forgets the scope must fail loudly, not default it."""
        import inspect

        from maistro_canvas.protocols import CanvasStore

        for name in ("get_canvas", "get_layer", "get_job", "update_canvas", "update_layer"):
            sig = inspect.signature(getattr(CanvasStore, name))
            assert "org_id" in sig.parameters, f"CanvasStore.{name} takes no org_id"
            param = sig.parameters["org_id"]
            assert param.kind is inspect.Parameter.KEYWORD_ONLY, (
                f"CanvasStore.{name}.org_id must be keyword-only"
            )
            assert param.default is inspect.Parameter.empty, (
                f"CanvasStore.{name}.org_id must have no default — a default is a bypass"
            )

    def test_generation_job_receipts_carry_their_scope(self) -> None:
        record = GenerationJobRecord(id="j", layer_id="l", canvas_id="c", org_id="org-1")
        assert record.to_dict()["org_id"] == "org-1"
        assert GenerationJobRecord(id="j", layer_id="l", canvas_id="c").org_id == ""
