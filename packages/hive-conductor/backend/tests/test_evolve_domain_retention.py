"""Run retention must preserve Evolve's domain state and replay fences (#1064)."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import aiosqlite
import pytest
from services.evolve_domain_store import (
    EvolveDomainPublication,
    EvolveDomainSnapshot,
    PgEvolveDomainStore,
    SqliteEvolveDomainStore,
)

from maistro.graph import Graph, Node
from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.pg_store import PgRunStore
from maistro.runs.retention_scope import WorkspaceRetentionScope
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

pytestmark = pytest.mark.contract("behavioral")


@pytest.fixture(params=["sqlite", "postgres"])
async def retention_domain(request: pytest.FixtureRequest, tmp_path: Path):
    workspace = f"evolve-retention-{uuid.uuid4().hex}"
    if request.param == "postgres":
        dsn = os.environ.get("MAISTRO_TEST_PG_DSN", "").strip()
        if not dsn:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        import asyncpg

        connection = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        projects = PgProjectScopeStore(connection)
        runs = PgRunStore(connection, project_store=projects)
        domain = PgEvolveDomainStore(connection)
    else:
        # Same SQLite file, not an isolated domain file: accidental coupling
        # of the spine purge to the domain tables must be observable here too.
        path = tmp_path / "retention.db"
        connection = await aiosqlite.connect(path)
        projects = SqliteProjectScopeStore(connection)
        await projects.ensure_schema()
        runs = SqliteRunStore(connection, project_store=projects)
        await runs.ensure_schema()
        domain = SqliteEvolveDomainStore(str(path))
    try:
        await domain.ensure_schema()
        if request.param == "postgres":
            # Migration 071 (#37): the Root fence verifies the Workspace
            # durably (`SELECT ... FOR UPDATE`) and the new
            # `canonical_projects` -> `canonical_workspaces` foreign key
            # backs it. Provision the per-test identity through the shipped
            # atomic create before minting its Root.
            from maistro.workspaces.pg_store import PgWorkspaceStore

            exists = await connection.fetchval(
                "SELECT 1 FROM canonical_workspaces WHERE workspace_id = $1", workspace
            )
            if exists is None:
                await PgWorkspaceStore(connection, project_store=projects).create(
                    creator_user_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
                    name="Evolve domain retention",
                    workspace_id=workspace,
                )
        root = await projects.create_root(workspace)
        yield SimpleNamespace(
            workspace=workspace, project_id=root.project_id, runs=runs, domain=domain
        )
    finally:
        if request.param == "postgres":
            # Only our domain records; no other test's replay keys are touched.
            await connection.execute(
                "DELETE FROM evolve_domain_publications WHERE workspace_id = $1", workspace
            )
            await connection.execute(
                "DELETE FROM evolve_domain_snapshots WHERE workspace_id = $1", workspace
            )
        await connection.close()


async def test_run_purge_preserves_domain_reconstruction_and_effect_fences(
    retention_domain: Any,
) -> None:
    world = retention_domain
    now = datetime.now(UTC)
    run = await world.runs.create_run(
        Graph(
            name="Evolve domain retention",
            workspace_id=world.workspace,
            project_id=world.project_id,
            nodes=[Node(node_id="battle", node_type="evolve.battle")],
        ),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        retention_expires_at=now - timedelta(seconds=1),
    )
    await world.runs.transition_run(run.run_id, RunStatus.QUEUED)
    await world.runs.transition_run(run.run_id, RunStatus.RUNNING)
    node = await world.runs.create_node_run(run.run_id, node_id="battle")
    attempt = await world.runs.create_attempt(node.node_run_id)
    await world.runs.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    await world.runs.transition_attempt(attempt.attempt_id, AttemptStatus.COMPLETED)
    await world.runs.transition_run(run.run_id, RunStatus.COMPLETED)

    publication = EvolveDomainPublication(
        effect_kind="battle",
        run_id=run.run_id,
        node_run_id=node.node_run_id,
        attempt_id=attempt.attempt_id,
        benchmark="proxy",
        payload={"genome_a_id": "g1", "genome_b_id": "g2", "score_a": 0.9, "score_b": 0.2},
    )
    assert await world.domain.record_battle_publication(world.workspace, publication)
    marker = {"status": "committed", "output": {"population_size": 2}}
    await world.domain.upsert_finalize_marker(
        world.workspace, "finalize-node", marker, run_id=run.run_id
    )
    snapshot = EvolveDomainSnapshot(
        workspace_id=world.workspace,
        run_id=run.run_id,
        kind="committed",
        membership_ids=["g1", "g2"],
        completed_cycles=1,
        last_battle_seq=await world.domain.battle_journal_head(world.workspace),
    )
    await world.domain.save_snapshot(snapshot)
    journal_before = await world.domain.list_battle_publications(world.workspace)

    outcome = await world.runs.purge_expired_runs(WorkspaceRetentionScope(world.workspace), now=now)
    assert outcome.runs == 1  # A no-op sweep cannot prove preservation.
    assert await world.runs.get_run(run.run_id) is None
    assert await world.runs.get_node_run(node.node_run_id) is None
    assert await world.runs.get_attempt(attempt.attempt_id) is None
    assert await world.domain.latest_snapshot(world.workspace, kind="committed") == snapshot
    assert await world.domain.list_battle_publications(world.workspace) == journal_before
    retained = await world.domain.get_finalize_marker(world.workspace, "finalize-node")
    assert retained is not None and retained.payload == marker and retained.run_id == run.run_id
    # Deleting execution identity must not permit a stale effect to republish.
    assert not await world.domain.record_battle_publication(world.workspace, publication)
    # Nor may the preserved fence suppress genuinely new logical work.
    fresh = publication.model_copy(update={"run_id": "new-run", "node_run_id": "new-node"})
    assert await world.domain.record_battle_publication(world.workspace, fresh)
