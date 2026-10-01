"""Issue #398 acceptance: the one job-store contract, and the health read.

Two suites share this module:

1. **Store contract legs** — the behavioral bodies from
   ``maistro_canvas.testing.job_store_contract`` run against the in-memory
   fake and, when a server is available, the production ``PgCanvasStore``:
   claim gates on ``next_retry_at``, the reaper writes the shared backoff,
   over-budget rows are unclaimable but surfaced, queue stats mirror the
   states the store's own writers produce, and both legs structurally
   implement the ``CanvasJobStore`` protocol. Running identical bodies
   against both legs is what makes fake/production drift fail a leg instead
   of passing silently.

2. **Queue-health route** — ``GET /api/canvas/jobs/health`` exposes the
   org-scoped counts, registered ahead of ``/jobs/{job_id}`` so the literal
   ``health`` segment cannot be swallowed by the id route.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro_canvas.testing.job_store_contract import (
    InMemoryJobStore,
    require_pg,
    run_job_store_contract,
    seed_job,
)
from maistro_canvas.types import GenerationJobRecord, JobQueueStats

pytestmark = pytest.mark.asyncio(loop_scope="module")

TEST_TOKEN = "test-canvas-token"
AUTH_HEADER = {"Authorization": f"Bearer {TEST_TOKEN}"}


# ─────────────────────────────────────────────────────────────────────
# Leg 1: the in-memory fake — always runs
# ─────────────────────────────────────────────────────────────────────


async def test_contract_in_memory_leg() -> None:
    await run_job_store_contract(InMemoryJobStore())


async def test_missing_pg_dsn_is_a_skip_but_requirement_mode_fails() -> None:
    """``MAISTRO_REQUIRE_PG_LEGS`` turns the production leg's skip into a
    failure — a CI recipe that guarantees a server must not silently lose
    the drift guard."""

    from maistro.testing.postgres import postgres_dsn

    if postgres_dsn():
        pytest.skip("a server is configured; the pg leg below runs for real")
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setenv("MAISTRO_REQUIRE_PG_LEGS", "1")
        monkey.delenv("MAISTRO_TEST_PG_DSN", raising=False)
        with pytest.raises(RuntimeError, match="MAISTRO_REQUIRE_PG_LEGS"):
            require_pg()
    finally:
        monkey.undo()


# ─────────────────────────────────────────────────────────────────────
# Leg 2: the production store — a real server, throwaway schema
# ─────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pg_store() -> Iterator[Any]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from maistro_canvas.canvas.store import PgCanvasStore
    from maistro_canvas.testing.canvas_schema import CANVAS_SCHEMA_DDL

    dsn = require_pg()
    schema = f"canvas_job_contract_{uuid.uuid4().hex[:12]}"
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://", 1),
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        # One statement at a time: asyncpg cannot run a multi-statement blob
        # as one prepared statement (the conformance suite's finding).
        for statement in CANVAS_SCHEMA_DDL.split(";"):
            if statement.strip():
                await conn.execute(text(statement))
    yield PgCanvasStore(engine)
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()


async def test_contract_postgres_leg(pg_store: Any) -> None:
    await run_job_store_contract(pg_store)


async def test_pg_job_round_trip_preserves_next_retry_at(pg_store: Any) -> None:
    """The durable column survives a row rebuild — the gate is only as real
    as its persistence (issue #398's 'durable' requirement)."""
    from datetime import UTC, datetime, timedelta

    org = "contract-roundtrip"
    when = datetime.now(UTC) + timedelta(hours=1)
    job = await seed_job(pg_store, org=org, job_id="job-rt", attempts=1, next_retry_at=when)
    reloaded = await pg_store.get_job(job.id, org_id=org)
    assert reloaded is not None
    assert reloaded.next_retry_at is not None
    assert abs(reloaded.next_retry_at - when) < timedelta(seconds=1)


# ─────────────────────────────────────────────────────────────────────
# Queue-health route
# ─────────────────────────────────────────────────────────────────────


class _NoopExecutor:
    pass


class _NoopCompositor:
    pass


def _client(store: InMemoryJobStore) -> TestClient:
    from maistro_canvas.canvas.routes import _make_canvas_router

    app = FastAPI()
    app.include_router(
        _make_canvas_router(
            store=store,  # type: ignore[arg-type]
            executor=_NoopExecutor(),  # type: ignore[arg-type]
            compositor=_NoopCompositor(),  # type: ignore[arg-type]
        ),
        prefix="/api/canvas",
    )
    return TestClient(app)


def test_queue_health_route_exposes_org_scoped_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", TEST_TOKEN)
    store = InMemoryJobStore()

    async def seed() -> None:
        await store.create_job(
            GenerationJobRecord(
                id="job-health",
                layer_id="layer-health",
                canvas_id="canvas-health",
                org_id="default",
            ),
            org_id="default",
        )

    asyncio.run(seed())
    client = _client(store)

    response = client.get("/api/canvas/jobs/health", headers=AUTH_HEADER)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"org_id", "pending", "running", "stuck", "retrying", "exhausted"}
    assert body == {
        "org_id": "default",
        "pending": 1,
        "running": 0,
        "stuck": 0,
        "retrying": 0,
        "exhausted": 0,
    }


def test_queue_health_route_refuses_unauthenticated_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", TEST_TOKEN)
    client = _client(InMemoryJobStore())
    response = client.get("/api/canvas/jobs/health")
    assert response.status_code == 401


def test_queue_health_route_is_not_shadowed_by_the_job_id_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/jobs/{job_id}`` must not swallow the literal ``health`` segment:
    a shadowed health route answers 404 (or worse, leaks a job lookup)."""
    monkeypatch.setenv("CANVAS_API_TOKEN", TEST_TOKEN)
    client = _client(InMemoryJobStore())
    response = client.get("/api/canvas/jobs/health", headers=AUTH_HEADER)
    assert response.status_code == 200, response.text
    assert "detail" not in response.json()


def test_job_queue_stats_is_part_of_the_store_protocol() -> None:
    """The health read is contract, not a cast-away: the typed protocol names
    it, so a store without it fails mypy and the runtime isinstance here."""
    from maistro_canvas.protocols import CanvasJobStore

    assert isinstance(InMemoryJobStore(), CanvasJobStore)
    assert hasattr(CanvasJobStore, "job_queue_stats")
    assert JobQueueStats.__dataclass_params__.frozen
