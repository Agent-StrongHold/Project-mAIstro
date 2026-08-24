"""The three-backend spine harness, shared by every conformance suite here.

Lives in a conftest rather than beside one suite: `test_spine_conformance`
and `test_retention_conformance` must drive *the same* fixture, or "all three
backends agree" quietly becomes "all three backends were each asked something
slightly different".
"""

from __future__ import annotations

from typing import Any

import aiosqlite
import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.store import InMemoryRunStore

WORKSPACE = "workspace-1"


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def spine(request: pytest.FixtureRequest, pg_pool: Any) -> Any:
    """A (run_store, project_id) pair on each backend, isolated per test."""
    if request.param == "postgres":
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.runs.pg_store import PgRunStore

        # A fresh Workspace per test: the tables are shared and durable, so
        # isolating by scope is cheaper and truer than truncating between tests.
        workspace = f"{WORKSPACE}-{request.node.name}"
        projects = PgProjectScopeStore(pg_pool)
        root = await projects.create_root(workspace)
        project = await projects.create(
            workspace_id=workspace, parent_project_id=root.project_id, name="Durable"
        )
        yield PgRunStore(pg_pool, project_store=projects), workspace, project.project_id
        return

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    project = await projects.create(
        workspace_id=WORKSPACE, parent_project_id=root.project_id, name="Durable"
    )
    if request.param == "memory":
        yield InMemoryRunStore(project_store=projects), WORKSPACE, project.project_id
        return

    from maistro.runs.sqlite_store import SqliteRunStore

    conn = await aiosqlite.connect(":memory:")
    store = SqliteRunStore(conn, project_store=projects)
    await store.ensure_schema()
    try:
        yield store, WORKSPACE, project.project_id
    finally:
        await conn.close()


@pytest.fixture
async def memory_spine() -> Any:
    """The same shape `spine` yields, pinned to the store with no environment
    gate.

    Acceptance-criterion markers go here rather than on `spine`.
    `scripts/ac_outcome_plugin.py` counts a skip as no evidence — "an
    environment-gated test that never ran is not evidence the criterion holds"
    — and `spine`'s postgres leg skips wherever `MAISTRO_TEST_PG_DSN` is unset,
    which includes the Quality gate job. A criterion marked on `spine` is
    therefore pinned at `covered` forever, however green CI is.
    """
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    project = await projects.create(
        workspace_id=WORKSPACE, parent_project_id=root.project_id, name="Durable"
    )
    return InMemoryRunStore(project_store=projects), WORKSPACE, project.project_id
