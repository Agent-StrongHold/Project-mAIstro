"""Two real workers on one real PostgreSQL: what a cancellation can prove (#1242).

The receipt contract in `maistro.runs.cancellation` claims a physical stop only
when the cancelling process can *prove* it. The proof is process-local — the
signal path to a live owner is `AttemptExecutionService._active_services`, an
in-memory index — so the interesting case is two workers that share a database
and nothing else. A test that drives both workers from one interpreter cannot
produce that case: the class-level registry would let the canceller reach the
other worker's Runtime handle, and the "remote owner" would be a local one.

So this suite starts a **second OS process** as the owning worker:

* the child claims the Run's node, runs a real bounded provider task against
  the same PostgreSQL, and signals that the provider is live;
* the parent (a different process) cancels the Run and must report
  `STOP_PENDING` — the fence is durable, the stop is *not* proven — while the
  child's Attempt stays `RUNNING` and the child's provider keeps running;
* the child then returns a **late success**. The durable Run fence must refuse
  it: the Attempt ends `CANCELLED`, never `COMPLETED`, and the Run never
  publishes a success;
* the second test SIGKILLs the owning worker instead. The durable Attempt
  stays `RUNNING` under a lease nobody renews, the receipt keeps reporting
  `STOP_PENDING` (never a stop nobody observed), and lease reclaim — the
  worker-death path of #232 — settles the Attempt terminally, after which a
  *restarted* worker's receipt can honestly say `STOP_CONFIRMED`.

Skipped unless `MAISTRO_TEST_PG_DSN` names a migrated PostgreSQL database;
the `coverage (PostgreSQL)` leg runs it against the real chain.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.runs.cancellation import CancellationDisposition
from maistro.runs.model import Attempt, AttemptStatus, RunStatus
from maistro.runs.pg_store import PgRunStore
from maistro.runs.service import RunExecutionService
from maistro.runtime import PythonExecutionRuntime
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.testing.postgres import postgres_dsn

#: The owning worker, as its own process. It writes its progress into a
#: directory the parent watches, so the handshake is a filesystem fact rather
#: than a timing assumption.
CHILD_WORKER = '''
"""A second worker process: one bounded provider task on a shared PostgreSQL."""

import asyncio
import os
import sys
import time

from maistro.persistence import _register_json_codecs
from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.runs.pg_store import PgRunStore
from maistro.runs.service import RunExecutionService
from maistro.runtime import PythonExecutionRuntime
from maistro.tasks.execution import DEFAULT_TASK_LEASE_TTL


def _write(directory, name, text):
    with open(os.path.join(directory, name), "w") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


async def main():
    import asyncpg

    dsn = os.environ["MAISTRO_TEST_PG_DSN"]
    run_id = os.environ["WORKER_RUN_ID"]
    node_id = os.environ["WORKER_NODE_ID"]
    directory = os.environ["WORKER_DIR"]

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4, init=_register_json_codecs)
    try:
        projects = PgProjectScopeStore(pool)
        store = PgRunStore(pool, project_store=projects)
        # A real worker opts its Attempts into crash recovery: the lease that
        # expires is what makes `STOP_PENDING` ("reclaim will settle it") the
        # honest answer, and what the killed-owner leg reclaims through.
        service = RunExecutionService(
            store=store, runtime=PythonExecutionRuntime(), lease_ttl=DEFAULT_TASK_LEASE_TTL
        )

        async def provider(_work, _context):
            """A bounded provider task: it waits for the parent, then answers."""
            _write(directory, "provider_started", "started")
            deadline = time.monotonic() + 120
            while not os.path.exists(os.path.join(directory, "release")):
                if time.monotonic() > deadline:
                    raise TimeoutError("the parent never released the provider")
                await asyncio.sleep(0.05)
            return "stale success"

        try:
            await service.execute_node(run_id, node_id, None, None, executor=provider)
        except asyncio.CancelledError:
            # The durable Run fence refused this worker's late success.
            _write(directory, "outcome", "refused")
            return 0
        _write(directory, "outcome", "published")
        return 1
    finally:
        await pool.close()


sys.exit(asyncio.run(main()))
'''

#: How long the parent waits for a child milestone. Generous on purpose: the
#: child pays interpreter start-up and an import of the whole runtime.
CHILD_TIMEOUT_S = 120.0


def _require_pg() -> str:
    dsn = postgres_dsn()
    if not dsn:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set; this leg needs a real PostgreSQL")
    return dsn


async def _running_attempt(store: PgRunStore, run_id: str) -> Attempt:
    """The one live physical try under the Run, as the durable row records it."""
    live: list[Attempt] = []
    for node_run in await store.list_node_runs(run_id):
        for attempt in await store.list_attempts(node_run.node_run_id):
            if attempt.status not in {AttemptStatus.COMPLETED, AttemptStatus.CANCELLED}:
                live.append(attempt)
    assert len(live) == 1, f"expected exactly one live Attempt, found {live}"
    return live[0]


async def _spawn_owner(
    tmp_path: Path, dsn: str, run_id: str, node_id: str
) -> subprocess.Popen[bytes]:
    """Start the owning worker process and wait until its provider is live."""
    directory = tmp_path / "worker"
    directory.mkdir(exist_ok=True)
    script = tmp_path / "owner_worker.py"
    script.write_text(CHILD_WORKER)
    # The worker is a plain interpreter, not pytest: it needs the same import
    # path pytest's `pythonpath` gives the suite.
    root = Path(__file__).resolve().parents[4]
    pythonpath = os.pathsep.join(
        path
        for path in (
            str(root / "packages" / "maistro-core" / "src"),
            os.environ.get("PYTHONPATH", ""),
        )
        if path
    )
    env = {
        **os.environ,
        "MAISTRO_TEST_PG_DSN": dsn,
        "WORKER_RUN_ID": run_id,
        "WORKER_NODE_ID": node_id,
        "WORKER_DIR": str(directory),
        "PYTHONPATH": pythonpath,
    }
    process = subprocess.Popen(
        [sys.executable, str(script)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    started = directory / "provider_started"
    deadline = time.monotonic() + CHILD_TIMEOUT_S
    while time.monotonic() < deadline:
        if started.exists():
            return process
        if process.poll() is not None:
            out, err = process.communicate()
            raise AssertionError(
                f"the owning worker exited before its provider started "
                f"(rc={process.returncode})\nstdout:\n{out.decode(errors='replace')}\n"
                f"stderr:\n{err.decode(errors='replace')}"
            )
        time.sleep(0.05)
    process.kill()
    raise AssertionError("the owning worker never started its provider")


def _finish(process: subprocess.Popen[bytes], timeout: float = 60.0) -> int:
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:  # pragma: no cover - a hung child fails the leg
        process.kill()
        raise


@pytest.mark.asyncio
async def test_remote_owner_cannot_publish_success_after_the_canonical_fence(
    pg_pool: Any, tmp_path: Path
) -> None:
    """Worker B cancels; worker A's late success is refused by the durable fence.

    The receipt B returns must separate the two facts: the fence is durable
    (`fenced`), the physical stop is *not* proven (`stop_confirmed=False`,
    `STOP_PENDING` with a diagnosis naming the owner that must stop it).
    """
    dsn = _require_pg()
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set; this leg needs a real PostgreSQL")

    workspace = "workspace-1242-two-workers"
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace, parent_project_id=root.project_id, name="Durable"
    )
    store = PgRunStore(pg_pool, project_store=projects)
    graph = Graph(
        graph_id="graph-1242-two-workers",
        workspace_id=workspace,
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)

    owner = await _spawn_owner(tmp_path, dsn, run.run_id, "node-1")
    try:
        attempt = await _running_attempt(store, run.run_id)
        assert attempt.execution_lease is not None
        owner_holder = attempt.execution_lease.holder

        # Worker B — a different process, with no handle on the owner's
        # Runtime — cancels the Run.
        receipt = await RunExecutionService(
            store=store, runtime=PythonExecutionRuntime()
        ).cancel_run_receipt(run.run_id)

        assert receipt.run_status is RunStatus.CANCELLED
        assert receipt.fenced is True
        assert receipt.stop_confirmed is False
        assert receipt.disposition is CancellationDisposition.STOP_PENDING
        [row] = receipt.attempts
        assert row.attempt_id == attempt.attempt_id
        assert row.owner == owner_holder
        # The diagnosis names the worker that still has to stop the try: an
        # explicit "somebody else owns this" answer, not a hopeful one.
        assert owner_holder in receipt.diagnosis
        assert owner_holder in row.diagnosis

        # The canceller did not touch the owner's durable row: it may not
        # fabricate the stop it is reporting on.
        persisted = await store.get_attempt(attempt.attempt_id)
        assert persisted is not None
        assert persisted.status is AttemptStatus.RUNNING
        assert owner.poll() is None, "the owning worker must still be running"

        # The owner now answers with a late success. The durable fence refuses
        # it: the Attempt must end CANCELLED, never COMPLETED.
        (tmp_path / "worker" / "release").write_text("go")
        assert _finish(owner) == 0
        outcome = (tmp_path / "worker" / "outcome").read_text()
        assert outcome == "refused", "the remote owner published a success after the fence"

        settled = await store.get_attempt(attempt.attempt_id)
        assert settled is not None
        assert settled.status is AttemptStatus.CANCELLED
        final_run = await store.get_run(run.run_id)
        assert final_run is not None
        assert final_run.status is RunStatus.CANCELLED
    finally:
        if owner.poll() is None:  # pragma: no cover - cleanup on an early failure
            owner.kill()
            owner.wait(timeout=30)

    # A restarted worker now sees a durably terminal try and may say so.
    restarted = await RunExecutionService(
        store=store, runtime=PythonExecutionRuntime()
    ).cancel_run_receipt(run.run_id)
    assert restarted.stop_confirmed is True
    assert restarted.disposition is CancellationDisposition.STOP_CONFIRMED


@pytest.mark.asyncio
async def test_a_killed_owner_leaves_the_receipt_pending_until_reclaim_settles_it(
    pg_pool: Any, tmp_path: Path
) -> None:
    """A dead owner is not a stopped one; reclaim settles it, and only then.

    The process kill is the worker-death case of #232: the Attempt stays
    `RUNNING` under a lease nobody renews, so the honest receipt is still
    `STOP_PENDING`. Lease expiry then settles the try terminally, and only
    after that does a receipt claim a confirmed stop.
    """
    dsn = _require_pg()
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set; this leg needs a real PostgreSQL")

    workspace = "workspace-1242-killed-owner"
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace, parent_project_id=root.project_id, name="Durable"
    )
    store = PgRunStore(pg_pool, project_store=projects)
    graph = Graph(
        graph_id="graph-1242-killed-owner",
        workspace_id=workspace,
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)

    owner = await _spawn_owner(tmp_path, dsn, run.run_id, "node-1")
    attempt = await _running_attempt(store, run.run_id)
    assert attempt.execution_lease is not None
    assert attempt.execution_lease.expires_at is not None

    # SIGKILL: no cleanup, no final answer — the worker simply stops existing.
    owner.send_signal(signal.SIGKILL)
    assert _finish(owner) != 0

    receipt = await RunExecutionService(
        store=store, runtime=PythonExecutionRuntime()
    ).cancel_run_receipt(run.run_id)
    assert receipt.fenced is True
    assert receipt.stop_confirmed is False
    assert receipt.disposition is CancellationDisposition.STOP_PENDING

    # The dead owner's try is still durably RUNNING: nothing proved it stopped.
    still_running = await store.get_attempt(attempt.attempt_id)
    assert still_running is not None
    assert still_running.status is AttemptStatus.RUNNING

    # Lease expiry is the recovery path (#232): it settles the abandoned try.
    reclaimed = await store.reclaim_expired_attempts(
        now=attempt.execution_lease.expires_at + timedelta(seconds=1)
    )
    assert [row.attempt_id for row in reclaimed] == [attempt.attempt_id]
    settled = await store.get_attempt(attempt.attempt_id)
    assert settled is not None
    assert settled.status is AttemptStatus.CANCELLED

    # Now, and only now, a receipt may claim a confirmed stop.
    after = await RunExecutionService(
        store=store, runtime=PythonExecutionRuntime()
    ).cancel_run_receipt(run.run_id)
    assert after.stop_confirmed is True
    assert after.disposition is CancellationDisposition.STOP_CONFIRMED


@pytest.mark.asyncio
async def test_the_fence_is_durable_for_a_worker_that_restarts_afterwards(
    pg_pool: Any, tmp_path: Path
) -> None:
    """A restarted worker sees the fence, not a fresh Run it may complete.

    The restart is a new store object over the same database — what a worker
    that crashed and came back holds. It must not find an uncancelled Run.
    """
    dsn = _require_pg()
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set; this leg needs a real PostgreSQL")

    workspace = "workspace-1242-restart"
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace, parent_project_id=root.project_id, name="Durable"
    )
    store = PgRunStore(pg_pool, project_store=projects)
    graph = Graph(
        graph_id="graph-1242-restart",
        workspace_id=workspace,
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)

    owner = await _spawn_owner(tmp_path, dsn, run.run_id, "node-1")
    try:
        receipt = await RunExecutionService(
            store=store, runtime=PythonExecutionRuntime()
        ).cancel_run_receipt(run.run_id)
        assert receipt.fenced is True
        assert receipt.disposition is CancellationDisposition.STOP_PENDING
    finally:
        if owner.poll() is None:
            owner.send_signal(signal.SIGKILL)
            _finish(owner)

    # A restarted worker: a fresh store object over the same database.
    restarted_store = PgRunStore(pg_pool, project_store=PgProjectScopeStore(pg_pool))
    restarted_run = await restarted_store.get_run(run.run_id)
    assert restarted_run is not None
    assert restarted_run.status is RunStatus.CANCELLED
    assert datetime.now(UTC) >= restarted_run.finished_at - timedelta(minutes=1)
