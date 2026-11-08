"""Characterize recovery interrupted after physical reclaim, before reconciliation (#1863)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from maistro.container import Container, create_container
from maistro.graph import Graph, Node
from maistro.runs.lifecycle import is_reclaimed_attempt
from maistro.runs.model import Attempt, AttemptStatus, CancellationCause, RunStatus
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.types.config import AgentConfig


class _InjectedCrash(BaseException):
    """Simulate process loss after reclaim committed but before reconciliation."""


def _config(backend: str, tmp_path: Path) -> AgentConfig:
    database_url = "memory://"
    if backend == "sqlite":
        database_url = f"sqlite:///{tmp_path / 'interrupted-reclaim.sqlite3'}"
    return AgentConfig(router_api_key="test-key", database_url=database_url)


async def _running_leased_attempt(
    container: Container, *, workspace: str
) -> tuple[str, str, Attempt]:
    root = await container.project_scope_store.create_root(workspace)
    graph = Graph(
        workspace_id=workspace,
        project_id=root.project_id,
        name="interrupted reclaim",
        nodes=[Node(node_id="step", node_type="test.interrupted_reclaim")],
    )
    run = await container.run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    await container.run_store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await container.run_store.create_node_run(run.run_id, node_id="step")
    await container.run_store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await container.run_store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await container.run_store.create_attempt(
        node_run.node_run_id,
        executor_id="worker-1",
        lease_holder="worker-1",
        lease_ttl=timedelta(seconds=30),
    )
    assert attempt.execution_lease is not None
    attempt = await container.run_store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    assert attempt.execution_lease is not None
    assert attempt.execution_lease.expires_at is not None
    return run.run_id, node_run.node_run_id, attempt


async def _interrupt_after_reclaim(
    container: Container,
    attempt: Attempt,
    monkeypatch: pytest.MonkeyPatch,
) -> Attempt:
    assert attempt.execution_lease is not None
    assert attempt.execution_lease.expires_at is not None
    expired_at = attempt.execution_lease.expires_at + timedelta(seconds=1)
    original = container.run_store.reclaim_expired_attempts
    observed: list[tuple[str, AttemptStatus]] = []

    async def crash_after_commit(**kwargs: Any) -> list[Attempt]:
        reclaimed = await original(**kwargs)
        observed.extend((item.attempt_id, item.status) for item in reclaimed)
        raise _InjectedCrash

    monkeypatch.setattr(container.run_store, "reclaim_expired_attempts", crash_after_commit)
    with pytest.raises(_InjectedCrash):
        await container.recover_abandoned_attempts(now=expired_at, limit=1)
    monkeypatch.undo()

    assert observed == [(attempt.attempt_id, AttemptStatus.CANCELLED)]
    persisted = await container.run_store.get_attempt(attempt.attempt_id)
    assert persisted is not None
    assert persisted.status is AttemptStatus.CANCELLED
    assert is_reclaimed_attempt(persisted)
    assert persisted.execution_lease == attempt.execution_lease
    assert persisted.ordinal == attempt.ordinal
    return persisted


async def _fresh_owner(
    backend: str,
    config: AgentConfig,
    prior: Container,
    retained_store: Any,
) -> Container:
    await prior.aclose()
    fresh = await create_container(config)
    if backend == "memory":
        fresh.run_store = retained_store
    return fresh


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_recovery_tick_rediscovers_reclaim_committed_before_reconcile(
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(backend, tmp_path)
    first = await create_container(config)
    fresh: Container | None = None
    try:
        run_id, node_run_id, attempt = await _running_leased_attempt(
            first, workspace=f"ws-interrupted-reclaim-{backend}"
        )
        retained_store = first.run_store
        cancelled = await _interrupt_after_reclaim(first, attempt, monkeypatch)

        before_run = await retained_store.get_run(run_id)
        before_node = await retained_store.get_node_run(node_run_id)
        assert before_run is not None and before_run.status is RunStatus.RUNNING
        assert before_node is not None and before_node.status is RunStatus.RUNNING

        fresh = await _fresh_owner(backend, config, first, retained_store)
        first = fresh
        stored_before_tick = await fresh.run_store.get_attempt(attempt.attempt_id)
        assert stored_before_tick == cancelled

        await fresh.recover_abandoned_attempts(
            now=attempt.execution_lease.expires_at + timedelta(seconds=2), limit=1
        )

        recovered_run = await fresh.run_store.get_run(run_id)
        recovered_node = await fresh.run_store.get_node_run(node_run_id)
        recovered_attempt = await fresh.run_store.get_attempt(attempt.attempt_id)

        assert recovered_run is not None and recovered_run.status is RunStatus.WAITING
        assert recovered_node is not None and recovered_node.status is RunStatus.WAITING
        assert recovered_attempt == cancelled
        assert await fresh.run_store.list_attempts(node_run_id) == [cancelled]

        snapshot = (
            recovered_run.model_dump(mode="json"),
            recovered_node.model_dump(mode="json"),
            recovered_attempt.model_dump(mode="json"),
        )
        assert await fresh.recover_abandoned_attempts(limit=1) == 0
        after_run = await fresh.run_store.get_run(run_id)
        after_node = await fresh.run_store.get_node_run(node_run_id)
        after_attempt = await fresh.run_store.get_attempt(attempt.attempt_id)
        assert after_run is not None and after_node is not None and after_attempt is not None
        assert (
            after_run.model_dump(mode="json"),
            after_node.model_dump(mode="json"),
            after_attempt.model_dump(mode="json"),
        ) == snapshot
    finally:
        await first.aclose()
        if fresh is not None and fresh is not first:
            await fresh.aclose()


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_explicit_recovered_reconcile_parks_same_reclaimed_evidence(
    backend: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(backend, tmp_path)
    first = await create_container(config)
    fresh: Container | None = None
    try:
        run_id, node_run_id, attempt = await _running_leased_attempt(
            first, workspace=f"ws-reclaim-positive-control-{backend}"
        )
        retained_store = first.run_store
        cancelled = await _interrupt_after_reclaim(first, attempt, monkeypatch)

        fresh = await _fresh_owner(backend, config, first, retained_store)
        first = fresh
        reloaded = await fresh.run_store.get_attempt(attempt.attempt_id)
        assert reloaded == cancelled

        parked = await AttemptLifecycleReconciler(fresh.run_store).reconcile(
            reloaded, cancellation=CancellationCause.RECOVERED
        )

        recovered_run = await fresh.run_store.get_run(run_id)
        persisted_attempt = await fresh.run_store.get_attempt(attempt.attempt_id)
        assert parked.node_run_id == node_run_id
        assert parked.status is RunStatus.WAITING
        assert recovered_run is not None and recovered_run.status is RunStatus.WAITING
        assert persisted_attempt == cancelled
        assert await fresh.run_store.list_attempts(node_run_id) == [cancelled]
    finally:
        await first.aclose()
        if fresh is not None and fresh is not first:
            await fresh.aclose()
