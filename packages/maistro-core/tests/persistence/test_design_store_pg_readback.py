"""Cross-package PostgreSQL readback proof for the shipped Design store (#815)."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from maistro_design.stores import PgDesignProjectStore
from maistro_design.trust import TrustTier
from maistro_design.types import (
    ArtifactKind,
    ArtifactNode,
    DesignOutput,
    DesignProject,
    OutputFormat,
)


@pytest.mark.asyncio
async def test_design_persisted_output_round_trips_on_postgres() -> None:
    """The migrated PostgreSQL profile can create and read a real Design output."""
    dsn = os.getenv("MAISTRO_TEST_PG_DSN", "").strip()
    if not dsn:
        pytest.skip("set MAISTRO_TEST_PG_DSN to run the PostgreSQL Design leg")

    pytest.importorskip("asyncpg")
    engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = PgDesignProjectStore(session_factory=factory)
    org_id = f"design-row-{uuid.uuid4()}"
    project = DesignProject(
        id=f"design-project-{uuid.uuid4()}",
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
