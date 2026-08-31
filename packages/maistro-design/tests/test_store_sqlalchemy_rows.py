"""Real SQLAlchemy row/result coverage for the Design project store (#815)."""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from maistro_design.stores import PgDesignProjectStore
from maistro_design.trust import TrustTier
from maistro_design.types import ArtifactKind, ArtifactNode, DesignOutput, DesignProject, OutputFormat


def _read_store() -> tuple[PgDesignProjectStore, Any]:
    """A PgDesignProjectStore reading actual SQLAlchemy Row objects from SQLite."""
    engine = create_engine("sqlite://")
    connection = engine.connect()
    connection.execute(
        text(
            """
            CREATE TABLE design_projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                skill_slug TEXT NOT NULL,
                design_system_slug TEXT NOT NULL,
                org_id TEXT NOT NULL,
                team_id TEXT,
                trust_tier TEXT,
                canvas_id TEXT,
                discovery_json TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE design_outputs (
                project_id TEXT NOT NULL,
                format TEXT NOT NULL,
                content TEXT NOT NULL,
                url TEXT,
                trust_tier TEXT,
                metadata_json TEXT,
                created_at TEXT,
                run_id TEXT,
                node_run_id TEXT,
                attempt_id TEXT
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO design_projects
                (id, name, skill_slug, design_system_slug, org_id, team_id,
                 trust_tier, canvas_id, discovery_json, created_at, updated_at)
            VALUES
                ('p-one', 'One', 'poster', 'default', 'org-a', NULL,
                 't3', NULL, NULL, '2026-08-31T00:00:00+00:00', '2026-08-31T00:00:00+00:00'),
                ('p-two', 'Two', 'poster', 'default', 'org-a', NULL,
                 't2', NULL, NULL, '2026-08-30T00:00:00+00:00', '2026-08-30T00:00:00+00:00'),
                ('p-other', 'Other', 'poster', 'default', 'org-b', NULL,
                 't1', NULL, NULL, '2026-08-29T00:00:00+00:00', '2026-08-29T00:00:00+00:00')
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO design_outputs
                (project_id, format, content, url, trust_tier, metadata_json, created_at,
                 run_id, node_run_id, attempt_id)
            VALUES
                ('p-one', 'html', '<main>one</main>', NULL, 't3', '{"source":"real-row"}',
                 '2026-08-31T00:00:00+00:00', 'run-1', 'node-1', 'attempt-1'),
                ('p-two', 'html', '<main>two</main>', NULL, 't2', NULL,
                 '2026-08-30T00:00:00+00:00', NULL, NULL, NULL)
            """
        )
    )
    connection.commit()

    class Session:
        async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
            return connection.execute(statement, params or {})

    @asynccontextmanager
    async def factory():
        yield Session()

    return PgDesignProjectStore(session_factory=factory), (connection, engine)


def _close_read_store(resources: Any) -> None:
    connection, engine = resources
    connection.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_get_reads_real_sqlalchemy_rows() -> None:
    store, resources = _read_store()
    try:
        project = await store.get("p-one", org_id="org-a")
    finally:
        _close_read_store(resources)

    assert project is not None
    assert project.id == "p-one"
    assert len(project.outputs) == 1
    assert project.outputs[0].content == "<main>one</main>"
    assert project.outputs[0].metadata == {"source": "real-row"}
    assert project.outputs[0].run_id == "run-1"


@pytest.mark.asyncio
async def test_list_by_skill_reads_real_sqlalchemy_rows() -> None:
    store, resources = _read_store()
    try:
        projects = await store.list_by_skill("poster", "org-a")
    finally:
        _close_read_store(resources)

    assert [project.id for project in projects] == ["p-one", "p-two"]
    assert projects[0].outputs[0].attempt_id == "attempt-1"


@pytest.mark.asyncio
async def test_list_by_org_reads_real_sqlalchemy_rows() -> None:
    store, resources = _read_store()
    try:
        projects = await store.list_by_org("org-a")
    finally:
        _close_read_store(resources)

    assert [project.id for project in projects] == ["p-one", "p-two"]
    assert all(project.org_id == "org-a" for project in projects)


@pytest.mark.asyncio
async def test_postgres_persisted_output_round_trips_through_shipped_store() -> None:
    dsn = os.getenv("MAISTRO_TEST_PG_DSN", "").strip()
    if not dsn:
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")

    pytest.importorskip("asyncpg")
    engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = PgDesignProjectStore(session_factory=factory)
    org_id = f"design-row-{uuid.uuid4()}"
    project = DesignProject(
        name="SQLAlchemy row round-trip",
        skill_slug="poster",
        design_system_slug="default",
        org_id=org_id,
        trust_tier=TrustTier.T3,
        outputs=[
            DesignOutput(
                root=ArtifactNode(
                    key="root",
                    kind=ArtifactKind.FILE,
                    format=OutputFormat.HTML,
                    value="<main>persisted</main>",
                ),
                trust_tier=TrustTier.T3,
                metadata={"source": "postgres"},
                run_id="run-row-readback",
                node_run_id="node-row-readback",
                attempt_id="attempt-row-readback",
            )
        ],
    )

    persisted_id: str | None = None
    try:
        persisted = await store.create(project)
        persisted_id = persisted.id
        loaded = await store.get(persisted.id, org_id=org_id)

        assert loaded is not None
        assert loaded.id == persisted.id
        assert len(loaded.outputs) == 1
        assert loaded.outputs[0].content == "<main>persisted</main>"
        assert loaded.outputs[0].metadata == {"source": "postgres"}
        assert loaded.outputs[0].run_id == "run-row-readback"
        assert loaded.outputs[0].node_run_id == "node-row-readback"
        assert loaded.outputs[0].attempt_id == "attempt-row-readback"
    finally:
        if persisted_id is not None:
            await store.delete(persisted_id, org_id=org_id)
        await engine.dispose()
