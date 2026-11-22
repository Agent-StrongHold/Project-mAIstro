"""The abandoned-Attempt sweep persists recovery dispositions on PostgreSQL (#2468).

The supported PostgreSQL Container oracle for #2468: an expired RUNNING
Attempt swept by `recover_abandoned_attempts` lands exactly one canonical
EventEnvelope row in `canonical_event_log` with the full
Workspace/Project/Run/NodeRun/Attempt correlation, and a replica reopening
the same database observes the same event_id at the same Workspace sequence.
A replica re-announcing the same logical disposition dedupes on the
deterministic event_id — no second sequence, no second row.

Skipped unless `MAISTRO_TEST_PG_DSN` names a migrated database; the
`coverage (PostgreSQL)` producer runs this leg against the migrated chain.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest

from maistro.graph import Graph, Node
from maistro.runs.model import CancellationCause, RunStatus
from maistro.runs.recovery_events import RECOVERY_EVENT_TYPE, recovery_event
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.testing.postgres import postgres_dsn
from maistro.types.config import AgentConfig

requires_postgres = pytest.mark.skipif(
    not postgres_dsn(),
    reason="set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database to run these",
)


def _require_postgres() -> str:
    """The DSN, or a skip — fatal where the caller promised a server.

    `MAISTRO_REQUIRE_PG_LEGS` is set by the `coverage (PostgreSQL)` producer,
    where a silent skip would leave the canonical-persistence leg unmeasured
    and green.
    """
    dsn = postgres_dsn()
    if dsn:
        return dsn
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
            "the recovery canonical-event leg cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_PG_DSN is not set; the PG recovery leg needs a real server")


@pytest.fixture
async def pg_pool():
    import asyncpg

    pool = await asyncpg.create_pool(_require_postgres(), min_size=1, max_size=4)
    try:
        yield pool
    finally:
        await pool.close()


async def _expired_running_attempt(container: Any, workspace: str) -> tuple[str, str, str, Any]:
    """A RUNNING Run/NodeRun holding one leased Attempt, on the Container's spine."""
    store = container.run_store
    root = await container.project_scope_store.create_root(workspace)
    graph = Graph(
        workspace_id=workspace,
        project_id=root.project_id,
        name="one step",
        nodes=[Node(node_id="step", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        run = await store.transition_run(run.run_id, status)
    node_run = await store.create_node_run(run.run_id, node_id="step")
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        node_run = await store.transition_node_run(node_run.node_run_id, status)
    attempt = await store.create_attempt(
        node_run.node_run_id, lease_holder="worker-pg-recovery", lease_ttl=timedelta(seconds=30)
    )
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    return (
        run.run_id,
        node_run.node_run_id,
        attempt.attempt_id,
        lease.expires_at + timedelta(seconds=1),
    )


async def _disposition_rows(pg_pool: Any, workspace: str) -> list[Any]:
    return await pg_pool.fetch(
        """SELECT event_id, sequence, type, workspace_id, project_id, run_id,
                  node_run_id, attempt_id, correlation_id, payload
           FROM canonical_event_log
           WHERE workspace_id = $1
           ORDER BY sequence ASC""",
        workspace,
    )


@requires_postgres
@pytest.mark.ac("ADR-082826-08f0/AC-7")
async def test_the_sweep_persists_one_canonical_disposition_that_a_replica_rediscovers(
    pg_pool,
) -> None:
    """AC oracle #2468: one envelope, persisted, reopenable, idempotent."""
    from maistro.container import create_container

    workspace = f"ws-pg-recovery-{uuid4().hex}"
    container = await create_container(AgentConfig(router_api_key="test-key"), pg_pool=pg_pool)
    try:
        run_id, node_run_id, attempt_id, after = await _expired_running_attempt(
            container, workspace
        )

        assert await container.recover_abandoned_attempts(now=after) == 1

        rows = await _disposition_rows(pg_pool, workspace)
        assert len(rows) == 1
        row = rows[0]
        assert row["type"] == RECOVERY_EVENT_TYPE
        assert row["sequence"] == 1
        assert row["workspace_id"] == workspace
        assert row["run_id"] == run_id
        assert row["node_run_id"] == node_run_id
        assert row["attempt_id"] == attempt_id
        assert row["correlation_id"] == run_id
        payload = json.loads(row["payload"])
        assert payload["disposition"] == "recovered_and_parked"
        assert payload["cancellation_cause"] == CancellationCause.RECOVERED.value

        settled = await container.run_store.get_attempt(attempt_id)
        assert settled is not None
        assert settled.status.value == "cancelled"
        parked = await container.run_store.get_node_run(node_run_id)
        assert parked is not None and parked.status is RunStatus.WAITING
        parked_run = await container.run_store.get_run(run_id)
        assert parked_run is not None and parked_run.status is RunStatus.WAITING
        event_id = row["event_id"]
        fact = recovery_event(
            attempt=settled,
            node_run=parked,
            cancellation=CancellationCause.RECOVERED,
            source="maistro.container.recover_abandoned_attempts",
        )
    finally:
        await container.aclose()

    # A replica reopens the same database: the same event_id is still there at
    # the same Workspace sequence, and re-announcing the same logical
    # disposition inserts nothing and allocates no sequence.
    replica = await create_container(AgentConfig(router_api_key="test-key"), pg_pool=pg_pool)
    try:
        store = replica.canonical_event_publisher.store
        reopened = await store.get(event_id)
        assert reopened is not None
        assert reopened.sequence == 1
        assert reopened.run_id == run_id
        assert reopened.node_run_id == node_run_id
        assert reopened.attempt_id == attempt_id

        envelope = await replica.recovery_event_sink.emit(fact)
        assert envelope.event_id == event_id
        assert envelope.sequence == 1

        assert (
            await pg_pool.fetchval(
                "SELECT count(*) FROM canonical_event_log WHERE workspace_id = $1", workspace
            )
            == 1
        )
        stream = await store.list_stream(f"workspace:{workspace}")
        assert [(event.event_id, event.sequence) for event in stream] == [(event_id, 1)]
    finally:
        await replica.aclose()
