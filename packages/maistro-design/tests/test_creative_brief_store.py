"""SQL composition and scope guards for the CreativeBrief store (#774).

The store tests drive ``PgCreativeBriefStore`` against a real SQLite schema
through the same tiny async facade ``test_store_sqlalchemy_rows.py`` uses,
because what is under test is the SQL the store composes and the guards
around it: workspace scoping on every operation, the cross-Workspace project
check, and first-writer-wins version minting.

The ``CAST(:payload AS jsonb)`` insert is PostgreSQL-shaped — SQLite's CAST
affinity turns any JSON text into ``0`` — so a created-row *round-trip* is
held by ``test_creative_brief_pg.py`` against a real PostgreSQL, the only
backend the inventory lists for this table. Here, created rows are exercised
for their guard behavior, and read paths run over rows seeded raw.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, get_args

import pytest
from sqlalchemy import create_engine, text

from maistro_design.brief import (
    BriefVersionConflictError,
    CreativeBrief,
    CrossWorkspaceReferenceError,
)
from maistro_design.brief_store import PgCreativeBriefStore
from maistro_design.types import DesignScopeError

pytestmark = pytest.mark.contract("boundary")


DDL_STATEMENTS = (
    """
    CREATE TABLE canonical_projects (
        project_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE design_creative_briefs (
        brief_id TEXT PRIMARY KEY,
        lineage_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        supersedes_brief_id TEXT,
        workspace_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        goal_id TEXT NOT NULL,
        goal_revision INTEGER NOT NULL,
        payload TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT,
        CONSTRAINT uq_design_creative_briefs_lineage_version UNIQUE (lineage_id, version)
    )
    """,
)


def _store(*, project_rows: list[tuple[str, str]] | None = None):
    """A store over SQLite, plus the connection so tests can seed and read."""
    engine = create_engine("sqlite://")
    connection = engine.connect()
    for statement in DDL_STATEMENTS:
        connection.execute(text(statement))
    for project_id, workspace_id in project_rows or []:
        connection.execute(
            text("INSERT INTO canonical_projects (project_id, workspace_id) VALUES (:p, :w)"),
            {"p": project_id, "w": workspace_id},
        )
    connection.commit()

    class Session:
        async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
            return connection.execute(statement, params or {})

        async def commit(self) -> None:
            connection.commit()

    @asynccontextmanager
    async def factory():
        yield Session()

    return PgCreativeBriefStore(session_factory=factory), (connection, engine)


def _seed_brief(
    connection: Any,
    *,
    brief_id: str,
    lineage_id: str,
    version: int,
    workspace_id: str = "ws-1",
    payload: dict[str, Any] | None = None,
) -> None:
    """Insert a fully-formed row the way PostgreSQL would have written it."""
    connection.execute(
        text(
            """
            INSERT INTO design_creative_briefs
            (brief_id, lineage_id, version, supersedes_brief_id, workspace_id, project_id,
             goal_id, goal_revision, payload, created_by, created_at)
            VALUES (:brief_id, :lineage_id, :version, :supersedes_brief_id, :workspace_id,
                    :project_id, :goal_id, :goal_revision, :payload, :created_by, :created_at)
            """
        ),
        {
            "brief_id": brief_id,
            "lineage_id": lineage_id,
            "version": version,
            "supersedes_brief_id": None,
            "workspace_id": workspace_id,
            "project_id": "proj-1",
            "goal_id": "goal-1",
            "goal_revision": 3,
            "payload": json.dumps(payload or {"brief_id": brief_id, "version": version}),
            "created_by": "principal-1",
            "created_at": f"2026-09-28T00:00:0{version}+00:00",
        },
    )
    connection.commit()


def _brief(version: int = 1, lineage_id: str = "lineage-1") -> CreativeBrief:
    return CreativeBrief.model_validate(
        {
            "brief_id": f"brief-{version}",
            "lineage_id": lineage_id,
            "version": version,
            "workspace_id": "ws-1",
            "project_id": "proj-1",
            "goal_id": "goal-1",
            "goal_revision": 3,
            "goal_owner_agent_id": "agent-1",
            "persona": {
                "kind": "persona",
                "ref_id": "persona-1",
                "version": "p-v7",
                "workspace_id": "ws-1",
            },
            "design_system": {"kind": "design_system", "ref_id": "brand-x"},
        }
    )


@pytest.mark.contract("behavioral")
async def test_get_reads_a_seeded_row_back_as_its_brief() -> None:
    store, resources = _store(project_rows=[("proj-1", "ws-1")])
    connection, engine = resources
    try:
        payload = {
            "brief_id": "brief-1",
            "lineage_id": "lineage-1",
            "version": 1,
            "workspace_id": "ws-1",
            "project_id": "proj-1",
            "goal_id": "goal-1",
            "goal_revision": 3,
            "goal_owner_agent_id": "agent-1",
            "persona": {"kind": "persona", "ref_id": "persona-1", "version": "p-v7"},
            "design_system": {"kind": "design_system", "ref_id": "brand-x"},
        }
        _seed_brief(
            connection, brief_id="brief-1", lineage_id="lineage-1", version=1, payload=payload
        )
        brief = await store.get("brief-1", workspace_id="ws-1")
        assert brief is not None
        assert brief.goal_id == "goal-1"
        assert brief.goal_revision == 3
        assert brief.persona.version == "p-v7"
    finally:
        connection.close()
        engine.dispose()


@pytest.mark.contract("behavioral")
async def test_latest_and_list_versions_order_by_version() -> None:
    store, resources = _store(project_rows=[("proj-1", "ws-1")])
    connection, engine = resources

    def _payload(version: int) -> dict[str, Any]:
        return {
            "brief_id": f"brief-{version}",
            "lineage_id": "lineage-1",
            "version": version,
            "workspace_id": "ws-1",
            "project_id": "proj-1",
            "goal_id": "goal-1",
            "goal_revision": 3,
            "goal_owner_agent_id": "agent-1",
            "persona": {"kind": "persona", "ref_id": "persona-1", "version": "p-v7"},
            "design_system": {"kind": "design_system", "ref_id": "brand-x"},
        }

    try:
        for version in (1, 2, 3):
            _seed_brief(
                connection,
                brief_id=f"brief-{version}",
                lineage_id="lineage-1",
                version=version,
                payload=_payload(version),
            )
        latest = await store.latest("lineage-1", workspace_id="ws-1")
        assert latest is not None and latest.version == 3
        versions = await store.list_versions("lineage-1", workspace_id="ws-1")
        assert [brief.version for brief in versions] == [1, 2, 3]
        # Provenance stays exact per version — a redirect did not rewrite v1.
        assert versions[0].brief_id == "brief-1"
    finally:
        connection.close()
        engine.dispose()


@pytest.mark.contract("behavioral")
async def test_reads_in_another_workspace_answer_absent() -> None:
    store, resources = _store(project_rows=[("proj-1", "ws-1")])
    connection, engine = resources
    try:
        _seed_brief(connection, brief_id="brief-1", lineage_id="lineage-1", version=1)
        assert await store.get("brief-1", workspace_id="ws-2") is None
        assert await store.latest("lineage-1", workspace_id="ws-2") is None
        assert await store.list_versions("lineage-1", workspace_id="ws-2") == []
    finally:
        connection.close()
        engine.dispose()


@pytest.mark.parametrize("operation", ["get", "latest", "list_versions"])
async def test_blank_workspace_scope_is_refused(operation: str) -> None:
    store, resources = _store()
    connection, engine = resources
    try:
        with pytest.raises(DesignScopeError):
            if operation == "get":
                await store.get("brief-1", workspace_id="")
            elif operation == "latest":
                await store.latest("lineage-1", workspace_id="")
            else:
                await store.list_versions("lineage-1", workspace_id="")
    finally:
        connection.close()
        engine.dispose()


async def test_blank_scope_is_refused_on_create() -> None:
    store, resources = _store()
    connection, engine = resources
    try:
        brief = _brief().model_copy(update={"workspace_id": ""})
        with pytest.raises(DesignScopeError):
            await store.create(brief)  # type: ignore[arg-type]
    finally:
        connection.close()
        engine.dispose()


async def test_create_refuses_a_project_registered_to_another_workspace() -> None:
    store, resources = _store(project_rows=[("proj-1", "ws-2")])
    connection, engine = resources
    try:
        with pytest.raises(CrossWorkspaceReferenceError):
            await store.create(_brief())
    finally:
        connection.close()
        engine.dispose()


async def test_create_refuses_an_unregistered_project() -> None:
    store, resources = _store(project_rows=[])
    connection, engine = resources
    try:
        with pytest.raises(CrossWorkspaceReferenceError):
            await store.create(_brief())
    finally:
        connection.close()
        engine.dispose()


async def test_duplicate_lineage_version_is_a_conflict_not_an_overwrite() -> None:
    """First writer wins: the second writer of (lineage, version) loses loudly."""
    store, resources = _store(project_rows=[("proj-1", "ws-1")])
    connection, engine = resources
    try:
        _seed_brief(connection, brief_id="brief-1", lineage_id="lineage-1", version=1)
        with pytest.raises(BriefVersionConflictError):
            await store.create(_brief(version=1, lineage_id="lineage-1"))
    finally:
        connection.close()
        engine.dispose()


@pytest.mark.contract("behavioral")
async def test_create_commits_a_new_version_within_scope() -> None:
    """A version the lineage has not minted yet commits (row visible after)."""
    store, resources = _store(project_rows=[("proj-1", "ws-1")])
    connection, engine = resources
    try:
        _seed_brief(connection, brief_id="brief-1", lineage_id="lineage-1", version=1)
        await store.create(_brief(version=2, lineage_id="lineage-1"))
        row = connection.execute(
            text(
                "SELECT workspace_id, project_id, goal_id, goal_revision, version "
                "FROM design_creative_briefs WHERE brief_id = 'brief-2'"
            )
        ).fetchone()
        assert row is not None
        mapping = row._mapping if hasattr(row, "_mapping") else row
        assert mapping["workspace_id"] == "ws-1"
        assert mapping["goal_revision"] == 3
        assert mapping["version"] == 2
    finally:
        connection.close()
        engine.dispose()


def test_brief_reference_kind_vocabulary_is_closed() -> None:
    """The reference kinds are exactly the canonical things a brief may point at."""
    from maistro_design.brief import BriefReferenceKind

    assert set(get_args(BriefReferenceKind)) == {
        "persona",
        "design_system",
        "goal",
        "delegation",
        "graph_template",
        "graph",
        "artifact",
    }
