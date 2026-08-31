"""Real SQLAlchemy row/result coverage for the Design project store (#815)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from maistro_design.stores import PgDesignProjectStore


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
