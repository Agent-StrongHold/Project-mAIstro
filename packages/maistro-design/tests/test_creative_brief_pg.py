"""CreativeBrief persistence against real PostgreSQL (the migration's backend).

SQLite cannot round-trip a ``CAST(:payload AS jsonb)`` insert (its CAST
affinity turns JSON text into ``0``), so the created-row half of the store
contract — full document round-trip, the unique-version race, the FK to
``canonical_projects`` — is held here, against a server migrated by the real
alembic chain.

Skips without ``MAISTRO_TEST_DATABASE_URL``; the CI postgres leg sets it
against a database the chain has been applied to (same assumption as
``tests/migrations/``). Each run uses a fresh Workspace/Project/lineage id and
cleans its rows, so it can share the configured database.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")


def _require_postgres() -> str:
    """The asyncpg URL, or a skip — unless a server is declared guaranteed."""
    if DATABASE_URL:
        return DATABASE_URL
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is empty: "
            "the CreativeBrief PostgreSQL leg cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; these need a real PostgreSQL server")


def _asyncpg_url() -> str:
    url = _require_postgres()
    if url.startswith("postgresql+asyncpg://"):
        return url
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


def _sessions() -> tuple[object, object]:
    """An async engine + sessionmaker over the configured database."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(_asyncpg_url())
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _brief(lineage_id: str, workspace_id: str, project_id: str, version: int = 1):
    from maistro_design.brief import ArtifactRequest, BriefReference, CreativeBrief

    return CreativeBrief(
        lineage_id=lineage_id,
        version=version,
        workspace_id=workspace_id,
        project_id=project_id,
        goal_id=f"goal-{lineage_id}",
        goal_revision=3,
        goal_owner_agent_id="agent-orchestrator",
        persona=BriefReference(
            kind="persona", ref_id="persona-1", version="p-v7", workspace_id=workspace_id
        ),
        design_system=BriefReference(kind="design_system", ref_id="brand-x", version="2026.09"),
        audience="home bakers",
        required_messages=("Fresh daily",),
        required_facts=(),  # kept minimal; depth is covered by the contract suite
        artifact_requests=(
            ArtifactRequest(
                request_id="ig-square", channel="social", format="png", dimensions="1080x1080"
            ),
        ),
        created_by="principal-1",
    )


async def _seed_scope(session_factory: object, workspace_id: str, project_id: str) -> None:
    """Register one canonical Project in the claimed Workspace."""
    from sqlalchemy import text

    factory = session_factory  # async_sessionmaker
    async with factory() as session:  # type: ignore[operator]
        await session.execute(
            text(
                "INSERT INTO canonical_projects (project_id, workspace_id, is_root, payload) "
                "VALUES (:p, :w, FALSE, CAST(:payload AS jsonb)) "
                "ON CONFLICT (project_id) DO NOTHING"
            ),
            {"p": project_id, "w": workspace_id, "payload": "{}"},
        )
        await session.commit()


async def _cleanup(engine: object, workspace_id: str, project_id: str) -> None:
    from sqlalchemy import text

    async with engine.begin() as conn:  # type: ignore[operator]
        await conn.execute(
            text("DELETE FROM design_creative_briefs WHERE workspace_id = :w"), {"w": workspace_id}
        )
        await conn.execute(
            text("DELETE FROM canonical_projects WHERE project_id = :p"), {"p": project_id}
        )
        await conn.execute(
            text("DELETE FROM canonical_workspaces WHERE workspace_id = :w"), {"w": workspace_id}
        )
    await engine.dispose()  # type: ignore[operator]


@pytest.mark.contract("behavioral")
async def test_brief_round_trips_through_postgres() -> None:
    from maistro_design.brief import BriefVersionConflictError, CrossWorkspaceReferenceError
    from maistro_design.brief_store import PgCreativeBriefStore

    lineage = f"lineage-{uuid4().hex}"
    workspace = f"ws-{uuid4().hex}"
    project = f"proj-{uuid4().hex}"
    engine, session_factory = _sessions()
    store = PgCreativeBriefStore(session_factory=session_factory)
    try:
        await _seed_scope(session_factory, workspace, project)

        v1 = await store.create(_brief(lineage, workspace, project, version=1))
        read = await store.get(v1.brief_id, workspace_id=workspace)
        assert read is not None
        assert read == v1
        assert read.persona.version == "p-v7"
        assert read.design_system_version == "2026.09"

        # A redirect mints a second version; the first is untouched.
        v2 = await store.create(v1.new_version(goal_revision=4, change_note="outcome bump"))
        latest = await store.latest(lineage, workspace_id=workspace)
        assert latest is not None and latest == v2
        assert latest.goal_revision == 4
        versions = await store.list_versions(lineage, workspace_id=workspace)
        assert [brief.version for brief in versions] == [1, 2]
        assert versions[0] == v1

        # Version identity is first-writer-wins.
        with pytest.raises(BriefVersionConflictError):
            await store.create(_brief(lineage, workspace, project, version=1))

        # Cross-Workspace stays structurally impossible.
        other_workspace = f"ws-{uuid4().hex}"
        with pytest.raises(CrossWorkspaceReferenceError):
            await store.create(_brief(f"lineage-{uuid4().hex}", other_workspace, project))

        # Other-Workspace reads answer absent.
        assert await store.get(v1.brief_id, workspace_id=other_workspace) is None
        assert await store.latest(lineage, workspace_id=other_workspace) is None
    finally:
        await _cleanup(engine, workspace, project)
