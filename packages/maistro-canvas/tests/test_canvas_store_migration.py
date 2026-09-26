"""The root alembic chain creates every table ``PgCanvasStore`` touches (#286).

Until migration 044 nothing in this repository did: the only DDL for
``canvases``, ``layers``, ``generation_jobs``, ``composite_records`` and
``canvas_blobs`` was test-local, so a database migrated to head could not run
the Canvas store, and nothing noticed because no test ran the store against
the chain's own schema.

- A static check, no server: every table named in ``store.py``'s SQL is left
  behind by the root chain's upgrades (read the way the durable-table gate
  reads them).
- PostgreSQL legs, each in a database of its own so ``alembic`` can run the
  whole chain from empty without touching the one it borrows the server
  from: ``upgrade head`` then a real store round trip; re-applying 044 over
  tables that already exist; adopting a hand-made pre-044 shape; and
  ``downgrade``. They skip without ``MAISTRO_TEST_PG_DSN``, and
  ``MAISTRO_REQUIRE_PG_LEGS`` turns that skip into a failure.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

from maistro.testing.postgres import postgres_dsn
from maistro_canvas.canvas import store as store_module
from maistro_canvas.canvas.store import PgCanvasStore
from maistro_canvas.types import (
    CompositeResult,
    GenerationJobRecord,
    JobLeaseLostError,
    JobStatus,
)

ROOT = Path(__file__).resolve().parents[3]
CANVAS_TABLES = {"canvases", "layers", "generation_jobs", "composite_records", "canvas_blobs"}
PARENT_REVISION = "042"
REVISION = "044"
ORG = "org-migration"

_TABLE_REFERENCE = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([a-z_][a-z0-9_]*)")


def _inventory_gate() -> ModuleType:
    path = ROOT / "scripts" / "check-durable-table-inventory.py"
    spec = importlib.util.spec_from_file_location("check_durable_table_inventory", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def _store_tables() -> set[str]:
    source = Path(store_module.__file__).read_text()
    return {name for name in _TABLE_REFERENCE.findall(source) if name != "candidate"}


def _root_chain_tables() -> set[str]:
    gate = _inventory_gate()
    events = []
    for path in sorted((ROOT / "alembic" / "versions").glob("*.py")):
        events.extend(gate.migration_events(path.read_text(), path=str(path)))
    return {found.table for found in gate._net(events)}


class TestTheChainOwnsTheStoreSchema:
    def test_the_store_names_exactly_the_canvas_tables(self) -> None:
        """Pins the reader below: a regex that found nothing would make the
        next test pass on an empty set."""
        assert _store_tables() == CANVAS_TABLES

    def test_every_table_the_store_touches_is_created_by_the_root_chain(self) -> None:
        missing = _store_tables() - _root_chain_tables()
        assert not missing, f"PgCanvasStore reads tables no root migration creates: {missing}"


# ─────────────────────────────────────────────────────────────────────
# PostgreSQL legs
# ─────────────────────────────────────────────────────────────────────


def _require_pg() -> str:
    dsn = postgres_dsn()
    if dsn:
        return dsn
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
            "the Canvas store migration leg cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_PG_DSN is unset; the PostgreSQL leg needs a real server")


def _sync_dsn(url: str) -> str:
    """psycopg's own connect() wants the bare libpq form."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _execute(url: str, sql: str, *, autocommit: bool = False) -> list[tuple[object, ...]]:
    import psycopg

    with psycopg.connect(_sync_dsn(url), autocommit=autocommit) as conn, conn.cursor() as cur:
        cur.execute(sql)  # type: ignore[arg-type]
        return list(cur.fetchall()) if cur.description else []


