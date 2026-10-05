"""A persisted pre-launch Attempt remains owned when logical preparation fails."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.runs import AttemptStatus, RunExecutionService, RunIntegrityError, RunStatus
from maistro.runtime import PythonExecutionRuntime
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


async def _service(spine: Any) -> tuple[Any, RunExecutionService, str]:
    store, workspace, project = spine
    service = RunExecutionService(
        store=store, runtime=PythonExecutionRuntime(), lease_ttl=timedelta(seconds=30)
    )
    run = await service.create_run(
        Graph(
            workspace_id=workspace,
            project_id=project,
            name="Preparation ownership",
            nodes=[Node(node_id="node", node_type="capability")],
        ),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        initial_status=RunStatus.QUEUED,
    )
    return store, service, run.run_id


async def _must_not_execute(_work: Any, _context: Any) -> None:
    pytest.fail("physical work must not start after failed preparation")


async def _attempt(store: Any, run_id: str) -> Any:
    nodes = await store.list_node_runs(run_id)
    assert len(nodes) == 1
    attempts = await store.list_attempts(nodes[0].node_run_id)
    assert len(attempts) == 1
    return attempts[0]


@pytest.mark.asyncio
async def test_run_cancel_after_attempt_persist_before_preparation_settles_attempt(
    spine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, service, run_id = await _service(spine)
    admitted = asyncio.Event()
    release = asyncio.Event()
    original = store.create_attempt
    created = []

    async def gated_create(*args: Any, **kwargs: Any) -> Any:
        attempt = await original(*args, **kwargs)
        created.append(attempt)
        admitted.set()
        await release.wait()
        return attempt

    monkeypatch.setattr(store, "create_attempt", gated_create)
    task = asyncio.create_task(
        service.execute_node(run_id, "node", None, None, executor=_must_not_execute)
    )
    await admitted.wait()
    await service.cancel_run(run_id)
    release.set()
    with pytest.raises(RunIntegrityError, match="terminal Run"):
        await task

    terminal = await _attempt(store, run_id)
    assert terminal.status is AttemptStatus.CANCELLED
    assert terminal.execution_lease == created[0].execution_lease
    assert terminal.execution_lease is not None
    assert terminal.execution_lease.expires_at is not None
    assert (await store.get_run(run_id)).status is RunStatus.CANCELLED
    assert (await store.list_node_runs(run_id))[0].status is RunStatus.CANCELLED
    assert terminal.attempt_id not in service._attempts._active_services


@pytest.mark.asyncio
async def test_nonterminal_preparation_failure_retains_recoverable_attempt(
    spine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, service, run_id = await _service(spine)
    failure = RuntimeError("logical preparation unavailable")

    async def fail_preparation(_node_id: str) -> None:
        raise failure

    monkeypatch.setattr(service._attempts._lifecycle, "prepare_execution", fail_preparation)
    with pytest.raises(RuntimeError) as raised:
        await service.execute_node(run_id, "node", None, None, executor=_must_not_execute)
    assert raised.value is failure
    terminal = await _attempt(store, run_id)
    assert terminal.status is AttemptStatus.CREATED
    assert terminal.execution_lease is not None
    assert terminal.execution_lease.expires_at is not None
    # Preparation never established RUNNING logical state. The domain still
    # owns its disposition; physical cleanup must not invent logical progress.
    assert (await store.get_run(run_id)).status is RunStatus.QUEUED
    assert (await store.list_node_runs(run_id))[0].status is RunStatus.CREATED
    reclaimed = await store.reclaim_expired_attempts(
        now=terminal.execution_lease.expires_at + timedelta(seconds=1)
    )
    assert [attempt.attempt_id for attempt in reclaimed] == [terminal.attempt_id]
    assert reclaimed[0].status is AttemptStatus.CANCELLED


@pytest.mark.asyncio
async def test_unfenced_preparation_cancellation_retains_recoverable_attempt(
    spine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, service, run_id = await _service(spine)
    preparing = asyncio.Event()

    async def block_preparation(_node_id: str) -> None:
        preparing.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(service._attempts._lifecycle, "prepare_execution", block_preparation)
    task = asyncio.create_task(
        service.execute_node(run_id, "node", None, None, executor=_must_not_execute)
    )
    await preparing.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    attempt = await _attempt(store, run_id)
    assert attempt.status is AttemptStatus.CREATED
    assert attempt.execution_lease is not None
    assert attempt.execution_lease.expires_at is not None


@pytest.mark.asyncio
async def test_preparation_cleanup_preserves_existing_physical_winner(
    spine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, service, run_id = await _service(spine)
    failure = RuntimeError("preparation stopped after cancellation winner")

    async def already_cancelled(node_id: str) -> None:
        attempt = (await store.list_attempts(node_id))[0]
        await store.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.CANCELLED,
            fencing_token=attempt.execution_lease.fencing_token,
            error="original canonical winner",
        )
        await service.cancel_run(run_id)
        raise failure

    monkeypatch.setattr(service._attempts._lifecycle, "prepare_execution", already_cancelled)
    with pytest.raises(RuntimeError) as raised:
        await service.execute_node(run_id, "node", None, None, executor=_must_not_execute)
    assert raised.value is failure
    terminal = await _attempt(store, run_id)
    assert terminal.status is AttemptStatus.CANCELLED
    assert terminal.error == "original canonical winner"


@pytest.mark.asyncio
@pytest.mark.parametrize("lookup", ["get_node_run", "get_run"])
async def test_unreadable_preparation_fence_preserves_failure_and_lease(
    spine: Any, monkeypatch: pytest.MonkeyPatch, lookup: str
) -> None:
    store, service, run_id = await _service(spine)
    failure = RuntimeError("original preparation failure")

    async def fail_preparation(_node_id: str) -> None:
        async def unreadable(_identity: str) -> None:
            raise RuntimeError("fence read unavailable")

        monkeypatch.setattr(store, lookup, unreadable)
        raise failure

    monkeypatch.setattr(service._attempts._lifecycle, "prepare_execution", fail_preparation)
    with pytest.raises(RuntimeError) as raised:
        await service.execute_node(run_id, "node", None, None, executor=_must_not_execute)
    assert raised.value is failure
    monkeypatch.undo()
    attempt = await _attempt(store, run_id)
    assert attempt.status is AttemptStatus.CREATED
    assert attempt.execution_lease is not None
    assert attempt.execution_lease.expires_at is not None


@pytest.mark.asyncio
async def test_fence_cleanup_write_failure_remains_visible_and_recoverable(
    spine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, service, run_id = await _service(spine)
    cleanup_failure = RuntimeError("terminal persistence unavailable")

    async def fail_preparation(_node_id: str) -> None:
        await service.cancel_run(run_id)
        raise RunIntegrityError("terminal Run won before preparation")

    async def fail_terminal_write(*_args: Any, **_kwargs: Any) -> None:
        raise cleanup_failure

    monkeypatch.setattr(service._attempts._lifecycle, "prepare_execution", fail_preparation)
    monkeypatch.setattr(store, "transition_attempt", fail_terminal_write)
    with pytest.raises(RuntimeError) as raised:
        await service.execute_node(run_id, "node", None, None, executor=_must_not_execute)
    assert raised.value is cleanup_failure
    attempt = await _attempt(store, run_id)
    assert attempt.status is AttemptStatus.CREATED
    assert attempt.execution_lease is not None
    assert attempt.execution_lease.expires_at is not None
    assert (await store.get_run(run_id)).status is RunStatus.CANCELLED
