"""Root-run preparation finishes all scope-store I/O before admission (#1882).

``PgRunStore.prepare_root_run`` is the task-agnostic, parentless half of the
admission seam (#1845): graph/scope validation, actor requirement, graph copy
and initial state all complete — and the Project store's connection is
released — before the caller acquires the admission transaction connection.
These tests pin the public contract directly against a real server:

* the prepared candidate carries exactly the validated semantics the
  canonical row later shows (scope, actor, provenance, retention, state);
* wrong scope, a missing/blank actor and a malformed-scope graph refuse
  before any canonical row exists;
* on a pool of ``max_size=1`` whose single connection is the Project store's
  only route, preparation completes, leaves the pool with no connection still
  acquired and no canonical row, and the later transaction acquisition
  succeeds — the ordering the whole seam exists to guarantee;
* preparation moved *inside* a held connection cannot complete — a nested
  pool acquisition on a max_size=1 pool never returns, so a deterministic
  timeout is a deadlock guard, not a performance assertion.

PostgreSQL legs are live-server proof: with ``pg_pool`` absent they skip, and
``MAISTRO_REQUIRE_PG_LEGS`` turns that skip into a failure, because a skipped
PG case is not durability proof. A fake-asyncpg statement assertion would not
be one either, so every leg here drives the production stores on a genuinely
migrated database with the production JSON codecs.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from maistro.graph import Graph, Node
from maistro.runs.model import GraphSnapshot, RunStatus
from maistro.runs.pg_store import PgRunStore
from maistro.runs.store import RunIntegrityError, RunNotFound
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.testing.postgres import postgres_dsn

#: How long the nested-acquisition probe waits before declaring deadlock. The
#: guard exists because the failure mode it detects is an infinite wait (the
#: pool's last connection is held by the caller's own transaction), so the
#: wait must be long enough to rule out scheduler noise but is in no way a
#: latency bound: a completion at any time before it would fail the test.
DEADLOCK_GUARD_SECONDS = 2.0


def _live_pool(pg_pool: Any) -> Any:
    """Require the real server: skip without a DSN, fail when legs are due.

    The suite directory has both a no-services consumer (coverage producer)
    and a with-services one (CI's postgres job, quality.yml's suites). A skip
    is honest in the first and a lie in the second, so the operator's
    ``MAISTRO_REQUIRE_PG_LEGS=1`` — the repo's existing contract for exactly
    this — converts "no server" into a red test instead of a green skip.
    """
    if pg_pool is None:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            pytest.fail(
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
                "the PostgreSQL leg cannot be proven without a server"
            )
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    return pg_pool


def _graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Root preparation",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


async def _fresh_scope(pool: Any, label: str) -> tuple[Any, str, str]:
    """One fresh Workspace with a non-root Project, isolated per test."""
    from maistro.projects.pg_scope_store import PgProjectScopeStore

    projects = PgProjectScopeStore(pool)
    workspace = f"issue-1882-{label}-{uuid4().hex}"
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace, parent_project_id=root.project_id, name="Preparation"
    )
    return projects, workspace, project.project_id


async def _canonical_rows(pool: Any, workspace: str) -> int:
    conn: Any
    async with pool.acquire() as conn:
        return int(
            await conn.fetchval(
                "SELECT count(*) FROM canonical_runs WHERE workspace_id = $1", workspace
            )
        )


@pytest.fixture
async def pg_pool_1() -> Any:
    """A dedicated pool of exactly one connection, production codecs.

    The exhaustion and nested-acquisition proofs need a pool whose last
    connection is visibly held; the shared ``pg_pool`` fixture is
    ``max_size=8`` and could hide a leaked acquisition behind its seven
    spares. The DSN is the same migrated database; the codecs are the ones
    the production pool registers, so the connections under test are the
    connections that ship.
    """
    dsn = postgres_dsn()
    if not dsn:
        yield None
        return
    asyncpg = pytest.importorskip("asyncpg")

    from maistro.persistence import _register_json_codecs

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1, init=_register_json_codecs)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_prepared_root_carries_the_validated_semantics_create_run_inserts(
    pg_pool: Any,
) -> None:
    """The public root call answers with the same validated Run the canonical
    row later shows: scope from the graph, the actor required, provenance and
    graph copied (not aliased), and the initial state already applied."""
    _live_pool(pg_pool)
    projects, workspace, project_id = await _fresh_scope(pg_pool, "semantics")
    store = PgRunStore(pg_pool, project_store=projects)
    graph = _graph(workspace, project_id)
    original_snapshot = GraphSnapshot.from_graph(graph)
    retention = datetime.now(UTC) + timedelta(days=1)
    provenance = {"task_id": "task-1", "source": "task_queue"}

    prepared = await store.prepare_root_run(
        graph,
        persona_id="persona-1",
        actor_principal_id=f"  {DEFAULT_TEST_ACTOR_PRINCIPAL_ID}  ",
        provenance=provenance,
        retention_expires_at=retention,
        initial_status=RunStatus.QUEUED,
    )

    # Every validated field, exactly as the insert path will write it.
    assert prepared.workspace_id == workspace
    assert prepared.project_id == project_id
    assert prepared.parent_run_id is None
    assert prepared.parent_node_run_id is None
    assert prepared.persona_id == "persona-1"
    # The shared actor guard ran: required, and stripped.
    assert prepared.actor_principal_id == DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    assert prepared.provenance == {"task_id": "task-1", "source": "task_queue"}
    assert prepared.retention_expires_at == retention
    # `admit_in_state` applied before anything was written: the candidate is
    # born QUEUED, not inserted CREATED and transitioned after.
    assert prepared.status is RunStatus.QUEUED
    assert prepared.graph == original_snapshot

    # And the canonical row agrees with the prepared candidate field for field
    # — the same graph object, so the snapshots must be identical, not just
    # similar.
    inserted = await store.create_run(
        graph,
        persona_id="persona-1",
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        provenance={"task_id": "task-1", "source": "task_queue"},
        retention_expires_at=retention,
        initial_status=RunStatus.QUEUED,
    )
    stored = await store.get_run(inserted.run_id)
    assert stored is not None
    assert stored.workspace_id == prepared.workspace_id
    assert stored.project_id == prepared.project_id
    assert stored.parent_run_id is None
    assert stored.graph == prepared.graph
    assert stored.persona_id == prepared.persona_id
    assert stored.actor_principal_id == prepared.actor_principal_id
    assert stored.provenance == prepared.provenance
    assert stored.retention_expires_at == prepared.retention_expires_at
    assert stored.status is prepared.status

    # Copies, not aliases: later mutation of the inputs cannot rewrite the
    # candidate — or, by the same mechanism, any row already inserted from it.
    graph.nodes.append(Node(node_id="node-2", node_type="agent"))
    provenance["task_id"] = "mutated"
    assert prepared.graph == original_snapshot
    assert prepared.provenance["task_id"] == "task-1"
    assert stored.graph == original_snapshot


@pytest.mark.asyncio
async def test_preparation_refuses_a_wrong_scope_before_any_insert(pg_pool: Any) -> None:
    """A graph naming another Workspace's Project never reaches an INSERT."""
    _live_pool(pg_pool)
    projects, workspace, _unused = await _fresh_scope(pg_pool, "scope")
    store = PgRunStore(pg_pool, project_store=projects)
    _projects, other_workspace, other_project_id = await _fresh_scope(pg_pool, "scope-other")

    with pytest.raises(RunIntegrityError, match="does not belong to the Graph Workspace"):
        await store.prepare_root_run(
            _graph(workspace, other_project_id),
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
    with pytest.raises(RunIntegrityError, match="does not exist in canonical Project scope"):
        await store.prepare_root_run(
            _graph(workspace, f"missing-{uuid4().hex}"),
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
    assert await _canonical_rows(pg_pool, workspace) == 0
    assert await _canonical_rows(pg_pool, other_workspace) == 0


@pytest.mark.asyncio
async def test_preparation_refuses_an_unadmitted_actor_before_any_insert(
    pg_pool: Any,
) -> None:
    """`require_admitted_actor` still guards the root seam: blank or missing
    actors refuse with nothing written."""
    _live_pool(pg_pool)
    projects, workspace, project_id = await _fresh_scope(pg_pool, "actor")
    store = PgRunStore(pg_pool, project_store=projects)
    graph = _graph(workspace, project_id)

    for blank in (None, "", "   "):
        with pytest.raises(ValueError, match="actor_principal_id is required"):
            await store.prepare_root_run(graph, actor_principal_id=blank)
    assert await _canonical_rows(pg_pool, workspace) == 0


@pytest.mark.asyncio
async def test_preparation_refuses_an_unadmissible_initial_state(pg_pool: Any) -> None:
    """`admit_in_state` decides the created state before any write: a caller
    claiming a terminal Run is refused, not silently corrected."""
    _live_pool(pg_pool)
    projects, workspace, project_id = await _fresh_scope(pg_pool, "state")
    store = PgRunStore(pg_pool, project_store=projects)

    with pytest.raises(RunIntegrityError, match="cannot be created in state"):
        await store.prepare_root_run(
            _graph(workspace, project_id),
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
            initial_status=RunStatus.RUNNING,
        )
    assert await _canonical_rows(pg_pool, workspace) == 0


@pytest.mark.asyncio
async def test_preparation_leaves_no_row_and_the_transaction_still_acquires(
    pg_pool: Any, pg_pool_1: Any
) -> None:
    """The seam contract, on the pool shape that punishes violations.

    With ``max_size=1`` and the Project store reading through that same pool,
    preparation can only complete by acquiring the connection, doing the
    scope read, and releasing it. Anything held across the call's end would
    make the transaction acquisition below hang forever."""
    pool = _live_pool(pg_pool_1)
    projects, workspace, project_id = await _fresh_scope(pool, "one-connection")
    store = PgRunStore(pool, project_store=projects)
    graph = _graph(workspace, project_id)

    prepared = await store.prepare_root_run(
        graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )

    # Nothing acquired remains and nothing was written: the single connection
    # is back, and the candidate exists only in the caller's hands.
    assert pool.get_idle_size() == pool.get_max_size() == 1
    assert await _canonical_rows(pool, workspace) == 0

    # The admission transaction the preparation preceded acquires the very
    # connection preparation used, inserts through the seam's write half, and
    # commits the canonical row.
    conn: Any
    async with pool.acquire() as conn, conn.transaction(isolation="read_committed"):
        await store.insert_prepared_run(conn, prepared)
    stored = await store.get_run(prepared.run_id)
    assert stored is not None
    assert stored.status is RunStatus.CREATED
    assert await _canonical_rows(pool, workspace) == 1


@pytest.mark.asyncio
async def test_preparation_moved_inside_a_held_connection_is_detected_by_timeout(
    pg_pool: Any, pg_pool_1: Any
) -> None:
    """The deliberate mis-ordering, integrated: preparation invoked while the
    caller already holds the pool's only connection (as an in-transaction
    caller would) cannot complete — the Project store's read waits for that
    same connection. The timeout exists to detect exactly this; the test then
    proves the block was the pool, not slowness, by letting preparation
    succeed the moment the connection is released."""
    pool = _live_pool(pg_pool_1)
    projects, workspace, project_id = await _fresh_scope(pool, "nested")
    store = PgRunStore(pool, project_store=projects)
    graph = _graph(workspace, project_id)

    conn: Any
    async with pool.acquire() as conn, conn.transaction(isolation="read_committed"):
        # Deterministic barrier, not a sleep: the held connection is the only
        # one, and a nested acquisition has nowhere else to go.
        assert pool.get_idle_size() == 0
        probe = asyncio.create_task(
            store.prepare_root_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
        )
        try:
            done, _pending = await asyncio.wait({probe}, timeout=DEADLOCK_GUARD_SECONDS)
            assert probe not in done, (
                "preparation completed inside a held connection: the scope read "
                "cannot have run, or it ran on a connection the caller already owned"
            )
        finally:
            probe.cancel()
            with pytest.raises(asyncio.CancelledError):
                await probe

    # The guard's explanation, proven: with the connection released the same
    # call completes immediately, and neither attempt wrote anything.
    prepared = await store.prepare_root_run(
        graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    assert await _canonical_rows(pool, workspace) == 0
    assert prepared.parent_run_id is None


@pytest.mark.asyncio
async def test_child_preparation_keeps_its_own_validation(pg_pool: Any) -> None:
    """The root seam takes nothing away from the child path: the shared parent
    checks still run, unchanged, on the mixed branch of `create_run`."""
    _live_pool(pg_pool)
    projects, workspace, project_id = await _fresh_scope(pg_pool, "child")
    store = PgRunStore(pg_pool, project_store=projects)
    parent = await store.create_run(
        _graph(workspace, project_id), actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )

    # A parentless call that still names a node is refused where it always was.
    with pytest.raises(RunIntegrityError, match="parent_node_run_id requires parent_run_id"):
        await store.prepare_run(
            _graph(workspace, project_id),
            parent_node_run_id="node-run-orphan",
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
    # Cross-Workspace children are still refused by the shared scope check.
    _other_store_pool, other_workspace, other_project_id = await _fresh_scope(
        pg_pool, "child-other"
    )
    with pytest.raises(RunIntegrityError, match="Workspace"):
        await store.prepare_run(
            _graph(other_workspace, other_project_id),
            parent_run_id=parent.run_id,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
    # A missing parent is still a missing parent.
    with pytest.raises(RunNotFound):
        await store.prepare_run(
            _graph(workspace, project_id),
            parent_run_id=f"run-{uuid4().hex}",
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )

    # And a legitimate child still prepares with its parent bound.
    child_graph = _graph(workspace, project_id)
    child = await store.prepare_run(
        child_graph,
        parent_run_id=parent.run_id,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert child.parent_run_id == parent.run_id
    assert child.graph == GraphSnapshot.from_graph(child_graph)
