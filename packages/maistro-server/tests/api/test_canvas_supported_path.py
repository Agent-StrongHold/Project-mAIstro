"""E2E: the supported Canvas path, end to end over real PostgreSQL (#851).

The shipped surface is ``/v2/canvas`` in ``maistro_server`` backed by the
``PgCanvasStore`` the application lifecycle wires (#851). Before the M3-B
repair nothing connected the three: the API answered 503, the store's tables
lived outside the root migration chain, and a second, orphan Alembic tree held
the lease columns. This module walks the one supported path:

1. a clean database migrated by the authoritative root chain only
   (``alembic upgrade head`` from empty — no second environment);
2. design CRUD through the real HTTP routes over the real store, wired by the
   same ``_wire_canvas_ability`` helper the lifespan calls;
3. the durable job lifecycle the store's lease columns exist for: canonical
   admission, retryable failure (bounded, requeued), terminal failure
   (visible, error recorded), worker crash → lease expiry → reclaim by a
   restarted worker (exactly once), and every truth read back through a
   *fresh* store instance so nothing passes because of process-local state.

Skips without ``MAISTRO_TEST_PG_DSN``; ``MAISTRO_REQUIRE_PG_LEGS`` turns that
skip into a failure (same contract as the Canvas store migration suite).
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.store import InMemoryRunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.testing.postgres import postgres_dsn
from maistro_canvas.canvas.executor import CanvasExecutor
from maistro_canvas.canvas.retry_policy import RetryBackoff
from maistro_canvas.canvas.runner import LEASE_EXPIRED_MESSAGE, CanvasJobRunner
from maistro_canvas.canvas.store import PgCanvasStore
from maistro_canvas.protocols import ImageData
from maistro_canvas.types import JobStatus

ROOT = Path(__file__).resolve().parents[4]

ORG = "org-e2e"

#: No-wait retry schedule shared by the store, the runner and the reaper in
#: these tests, so a requeue's durable ``next_retry_at`` never delays a claim
#: (mirrors ``canvas_testing.job_store_contract.ZERO_BACKOFF``).
ZERO_BACKOFF = RetryBackoff(base_seconds=0.0, factor=1.0, cap_seconds=0.0)


# ── PostgreSQL plumbing (same contract as test_canvas_store_migration) ───


def _require_pg() -> str:
    dsn = postgres_dsn()
    if dsn:
        return dsn
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
            "the supported-path E2E cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_PG_DSN is unset; the supported-path E2E needs a real server")


def _sync_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _async_dsn(url: str) -> str:
    return _sync_dsn(url).replace("postgresql://", "postgresql+asyncpg://", 1)


def _execute(url: str, sql: str, *, autocommit: bool = False) -> list[tuple[object, ...]]:
    import psycopg

    with psycopg.connect(_sync_dsn(url), autocommit=autocommit) as conn, conn.cursor() as cur:
        cur.execute(sql)  # type: ignore[arg-type]
        return list(cur.fetchall()) if cur.description else []


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[str]:
    """A database of its own, migrated by the authoritative root chain only.

    This is the clean-install path from the docs: ``alembic upgrade head``
    against an empty database, run in the repository root with the same env
    resolver the server reads. If the chain cannot produce a Canvas-capable
    schema by itself, every test below fails — which is the point.
    """
    from sqlalchemy.engine import make_url

    dsn = _require_pg()
    name = f"canvas_e2e_{uuid.uuid4().hex[:12]}"
    _execute(dsn, f'CREATE DATABASE "{name}"', autocommit=True)
    url = make_url(dsn).set(database=name).render_as_string(hide_password=False)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env={**os.environ, "DATABASE_URL": _sync_dsn(url)},
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stderr}"
        tables = {
            str(row[0])
            for row in _execute(url, "SELECT tablename FROM pg_tables WHERE schemaname='public'")
        }
        missing = {"canvases", "layers", "generation_jobs"} - tables
        assert not missing, f"root chain left the Canvas store no tables: {missing}"
        yield url
    finally:
        _execute(dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', autocommit=True)


@pytest.fixture()
async def store(migrated_database: str) -> AsyncIterator[PgCanvasStore]:
    """A fresh store per test: asyncpg connections are event-loop bound, and
    each test gets its own loop. The *database* (module fixture) is shared;
    no state is (org-scoped rows aside).

    The store carries the zero backoff schedule so a requeue's durable
    ``next_retry_at`` gate is immediately claimable — these tests assert the
    attempt/retry bookkeeping, not wall-clock backoff timing (the runner and
    store must share one schedule, exactly as in production composition).
    """
    engine: AsyncEngine = create_async_engine(_async_dsn(migrated_database))
    yield PgCanvasStore(engine, retry_backoff=ZERO_BACKOFF)
    await engine.dispose()


@pytest.fixture()
async def api(store: PgCanvasStore) -> AsyncIterator[AsyncClient]:
    """The supported wiring, exactly as the server lifespan performs it."""
    from maistro_server.api.canvas import router as canvas_router
    from maistro_server.main import _wire_canvas_ability

    app = FastAPI()
    app.include_router(canvas_router)
    assert _wire_canvas_ability(app, store._engine) is True
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


# ── Execution-side fakes (the provider boundary the runner drives) ───────


class _FakeImageClient:
    """Pops one scripted behaviour per generate() call, then repeats the last."""

    def __init__(self, *behaviours: Any) -> None:
        self.script = list(behaviours)
        self.calls = 0

    async def generate(self, **kwargs: Any) -> list[ImageData]:
        behaviour = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        self.calls += 1
        if isinstance(behaviour, Exception):
            raise behaviour
        width, height = int(kwargs.get("width", 8)), int(kwargs.get("height", 8))
        return [ImageData(width=width, height=height, url=url) for url in behaviour]


class _FakeRegistry:
    def is_registered(self, model_id: str) -> bool:
        return model_id == "probe-model"

    def get_default_draft(self) -> str:
        return "probe-model"


class _PassWarden:
    async def scan_prompt(self, prompt: str) -> str:
        return prompt


async def _runtime(store: PgCanvasStore, image_client: _FakeImageClient) -> CanvasExecutor:
    """The canonical executor the composition seam builds — real adapter.

    The scope comes from the caller's authorization path, as in production:
    a canonical Project root created under the workspace the runtime names.
    """
    from maistro_canvas.canvas.composition import build_canvas_runtime

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-e2e")
    runtime = build_canvas_runtime(
        store=store,
        image_client=image_client,
        model_registry=_FakeRegistry(),
        warden=_PassWarden(),
        run_store=InMemoryRunStore(project_store=projects),
        workspace_id="ws-e2e",
        project_id=root.project_id,
        lease_seconds=1,
        poll_interval=0.01,
        reap_interval=0.05,
    )
    return runtime.executor


def _runner(store: PgCanvasStore, executor: CanvasExecutor, worker_id: str) -> CanvasJobRunner:
    return CanvasJobRunner(
        store=store,
        executor=executor,
        worker_id=worker_id,
        lease_seconds=1,
        retry_backoff=ZERO_BACKOFF,
    )


async def _admit(
    store: PgCanvasStore, executor: CanvasExecutor, *, prompt: str = "a dawn sky"
) -> Any:
    """Admit through the product path: canvas → layer → canonical start_job."""
    canvas = await store.create_canvas(name="e2e cover", width=32, height=32, org_id=ORG)
    layer = await store.add_layer(canvas.id, name="sky", layer_type="background", org_id=ORG)
    return await executor.start_job(
        canvas_id=canvas.id,
        layer_id=layer.id,
        org_id=ORG,
        action="generate",
        model_id="probe-model",
        prompt=prompt,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )


# ── 1. Clean migration + API CRUD over the real store ────────────────────


class TestCleanMigrationApiCrud:
    async def test_design_crud_round_trips_through_postgres(
        self, api: AsyncClient, store: PgCanvasStore
    ) -> None:
        # Create: 201, and the row is durable, not process-local.
        created = await api.post(
            "/v2/canvas/designs",
            json={"name": "Book cover", "width": 800, "height": 600},
        )
        assert created.status_code == 201, created.text
        design = created.json()
        assert design["name"] == "Book cover"

        # A store instance with no shared memory with the API sees the row.
        durable = await PgCanvasStore(store._engine).get_canvas(design["id"], org_id="dev")
        assert durable is not None and durable.width == 800

        # Read / update through the API.
        fetched = await api.get(f"/v2/canvas/designs/{design['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["layers"] == []

        renamed = await api.put(
            f"/v2/canvas/designs/{design['id']}", json={"name": "Renamed cover"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Renamed cover"

        listing = await api.get("/v2/canvas/designs")
        assert [d["id"] for d in listing.json()] == [design["id"]]

        # Soft-delete: gone from the API, archived marker in the database.
        deleted = await api.delete(f"/v2/canvas/designs/{design['id']}")
        assert deleted.status_code == 200
        assert (await api.get(f"/v2/canvas/designs/{design['id']}")).status_code == 404
        archived = await store.get_canvas(design["id"], org_id="dev")
        assert archived is not None and archived.archived_at is not None

    async def test_the_supported_wiring_answers_other_than_503(self, api: AsyncClient) -> None:
        response = await api.get("/v2/canvas/designs")
        assert response.status_code == 200
        assert response.json() == []

    async def test_another_principal_reads_nothing_of_ours(self, store: PgCanvasStore) -> None:
        from maistro_server.api.canvas import router as canvas_router
        from maistro_server.main import _wire_canvas_ability

        await store.create_canvas(name="alice's", width=8, height=8, org_id="alice")

        app = FastAPI()
        app.include_router(canvas_router)
        assert _wire_canvas_ability(app, store._engine) is True
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as dev_client:
            # The unauthenticated fallback owner is "dev"; alice's canvas —
            # a different org — must read as absent, not as a filtered row.
            list_response = await dev_client.get("/v2/canvas/designs")
            assert list_response.status_code == 200
            assert list_response.json() == []


# ── 2. Durable job lifecycle over the real lease columns ─────────────────


class TestDurableJobLifecycle:
    async def test_retryable_failure_is_bounded_then_terminal_failure_is_visible(
        self, store: PgCanvasStore, api: AsyncClient
    ) -> None:
        executor = await _runtime(store, _FakeImageClient(RuntimeError("provider 500")))
        runner = _runner(store, executor, "worker-a")
        job = await _admit(store, executor)
        assert job.status == JobStatus.PENDING

        # Attempts 1 and 2 fail and requeue (retry budget: max_attempts=3).
        assert await runner.tick_once() is True
        requeued = await store.get_job(job.id, org_id=ORG)
        assert requeued is not None and requeued.status == JobStatus.PENDING
        assert requeued.attempts == 1
        assert await runner.tick_once() is True
        requeued = await store.get_job(job.id, org_id=ORG)
        assert requeued is not None and requeued.attempts == 2

        # Attempt 3 exhausts the budget: terminal, with the *classified* error
        # recorded — the sanitiser turns the raw provider exception into the
        # provider-failure class rather than swallowing it.
        assert await runner.tick_once() is True
        failed = await store.get_job(job.id, org_id=ORG)
        assert failed is not None and failed.status == JobStatus.FAILED
        assert failed.attempts == failed.max_attempts == 3
        assert failed.error_message is not None and "provider error" in failed.error_message
        assert "provider 500" not in failed.error_message  # raw cause sanitised away
        assert failed.completed_at is not None

        # Durable truth: a fresh store over the same database reads the same
        # terminal state, and no worker can requeue a FAILED job.
        fresh = PgCanvasStore(store._engine, retry_backoff=ZERO_BACKOFF)
        assert await fresh.claim_next_pending("worker-b", lease_seconds=1) is None
        again = await fresh.get_job(job.id, org_id=ORG)
        assert again is not None and again.status == JobStatus.FAILED

        # The API surface reads the same durable rows — scoped: the unauthenticated
        # caller is org "dev", so the org-e2e design stays invisible, and a dev
        # design created over HTTP lists exactly once.
        mine = await api.post(
            "/v2/canvas/designs", json={"name": "dev design", "width": 8, "height": 8}
        )
        assert mine.status_code == 201
        designs = await api.get("/v2/canvas/designs")
        assert designs.status_code == 200
        assert [d["name"] for d in designs.json()] == ["dev design"]

    async def test_success_after_a_retry_persists_the_result(self, store: PgCanvasStore) -> None:
        executor = await _runtime(
            store, _FakeImageClient(RuntimeError("transient"), ["blob://variant-1"])
        )
        runner = _runner(store, executor, "worker-a")
        job = await _admit(store, executor)

        assert await runner.tick_once() is True  # fails, requeued
        assert await runner.tick_once() is True  # succeeds
        done = await store.get_job(job.id, org_id=ORG)
        assert done is not None and done.status == JobStatus.DONE
        assert done.attempts == 2
        assert done.result_paths == ["blob://variant-1"]
        assert done.completed_at is not None

    async def test_worker_crash_is_reclaimed_exactly_once_by_a_restarted_worker(
        self, store: PgCanvasStore
    ) -> None:
        # Worker A claims, then dies before doing anything: the lease row is
        # all that survives it.
        import asyncio

        executor = await _runtime(store, _FakeImageClient(["blob://variant-1"]))
        job = await _admit(store, executor)

        claimed = await store.claim_next_pending("worker-a", lease_seconds=1)
        assert claimed is not None and claimed.id == job.id
        assert claimed.status == JobStatus.RUNNING and claimed.leased_by == "worker-a"

        # Lease expires; the reaper requeues the orphaned job.
        await asyncio.sleep(1.2)
        reaped = await store.reap_expired_leases()
        assert [j.id for j in reaped] == [job.id]
        requeued = await store.get_job(job.id, org_id=ORG)
        assert requeued is not None and requeued.status == JobStatus.PENDING
        assert requeued.attempts == 1  # the crash consumed an attempt
        assert requeued.leased_by is None

        # Restart: a brand-new runner instance (fresh process, same store)
        # claims it once and completes it exactly once.
        runner_b = _runner(store, executor, "worker-b")
        assert await runner_b.tick_once() is True
        done = await store.get_job(job.id, org_id=ORG)
        assert done is not None and done.status == JobStatus.DONE
        assert done.result_paths == ["blob://variant-1"]

        # No duplicate accepted output: the done job claims nothing, the
        # reaper no longer sees it, and a second restart tick finds no work.
        assert await store.claim_next_pending("worker-c", lease_seconds=1) is None
        assert await store.reap_expired_leases() == []
        assert await runner_b.tick_once() is False

    async def test_lease_lost_at_the_retry_ceiling_becomes_a_visible_failure(
        self, store: PgCanvasStore
    ) -> None:
        import asyncio

        executor = await _runtime(store, _FakeImageClient(["blob://never-used"]))
        job = await _admit(store, executor)

        claimed = await store.claim_next_pending("worker-a", lease_seconds=1)
        assert claimed is not None
        # The worker dies on its last attempt: pull the ceiling forward to the
        # consumed attempt so the reaper must terminalize, not requeue.
        claimed.max_attempts = 1
        await store.update_job(claimed, org_id=ORG)

        await asyncio.sleep(1.2)
        runner = _runner(store, executor, "worker-a")
        reaped = await runner.reap_once()
        assert [j.id for j in reaped] == [job.id]
        failed = await store.get_job(job.id, org_id=ORG)
        assert failed is not None and failed.status == JobStatus.FAILED
        assert failed.error_message == LEASE_EXPIRED_MESSAGE
        assert await store.claim_next_pending("worker-b", lease_seconds=1) is None
