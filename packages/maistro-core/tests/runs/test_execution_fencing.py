from __future__ import annotations

import contextlib
from typing import Any

import aiosqlite
import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import (
    AttemptExecutionService,
    AttemptStatus,
    InMemoryRunStore,
    RunStatus,
    SqliteRunStore,
    StaleExecutionFence,
)
from maistro.runtime import PythonExecutionRuntime


async def _scope() -> tuple[InMemoryProjectScopeStore, Graph]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-1")
    project = await projects.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Fencing",
    )
    return projects, Graph(
        workspace_id="ws-1",
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


@pytest.mark.asyncio
async def test_raw_attempt_fixture_remains_unfenced() -> None:
    projects, graph = await _scope()
    store = InMemoryRunStore(project_store=projects)
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(node_run.node_run_id)

    assert attempt.execution_lease is None
    running = await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    assert running.status is AttemptStatus.RUNNING


@pytest.mark.asyncio
async def test_leased_attempt_rejects_missing_and_wrong_fence() -> None:
    projects, graph = await _scope()
    store = InMemoryRunStore(project_store=projects)
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder="worker-a")

    assert attempt.execution_lease is not None
    with pytest.raises(StaleExecutionFence):
        await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    with pytest.raises(StaleExecutionFence):
        await store.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.RUNNING,
            fencing_token="wrong",
        )

    running = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    assert running.status is AttemptStatus.RUNNING


@pytest.mark.asyncio
async def test_retry_uses_new_epoch_and_old_fence_cannot_update_new_attempt() -> None:
    projects, graph = await _scope()
    store = InMemoryRunStore(project_store=projects)
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")

    first = await store.create_attempt(node_run.node_run_id, lease_holder="worker-a")
    assert first.execution_lease is not None
    first = await store.transition_attempt(
        first.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=first.execution_lease.fencing_token,
    )
    first = await store.transition_attempt(
        first.attempt_id,
        AttemptStatus.FAILED,
        error="lost worker",
        fencing_token=first.execution_lease.fencing_token,
    )
    assert first.status is AttemptStatus.FAILED

    second = await store.create_attempt(node_run.node_run_id, lease_holder="worker-b")
    assert second.execution_lease is not None
    assert second.execution_lease.lease_epoch == first.execution_lease.lease_epoch + 1
    assert second.execution_lease.fencing_token != first.execution_lease.fencing_token

    with pytest.raises(StaleExecutionFence):
        await store.transition_attempt(
            second.attempt_id,
            AttemptStatus.RUNNING,
            fencing_token=first.execution_lease.fencing_token,
        )


@pytest.mark.asyncio
async def test_attempt_execution_service_uses_fence_transparently() -> None:
    projects, graph = await _scope()
    store = InMemoryRunStore(project_store=projects)
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def executor(work_item: Any, _context: Any) -> Any:
        return work_item

    terminal = await service.execute(
        node_run.node_run_id,
        "ok",
        None,
        executor=executor,
        executor_id="agent-worker",
    )

    assert terminal.status is AttemptStatus.COMPLETED
    assert terminal.execution_lease is not None
    assert terminal.execution_lease.holder == "agent-worker"
    logical = await store.get_node_run(node_run.node_run_id)
    assert logical is not None and logical.status is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_sqlite_enforces_same_fence_contract() -> None:
    projects, graph = await _scope()
    async with aiosqlite.connect(":memory:") as conn:
        store = SqliteRunStore(conn, project_store=projects)
        await store.ensure_schema()
        run = await store.create_run(graph)
        node_run = await store.create_node_run(run.run_id, node_id="node-1")
        attempt = await store.create_attempt(node_run.node_run_id, lease_holder="worker-a")
        assert attempt.execution_lease is not None

        with pytest.raises(StaleExecutionFence):
            await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)

        running = await store.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.RUNNING,
            fencing_token=attempt.execution_lease.fencing_token,
        )
        assert running.status is AttemptStatus.RUNNING


# ── crash recovery through the production seam (#232) ──────────────────
#
# The spine-conformance suite proves the lease primitive. These prove the
# *executor* uses it, which is what #232's acceptance is actually about: "a
# task worker is simulated dying after its Attempt is durably RUNNING; after
# recovery, no persisted Attempt incorrectly remains RUNNING."


async def _running_node_run(store: Any, graph: Any) -> Any:
    from maistro.runs.model import RunStatus

    run = await store.create_run(graph)
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        await store.transition_run(run.run_id, status)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    for status in (RunStatus.QUEUED, RunStatus.RUNNING):
        await store.transition_node_run(node_run.node_run_id, status)
    return node_run