@pytest.fixture
def empty_database() -> Iterator[str]:
    """A database of its own, dropped afterwards: the chain runs from empty."""
    from sqlalchemy.engine import make_url

    dsn = _require_pg()
    name = f"canvas_mig_{uuid.uuid4().hex[:12]}"
    _execute(dsn, f'CREATE DATABASE "{name}"', autocommit=True)
    url = make_url(dsn).set(database=name).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        _execute(dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', autocommit=True)


def _alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": _sync_dsn(url)},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"


def _tables(url: str) -> set[str]:
    rows = _execute(url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    return {str(row[0]) for row in rows}


def _columns(url: str, table: str) -> set[str]:
    rows = _execute(
        url,
        "SELECT column_name FROM information_schema.columns"
        f" WHERE table_schema = 'public' AND table_name = '{table}'",
    )
    return {str(row[0]) for row in rows}


async def _round_trip(url: str, *, reorder: bool = True) -> None:
    """Every store write the Canvas pipeline makes, read back through the store."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        _sync_dsn(url).replace("postgresql://", "postgresql+asyncpg://", 1)
    )
    try:
        store = PgCanvasStore(engine)
        canvas = await store.create_canvas(name="cover", width=64, height=48, org_id=ORG)
        fetched = await store.get_canvas(canvas.id, org_id=ORG)
        assert fetched is not None and (fetched.width, fetched.height) == (64, 48)

        background = await store.add_layer(
            canvas.id, name="sky", layer_type="background", org_id=ORG
        )
        figure = await store.add_layer(canvas.id, name="hero", layer_type="character", org_id=ORG)
        assert [layer.id for layer in await store.list_layers(canvas.id, org_id=ORG)] == [
            background.id,
            figure.id,
        ]
        if reorder:
            await store.reorder_layers(
                canvas.id,
                [
                    {"layer_id": background.id, "z_index": figure.z_index},
                    {"layer_id": figure.id, "z_index": background.z_index},
                ],
                org_id=ORG,
            )
            assert [layer.id for layer in await store.list_layers(canvas.id, org_id=ORG)] == [
                figure.id,
                background.id,
            ]

        job = GenerationJobRecord(
            id=str(uuid.uuid4()),
            layer_id=background.id,
            canvas_id=canvas.id,
            action="generate",
            status="pending",
            model_id="probe-model",
            prompt="a dawn sky",
            params={"steps": 4},
        )
        await store.create_job(job, org_id=ORG)
        claimed = await store.claim_next_pending("worker-a", lease_seconds=60)
        assert claimed is not None and claimed.id == job.id
        assert (claimed.status, claimed.attempts, claimed.leased_by) == ("running", 1, "worker-a")
        assert claimed.lease_expires_at is not None

        done = dataclasses.replace(
            claimed,
            status=JobStatus.DONE,
            result_paths=["blob://sky"],
            completed_at=datetime.now(UTC),
            leased_by=None,
            lease_expires_at=None,
        )
        with pytest.raises(JobLeaseLostError):
            await store.update_job(
                done, org_id=ORG, expected_leased_by="worker-b", expected_attempts=1
            )
        await store.update_job(done, org_id=ORG, expected_leased_by="worker-a", expected_attempts=1)
        stored_job = await store.get_job(job.id, org_id=ORG)
        assert stored_job is not None
        assert (stored_job.status, stored_job.result_paths) == (JobStatus.DONE, ["blob://sky"])
        assert stored_job.params == {"steps": 4}

        composite = CompositeResult(
            canvas_id=canvas.id,
            image_bytes=b"\x89PNG-probe",
            width=64,
            height=48,
            layer_snapshot=[{"layer_id": background.id}],
        )
        await store.save_composite(composite, org_id=ORG)
        latest = await store.latest_composite(canvas.id, org_id=ORG)
        assert latest is not None
        assert (latest.image_bytes, latest.layer_snapshot) == (
            b"\x89PNG-probe",
            [{"layer_id": background.id}],
        )

        blob_id = await store.store_blob(b"pixels", format="png", metadata={"layer": "sky"})
    finally:
        await engine.dispose()

    rows = _execute(url, f"SELECT data, format, metadata FROM canvas_blobs WHERE id = '{blob_id}'")
    assert rows == [(b"pixels", "png", {"layer": "sky"})]


class TestTheChainRunsTheStore:
    async def test_upgrade_head_on_an_empty_database_serves_the_store(
        self, empty_database: str
    ) -> None:
        _alembic(empty_database, "upgrade", "head")
        assert _tables(empty_database) >= CANVAS_TABLES
        await _round_trip(empty_database)

    async def test_reapplying_over_existing_tables_keeps_their_rows(
        self, empty_database: str
    ) -> None:
        _alembic(empty_database, "upgrade", "head")
        await _round_trip(empty_database)
        _alembic(empty_database, "stamp", PARENT_REVISION)
        _alembic(empty_database, "upgrade", "head")
        assert _execute(empty_database, "SELECT count(*) FROM canvases") == [(1,)]
        assert _execute(empty_database, "SELECT count(*) FROM canvas_blobs") == [(1,)]
        await _round_trip(empty_database)

    async def test_a_hand_made_pre_migration_schema_is_adopted(self, empty_database: str) -> None:
        """What a live deployment has: the POC's tables without the SPEC-203
        lease columns and without ``canvas_blobs``, holding a row."""
        _alembic(empty_database, "upgrade", PARENT_REVISION)
        _execute(
            empty_database,
            """
            CREATE TABLE canvases (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, width INTEGER NOT NULL,
                height INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE layers (
                id TEXT PRIMARY KEY,
                canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
                name TEXT NOT NULL, z_index INTEGER NOT NULL DEFAULT 0,
                UNIQUE (canvas_id, z_index)
            );
            CREATE TABLE generation_jobs (
                id TEXT PRIMARY KEY,
                layer_id TEXT NOT NULL REFERENCES layers(id) ON DELETE CASCADE,
                canvas_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE composite_records (
                id TEXT PRIMARY KEY,
                canvas_id TEXT NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
                image_bytes BYTEA NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL
            );
            INSERT INTO canvases (id, name, width, height) VALUES ('legacy', 'old', 8, 8);
            """,
        )
        _alembic(empty_database, "upgrade", "head")

        assert {"attempts", "max_attempts", "leased_by", "lease_expires_at"} <= _columns(
            empty_database, "generation_jobs"
        )
        assert "canvas_blobs" in _tables(empty_database)
        assert _execute(empty_database, "SELECT id, org_id, layer_count FROM canvases") == [
            ("legacy", "", 0)
        ]
        unique = _execute(
            empty_database,
            "SELECT count(*) FROM pg_constraint"
            " WHERE conrelid = 'layers'::regclass AND contype = 'u'",
        )
        assert unique == [(1,)], "an adopted table's own unique constraint is not duplicated"
        # The adopted non-deferrable constraint is kept, so a swap still collides there.
        await _round_trip(empty_database, reorder=False)

    def test_downgrade_removes_the_tables(self, empty_database: str) -> None:
        _alembic(empty_database, "upgrade", "head")
        _alembic(empty_database, "downgrade", PARENT_REVISION)
        assert CANVAS_TABLES & _tables(empty_database) == set()
        _alembic(empty_database, "upgrade", REVISION)
        assert _tables(empty_database) >= CANVAS_TABLES

    def test_the_pending_claim_index_is_partial(self, empty_database: str) -> None:
        _alembic(empty_database, "upgrade", "head")
        rows = _execute(
            empty_database,
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_generation_jobs_pending'",
        )
        assert len(rows) == 1 and "WHERE (status = 'pending'::text)" in str(rows[0][0])
