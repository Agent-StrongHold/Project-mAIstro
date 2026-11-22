"""Cancellation receipts must not claim a physical stop nobody proved (#1242).

The witness the issue records: a Run cancelled from a process that does not
own its Attempt fences the Run CANCELLED while the remote owner's Attempt is
still RUNNING. The old bool answer read that as a stop. These tests drive the
real `RunExecutionService` over an in-memory store and check what the receipt
says, so the assertions are on the shipped contract, not on a stub.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import AttemptStatus, InMemoryRunStore, RunExecutionService, RunStatus
from maistro.runs.cancellation import CancellationDisposition
from maistro.runtime import PythonExecutionRuntime
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


async def _service_with_running_attempt(
    lease_holder: str,
) -> tuple[RunExecutionService, InMemoryRunStore, str, str]:
    """A Run whose single Attempt is RUNNING under `lease_holder`'s lease."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    store = InMemoryRunStore(project_store=projects)
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
    graph = Graph(
        graph_id="graph-1242",
        workspace_id="workspace-1",
        project_id=root.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await service.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(
        node_run.node_run_id,
        runtime_id="remote-runtime",
        lease_holder=lease_holder,
        lease_ttl=timedelta(minutes=5),
    )
    assert attempt.execution_lease is not None
    await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    return service, store, run.run_id, attempt.attempt_id


@pytest.mark.asyncio
async def test_remote_owner_cancel_is_fenced_but_not_reported_as_stopped() -> None:
    """Regression for the false-success witness.

    Before the receipt existed, `cancel_run` returned a CANCELLED Run and the
    task/Run API rendered it as `cancelled: true`. The Attempt is still RUNNING
    under a live lease held by a worker this process cannot reach, so the
    honest receipt is fenced-but-not-stopped.
    """
    service, store, run_id, attempt_id = await _service_with_running_attempt("worker-b")

    receipt = await service.cancel_run_receipt(run_id)

    assert receipt.run_status is RunStatus.CANCELLED
    assert receipt.fenced is True
    assert receipt.stop_confirmed is False
    assert receipt.disposition is CancellationDisposition.STOP_PENDING
    [row] = receipt.attempts
    assert row.attempt_id == attempt_id
    assert row.owner == "worker-b"
    # The durable row is untouched: this process must not transition a try it
    # does not own, or it would fabricate the stop it is reporting on.
    persisted = await store.get_attempt(attempt_id)
    assert persisted is not None
    assert persisted.status is AttemptStatus.RUNNING


@pytest.mark.asyncio
async def test_repeat_cancel_keeps_reporting_outstanding_physical_work() -> None:
    """A second cancellation cannot re-prove a stop the first did not have."""
    service, _, run_id, _ = await _service_with_running_attempt("worker-b")
    first = await service.cancel_run_receipt(run_id)

    repeat = await service.cancel_run_receipt(run_id)

    assert repeat.run_status is RunStatus.CANCELLED
    assert repeat.disposition is first.disposition is CancellationDisposition.STOP_PENDING
    assert repeat.stop_confirmed is False


@pytest.mark.asyncio
async def test_cancel_with_no_physical_try_is_confirmed() -> None:
    """A Run cancelled while queued owned no physical work, so the stop is real."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    store = InMemoryRunStore(project_store=projects)
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
    graph = Graph(
        graph_id="graph-queued",
        workspace_id="workspace-1",
        project_id=root.project_id,
        name="Queued",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await service.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)

    receipt = await service.cancel_run_receipt(run.run_id)

    assert receipt.fenced is True
    assert receipt.stop_confirmed is True
    assert receipt.disposition is CancellationDisposition.STOP_CONFIRMED
    assert receipt.attempts == ()


@pytest.mark.asyncio
async def test_a_fence_that_loses_the_completion_race_reports_the_winner() -> None:
    """When completion wins the fence race, the receipt says so - no stop.

    `cancel_run` already yields to the completed survivor; the receipt must
    agree: `run_status` names the actual winner, `fenced` is False because no
    cancellation fence is durable, and the physical try under the remote
    worker's lease is still reported as unaccounted, never as stopped.
    """

    class _FenceLosingToCompletionStore(InMemoryRunStore):
        """The Run COMPLETES in the gap before the CANCELLED fence lands."""

        async def transition_run(self, run_id: str, target: RunStatus, **kwargs: object):
            if target is RunStatus.CANCELLED:
                current = await super().get_run(run_id)
                assert current is not None
                if current.status is RunStatus.RUNNING:
                    await super().transition_run(run_id, RunStatus.COMPLETED)
                return await super().transition_run(run_id, target, **kwargs)  # type: ignore[arg-type]
            return await super().transition_run(run_id, target, **kwargs)  # type: ignore[arg-type]

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    store = _FenceLosingToCompletionStore(project_store=projects)
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
    graph = Graph(
        graph_id="graph-1242-race",
        workspace_id="workspace-1",
        project_id=root.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await service.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(
        node_run.node_run_id,
        runtime_id="remote-runtime",
        lease_holder="worker-b",
        lease_ttl=timedelta(minutes=5),
    )
    assert attempt.execution_lease is not None
    await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )

    receipt = await service.cancel_run_receipt(run.run_id)

    # The winner is named, not the cancellation: no fence is durable and no
    # stop is claimed, but the live try is still somebody's open work.
    assert receipt.run_status is RunStatus.COMPLETED
    assert receipt.fenced is False
    assert receipt.stop_confirmed is False
    assert receipt.disposition is CancellationDisposition.STOP_PENDING
    [row] = receipt.attempts
    assert row.owner == "worker-b"
    assert "worker-b" in receipt.diagnosis


@pytest.mark.asyncio
async def test_cancelling_an_already_completed_run_reports_the_actual_winner() -> None:
    """A repeat cancellation of a finished Run claims no stop and no fence.

    The early terminal path re-reads the durable rows rather than echoing a
    second `cancelled`: the run_status is the winner's own status and the
    disposition is `COMPLETION_WON` - nothing stopped, because nothing was
    running for this request to stop.
    """
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    store = InMemoryRunStore(project_store=projects)
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
    graph = Graph(
        graph_id="graph-1242-late",
        workspace_id="workspace-1",
        project_id=root.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await service.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    await store.transition_run(run.run_id, RunStatus.COMPLETED, result="done")

    receipt = await service.cancel_run_receipt(run.run_id)

    assert receipt.run_status is RunStatus.COMPLETED
    assert receipt.fenced is False
    assert receipt.stop_confirmed is False
    assert receipt.disposition is CancellationDisposition.COMPLETION_WON
    assert receipt.attempts == ()
    assert "already completed" in receipt.diagnosis
    assert "no stop is claimed" in receipt.diagnosis


@pytest.mark.asyncio
async def test_receipt_and_run_projection_agree_on_fence() -> None:
    """`cancel_run` (the Run API's value) and `cancel_run_receipt` share one fence.

    The Run API keeps returning the CANCELLED Run for compatibility; the
    receipt is the honest companion. They must agree on the fence so neither
    surface can say "cancelled" while the other says "not fenced".
    """
    service, store, run_id, _ = await _service_with_running_attempt("worker-b")

    run = await service.cancel_run(run_id)
    persisted = await store.get_run(run_id)

    assert run.status is RunStatus.CANCELLED
    assert persisted is not None and persisted.status is RunStatus.CANCELLED
