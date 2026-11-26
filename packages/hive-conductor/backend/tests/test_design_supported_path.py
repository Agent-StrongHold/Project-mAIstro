"""E2E: the supported Design path, end to end over real PostgreSQL (#1826).

The shipped configuration is a Compose-provided `postgresql://` DATABASE_URL.
Before #1826 that spelling raised inside `create_async_engine` — the bare
scheme selects the psycopg2 dialect, and psycopg2 is not installed in an async
runtime — the exception was swallowed into `None`, and startup reported the
store disabled as if no database had ever been configured. This module walks
the one supported path with the spelling Compose actually emits:

1. a clean database migrated by the authoritative root chain only
   (`alembic upgrade head` from empty — no second environment);
2. `DATABASE_URL` set to that database in the bare `postgresql://` spelling;
3. the real `start_design_service` composition — registries, engine,
   `PgDesignProjectStore` — and project create/read/list through the real
   routes, with the org scope rules intact;
4. a restart (caches cleared, singletons rebuilt) reading the same project
   back through a *fresh* store — durable truth, not process-local state.

The store assertions execute database operations; no engine-dialect-only claim
and no mock substitutes for them. Skips without `MAISTRO_TEST_PG_DSN`;
`MAISTRO_REQUIRE_PG_LEGS` turns that skip into a failure — for this module a
skip and a pass are the same green tick (the same contract as the Canvas
supported-path module, whose PostgreSQL plumbing helpers are duplicated here
because sibling test directories cannot import each other's fixtures).
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
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from maistro.testing.postgres import postgres_dsn

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from routes import design as design_routes  # noqa: E402
from services import design_service  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]

ORG_A = "design-e2e-org"
ORG_B = "design-e2e-other-org"

#: Discovery responses satisfying the `login-flow` skill's required fields —
#: the same pairing `test_design_service_startup` proves generates offline.
DISCOVERY = {
    "skill_slug": "login-flow",
    "responses": {"auth_methods": "email and passkey", "brand_tone": "calm"},
    "design_system_slug": "default",
}


class _Settings:
    open_design_url = None
    open_design_api_key = None


# ── PostgreSQL plumbing (same contract as the Canvas supported-path module) ──


def _require_pg() -> str:
    dsn = postgres_dsn()
    if dsn:
        return dsn
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
            "the Design supported-path E2E cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_PG_DSN is unset; the Design supported-path E2E needs a real server")


def _sync_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1).replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )


def _execute(url: str, sql: str, *, autocommit: bool = False) -> list[tuple[object, ...]]:
    import psycopg

    with psycopg.connect(_sync_dsn(url), autocommit=autocommit) as conn, conn.cursor() as cur:
        cur.execute(sql)  # type: ignore[arg-type]
        return list(cur.fetchall()) if cur.description else []


@pytest.fixture(scope="module")
def compose_database() -> Iterator[str]:
    """A clean database migrated by the root chain, as a Compose-spelling URL.

    The yielded string is deliberately the *bare* `postgresql://` form —
    byte-for-byte the environment shape docker-compose.yml hands the hive
    service — so everything downstream proves itself against the spelling the
    defect shipped with, not against the spelling that already worked.
    """
    from sqlalchemy.engine import make_url

    dsn = _require_pg()
    name = f"design_e2e_{uuid.uuid4().hex[:12]}"
    _execute(dsn, f'CREATE DATABASE "{name}"', autocommit=True)
    url = make_url(_sync_dsn(dsn)).set(database=name).render_as_string(hide_password=False)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env={**os.environ, "DATABASE_URL": url},
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
        missing = {"design_projects", "design_outputs"} - tables
        assert not missing, f"root chain left the Design store no tables: {missing}"
        yield url
    finally:
        _execute(dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', autocommit=True)


@pytest.fixture()
async def design_api(
    compose_database: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """The real composition, started the way the app lifespan starts it.

    `DATABASE_URL` is set to the throwaway database in the Compose spelling,
    the engine caches are cleared so nothing answers from another test's
    environment, and `start_design_service` runs for real. Restored after so
    the suite's other tests never see this database.
    """
    monkeypatch.setenv("DATABASE_URL", compose_database)
    design_service._get_async_engine.cache_clear()
    design_service._get_async_session_factory.cache_clear()
    monkeypatch.setattr(design_service, "_engine_singleton", None)
    monkeypatch.setattr(design_service, "_store_singleton", None)
    monkeypatch.setattr(design_service, "_renderer_registry_singleton", None)
    monkeypatch.setattr(design_service, "_status", design_service.DesignServiceStatus())

    await design_service.start_design_service(_Settings())
    status = design_service.get_design_status()
    assert status.ready, f"the real composition did not start: {status.cause}"
    assert status.store_cause is None, f"the store did not come up: {status.store_cause}"

    app = FastAPI()
    app.include_router(design_routes.router)

    @app.middleware("http")
    async def _org_header(request: Request, call_next: Any) -> Any:
        # The deployment-facing way a scope reaches these routes; absent here,
        # they fall back to the deployment default exactly as in production.
        org = request.headers.get("x-test-org")
        if org is not None:
            request.state.org_id = org
        return await call_next(request)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    engine = design_service._get_async_engine()
    await design_service.stop_design_service()
    if engine is not None:
        await engine.dispose()


async def _create_project(client: AsyncClient, org: str | None = None) -> dict[str, Any]:
    headers = {"x-test-org": org} if org is not None else {}
    response = await client.post("/design/projects", json=DISCOVERY, headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


# ── The acceptance walk ──────────────────────────────────────────────────────


class TestTheSupportedPath:
    async def test_the_store_is_real_and_asyncpg_backed(self, design_api):
        """AC: the Compose spelling produces the supported asyncpg-backed
        engine and a real `PgDesignProjectStore` — inside the started
        composition, not against a hand-built one."""
        engine = design_service._get_async_engine()
        assert engine is not None
        assert engine.dialect.driver == "asyncpg"
        store = design_service.get_design_store()
        assert type(store).__name__ == "PgDesignProjectStore"

    async def test_create_read_list_through_the_real_routes(self, design_api):
        """AC: the persisted project is written, read back with its outputs,
        and listed — every step a database operation through the shipped
        routes."""
        created = await _create_project(design_api)
        project_id = created["id"]

        fetched = await design_api.get(f"/design/projects/{project_id}")
        assert fetched.status_code == 200, fetched.text
        body = fetched.json()
        assert body["id"] == project_id
        assert body["skill_slug"] == "login-flow"
        assert body["org_id"] == design_routes.CONDUCTOR_ORG_ID
        assert body["outputs"], "the persisted project carries no outputs"

        listed = await design_api.get("/design/projects")
        assert listed.status_code == 200, listed.text
        assert project_id in [p["id"] for p in listed.json()]

    async def test_the_scope_rules_hold(self, design_api):
        """AC: the existing org scope rules survive the wiring — another
        org's caller gets a 404 (existence elsewhere is itself scoped
        information) and an empty list, not someone else's project."""
        created = await _create_project(design_api, org=ORG_A)

        other = await design_api.get(
            f"/design/projects/{created['id']}", headers={"x-test-org": ORG_B}
        )
        assert other.status_code == 404
        other_list = await design_api.get("/design/projects", headers={"x-test-org": ORG_B})
        assert [p["id"] for p in other_list.json()] == []

    async def test_a_restart_reads_the_persisted_project(self, design_api, compose_database):
        """AC: reinitialization reads durable truth. The restart is the real
        teardown/startup pair — caches cleared, singletons rebuilt, a *fresh*
        store over the same URL — and the project created before it is read
        after it, in its own scope."""
        created = await _create_project(design_api, org=ORG_A)
        project_id = created["id"]

        engine = design_service._get_async_engine()
        await design_service.stop_design_service()
        if engine is not None:
            await engine.dispose()
        await design_service.start_design_service(_Settings())

        # A different store instance than the one that wrote the row.
        assert design_service.get_design_store() is not None
        fetched = await design_api.get(
            f"/design/projects/{project_id}", headers={"x-test-org": ORG_A}
        )
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["id"] == project_id

        still_listed = await design_api.get("/design/projects", headers={"x-test-org": ORG_A})
        assert project_id in [p["id"] for p in still_listed.json()]
