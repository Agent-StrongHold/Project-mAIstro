"""``PgCanvasStore`` blob contract — the durable half of the image path (#2311).

``store_blob``/``get_blob`` existed for the governed image egress;
``read_blob`` is the whole-row read the authorized byte-serving route needs:
bytes, the media type they were stored under, and the write-time metadata
whose Workspace scope anchors the route's authorization. These legs run
against real PostgreSQL (they skip without ``MAISTRO_TEST_PG_DSN``) because
the contract is durability: a store instance with no shared process state
must read the row a previous write committed, and the metadata coercion must
survive the driver's jsonb shape. The pure coercion branches are unit-tested
without a server.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import pytest_asyncio

from maistro.testing.postgres import postgres_dsn
from maistro_canvas.canvas.store import PgCanvasStore, _coerce_blob_metadata

pytestmark = pytest.mark.asyncio(loop_scope="module")


def _require_pg() -> str:
    dsn = postgres_dsn()
    if dsn:
        return dsn
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
            "the Canvas blob-store PostgreSQL leg cannot run and must not be "
            "silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_PG_DSN is unset; the PostgreSQL leg needs a real server")


def _async_dsn(url: str) -> str:
    """The asyncpg engine form, whatever driver the env DSN named."""
    base = url.split("://", 1)[1]
    return f"postgresql+asyncpg://{base}"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def blob_engine() -> Iterator[Any]:
    """One engine per module over a throwaway schema with ``canvas_blobs``."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    dsn = _require_pg()
    schema = f"canvas_blob_{uuid.uuid4().hex[:12]}"
    engine = create_async_engine(
        _async_dsn(dsn),
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        for statement in (
            "CREATE TABLE canvas_blobs (id TEXT PRIMARY KEY)",
            "ALTER TABLE canvas_blobs ADD COLUMN IF NOT EXISTS data BYTEA NOT NULL",
            "ALTER TABLE canvas_blobs ADD COLUMN IF NOT EXISTS format TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE canvas_blobs ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'",
            "ALTER TABLE canvas_blobs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        ):
            await conn.execute(text(statement))
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()


# ── Pure coercion branches (no server) ────────────────────────────────


class TestBlobMetadataCoercion:
    def test_a_jsonb_text_decodes(self) -> None:
        raw = '{"source": "governed-image-egress", "workspace_id": "ws-1"}'
        assert _coerce_blob_metadata(raw)["workspace_id"] == "ws-1"

    def test_a_native_dict_passes_through(self) -> None:
        raw = {"workspace_id": "ws-2"}
        assert _coerce_blob_metadata(raw) == {"workspace_id": "ws-2"}

    def test_anything_else_reads_as_an_empty_stamp(self) -> None:
        assert _coerce_blob_metadata(None) == {}
        assert _coerce_blob_metadata(b"bytes") == {}


# ── The durable contract (real PostgreSQL) ────────────────────────────


class TestBlobStoreContract:
    async def test_store_read_round_trip_carries_bytes_media_type_and_scope(
        self, blob_engine: Any
    ) -> None:
        store = PgCanvasStore(blob_engine)
        png = b"\x89PNG\r\n\x1a\nstore-read-roundtrip"
        ref = await store.store_blob(
            png,
            format="image/png",
            metadata={
                "source": "governed-image-egress",
                "workspace_id": "ws-e2e",
                "project_id": "proj-root",
            },
        )
        # The reference is a canonical UUID: the presentation seam classifies
        # stored image values by exactly this shape.
        assert str(uuid.UUID(ref)) == ref

        record = await store.read_blob(ref)
        assert record is not None
        assert record.id == ref
        assert record.data == png
        assert record.format == "image/png"
        assert record.metadata["workspace_id"] == "ws-e2e"
        assert record.metadata["project_id"] == "proj-root"
        assert record.metadata["source"] == "governed-image-egress"

    async def test_a_fresh_store_instance_reads_the_committed_row(self, blob_engine: Any) -> None:
        store = PgCanvasStore(blob_engine)
        payload = b"\x89PNG\r\n\x1a\ncommitted-row"
        ref = await store.store_blob(payload, format="image/png", metadata={})
        # What a process restart leaves behind is the database row only.
        fresh = PgCanvasStore(blob_engine)
        record = await fresh.read_blob(ref)
        assert record is not None and record.data == payload

    async def test_an_unknown_id_reads_as_absence(self, blob_engine: Any) -> None:
        store = PgCanvasStore(blob_engine)
        assert await store.read_blob(str(uuid.uuid4())) is None
        assert await store.get_blob(str(uuid.uuid4())) is None

    async def test_get_blob_and_read_blob_answer_the_same_row(self, blob_engine: Any) -> None:
        store = PgCanvasStore(blob_engine)
        payload = b"\x89PNG\r\n\x1a\nsame-row"
        ref = await store.store_blob(payload, format="image/png", metadata={})
        assert await store.get_blob(ref) == payload
        record = await store.read_blob(ref)
        assert record is not None and record.data == payload