@pytest.mark.asyncio
@pytest.mark.ac("ADR-082526-b36a/AC-7")
async def test_a_worker_that_dies_mid_attempt_is_reclaimed() -> None:
    """#232's headline acceptance, driven through `AttemptExecutionService`.

    Death is simulated as *the worker stops being able to renew* while its
    Attempt stays durably RUNNING. That is the real shape: a process that is
    SIGKILLed, partitioned from the database, or wedged runs no cleanup — its
    renewals simply stop.

    Cancelling the executor task would NOT be this test. `execute` catches
    `CancelledError` and terminalizes the Attempt as CANCELLED (#230), which is
    an orderly in-process stop and leaves nothing to reclaim. The failure mode
    #232 is about is precisely the one where no handler runs at all.
    """
    import asyncio
    from datetime import timedelta

    from maistro.runs.execution import AttemptExecutionService
    from maistro.runs.model import AttemptStatus

    projects, graph = await _scope()
    store = InMemoryRunStore(project_store=projects)
    node_run = await _running_node_run(store, graph)
    service = AttemptExecutionService(
        store=store,
        runtime=PythonExecutionRuntime(),
        lease_ttl=timedelta(seconds=0.06),
    )

    started = asyncio.Event()

    async def _never_finishes(*_args: Any, **_kwargs: Any) -> Any:
        started.set()
        await asyncio.sleep(3600)

    worker = asyncio.create_task(
        service.execute(
            node_run.node_run_id,
            {},
            {},
            executor=_never_finishes,
            executor_id="task-worker-1",
        )
    )
    await started.wait()

    attempts = await store.list_attempts(node_run.node_run_id)
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt.status is AttemptStatus.RUNNING
    assert attempt.execution_lease is not None
    assert attempt.execution_lease.expires_at is not None, (
        "the executor must opt its Attempt into a TTL, or nothing is reclaimable"
    )

    # The worker loses the ability to renew. Its Attempt stays RUNNING on disk.
    async def _dead(*_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionError("worker is gone")

    store.renew_lease = _dead  # type: ignore[method-assign]
    await asyncio.sleep(0.15)  # past the TTL, with no successful renewal

    still = await store.get_attempt(attempt.attempt_id)
    assert still is not None and still.status is AttemptStatus.RUNNING, (
        "the durable record must still claim the work is executing — that is the bug"
    )

    reclaimed = await store.reclaim_expired_attempts()

    assert [item.attempt_id for item in reclaimed] == [attempt.attempt_id]
    settled = await store.get_attempt(attempt.attempt_id)
    assert settled is not None
    assert settled.status is not AttemptStatus.RUNNING, (
        "no persisted Attempt may incorrectly remain RUNNING after recovery"
    )
    assert "task-worker-1" in (settled.error or ""), (
        "the record must name the holder that went quiet, so a reclaimed Attempt is "
        "distinguishable from one a user cancelled (ADR-082426-f170)"
    )

    worker.cancel()
    with contextlib.suppress(BaseException):
        await worker  # the abandoned worker's unwinding is not under test


@pytest.mark.ac("ADR-082526-b36a/AC-8")
async def test_a_live_worker_keeps_its_attempt() -> None:
    """The other half of #232's acceptance, and the one a naive TTL fails.

    A worker slower than its own TTL must survive, because the heartbeat is
    still renewing. Without this the mechanism trades a stuck Attempt for a
    reaped healthy one, which is worse.
    """
    import asyncio
    from datetime import timedelta

    from maistro.runs.execution import AttemptExecutionService
    from maistro.runs.model import AttemptStatus

    projects, graph = await _scope()
    store = InMemoryRunStore(project_store=projects)
    node_run = await _running_node_run(store, graph)
    ttl = timedelta(seconds=0.09)
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime(), lease_ttl=ttl)

    async def _slower_than_its_ttl(*_args: Any, **_kwargs: Any) -> str:
        await asyncio.sleep(0.2)  # > 2x the TTL, so it only survives by renewing
        return "done"

    attempt = await service.execute(node_run.node_run_id, {}, {}, executor=_slower_than_its_ttl)

    assert attempt.status is AttemptStatus.COMPLETED, (
        "a live worker outran its TTL and must not have been reaped"
    )
    persisted = await store.list_attempts(node_run.node_run_id)
    assert len(persisted) == 1
    assert persisted[0].execution_lease is not None
    assert persisted[0].execution_lease.expires_at > attempt.created_at, (
        "the heartbeat must have pushed the expiry past where it started"
    )


@pytest.mark.asyncio
@pytest.mark.ac("ADR-082526-b36a/AC-5")
async def test_an_executor_without_a_ttl_creates_no_expiry() -> None:
    """The default, and what keeps this additive: no TTL, no heartbeat, no
    reclamation, and exactly today's behaviour."""
    from datetime import timedelta

    from maistro.runs.execution import AttemptExecutionService

    projects, graph = await _scope()
    store = InMemoryRunStore(project_store=projects)
    node_run = await _running_node_run(store, graph)
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def _work(*_args: Any, **_kwargs: Any) -> str:
        return "done"

    attempt = await service.execute(node_run.node_run_id, {}, {}, executor=_work)

    assert attempt.execution_lease is not None
    assert attempt.execution_lease.expires_at is None
    assert await store.reclaim_expired_attempts() == []
    assert timedelta(0) == timedelta(0)


@pytest.mark.asyncio
async def test_a_non_positive_lease_ttl_is_refused_at_construction() -> None:
    """Rejected where it is configured rather than at the first Attempt, so a
    misconfigured executor fails before it has created durable state."""
    from datetime import timedelta

    from maistro.runs.execution import AttemptExecutionService

    projects, _graph = await _scope()
    store = InMemoryRunStore(project_store=projects)

    with pytest.raises(ValueError, match="lease_ttl must be positive"):
        AttemptExecutionService(
            store=store, runtime=PythonExecutionRuntime(), lease_ttl=timedelta(0)
        )
