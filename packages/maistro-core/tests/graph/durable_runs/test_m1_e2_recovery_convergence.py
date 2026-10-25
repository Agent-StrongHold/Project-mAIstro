"""Crash-window and parked-waker contracts for M1-E2 (#62)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from maistro.a2a.delegate import A2ATask, DelegationMode, TaskStatus
from maistro.a2a.guest_peers import DelegationResult
from maistro.container import Container
from maistro.graph import Graph, Node
from maistro.graph.durable_runs import poll_external_results
from maistro.graph.durable_runs.stores import InMemoryDurableRunStore, external_result_record
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes.base import (
    PAUSE_AWAITING_DELEGATION_RECONCILIATION,
    PAUSE_AWAITING_HARNESS,
    PAUSE_AWAITING_HUMAN_ANSWER,
    PAUSE_AWAITING_HUMAN_APPROVAL,
    PAUSE_AWAITING_HUMAN_REVIEW,
    PAUSE_AWAITING_REMOTE_DELEGATION,
    PAUSE_AWAITING_ROLE_DELEGATE,
    PAUSE_REASON_OWNERS,
    PAUSE_WAITING_ON_JIRA_SUBTASKS,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import AttemptStatus, InMemoryRunStore, RunStatus
from maistro.runs.model import (
    AcceptedNodeOutcome,
    AttemptResult,
    GraphSnapshot,
    NodeRun,
    Run,
)
from maistro.runs.reconciliation import reconcile_stranded_runs

pytestmark = pytest.mark.contract("behavioral")

#: The production actor that can satisfy each registered resume condition.
#: The map is deliberately test-local (the same disposition
#: ``test_pause_reason_wakers.py`` records): a production registry nobody in
#: package code imports would itself be unreachable code. Keeping it beside
#: the mechanical proof makes a newly registered pause reason fail review
#: until it names a reachable answer, event, timer, or cancellation seam
#: (#1192).
PAUSE_REASON_WAKERS: dict[str, tuple[str, ...]] = {
    PAUSE_AWAITING_HUMAN_ANSWER: ("CanonicalDurableRunStore.submit_hitl_answer",),
    PAUSE_AWAITING_HUMAN_APPROVAL: ("CanonicalDurableRunStore.submit_hitl_answer",),
    PAUSE_AWAITING_HUMAN_REVIEW: ("CanonicalDurableRunStore.submit_hitl_answer",),
    PAUSE_AWAITING_ROLE_DELEGATE: ("CanonicalDurableRunStore.submit_hitl_answer",),
    PAUSE_AWAITING_REMOTE_DELEGATION: (
        "Container.wake_external_graph_result",
        "poll_external_results",
        "CanonicalDurableRunStore.submit_external_result",
        "resume_due_graph_runs",
    ),
    PAUSE_AWAITING_HARNESS: (
        "poll_external_results",
        "CanonicalDurableRunStore.submit_external_result",
        "resume_due_graph_runs",
    ),
    PAUSE_WAITING_ON_JIRA_SUBTASKS: ("Container.resume_parked_runs",),
    PAUSE_AWAITING_DELEGATION_RECONCILIATION: ("resume_due_graph_runs",),
}


def _graph(workspace_id: str, project_id: str) -> Graph:
    return Graph(
        graph_id="m1-e2-graph",
        workspace_id=workspace_id,
        project_id=project_id,
        name="M1-E2",
        nodes=[Node(node_id="work", node_type="test.m1_e2")],
    )


#: Import paths for the symbolic names in `PAUSE_REASON_WAKERS`. The waker
#: contract is kept executable here rather than via a production registry
#: nobody imports: the map resolves every symbolic waker to its defining
#: module and refuses one that is missing or not callable (#1192).
_PAUSE_WAKER_TARGETS: dict[str, str] = {
    "CanonicalDurableRunStore.submit_hitl_answer": (
        "maistro.graph.durable_runs.canonical_store:CanonicalDurableRunStore.submit_hitl_answer"
    ),
    "CanonicalDurableRunStore.submit_external_result": (
        "maistro.graph.durable_runs.canonical_store:CanonicalDurableRunStore.submit_external_result"
    ),
    "Container.wake_external_graph_result": "maistro.container:Container.wake_external_graph_result",
    "poll_external_results": "maistro.graph.durable_runs.recovery:poll_external_results",
    "Container.resume_parked_runs": "maistro.container:Container.resume_parked_runs",
    "resume_due_graph_runs": "maistro.graph.durable_runs.recovery:resume_due_graph_runs",
}


def _validate_pause_reason_wakers() -> None:
    """Fail if a registered waker no longer names a reachable callable."""
    import importlib

    if set(PAUSE_REASON_WAKERS) != set(PAUSE_REASON_OWNERS):
        raise RuntimeError("pause owners and wakers classify different reasons")
    for reason, wakers in PAUSE_REASON_WAKERS.items():
        if not wakers:
            raise RuntimeError(f"pause reason {reason!r} has no production waker")
        for name in wakers:
            target_path = _PAUSE_WAKER_TARGETS.get(name)
            if target_path is None:
                raise RuntimeError(f"pause reason {reason!r} has unknown waker {name!r}")
            module_name, object_path = target_path.split(":", 1)
            target: Any = importlib.import_module(module_name)
            for component in object_path.split("."):
                target = getattr(target, component)
            if not callable(target):
                raise RuntimeError(f"pause waker {name!r} is not callable")


# No @pytest.mark.ac claim: M1-E2/#1192 names an issue, not a declared
# criterion id, and the acceptance ledger ceilings markers that name nothing
# (test_pause_reason_wakers.py carries no marker for the same reason).
def test_every_registered_pause_reason_names_a_production_waker() -> None:
    """A new resumable reason cannot silently become an inert WAITING Run."""
    assert set(PAUSE_REASON_WAKERS) == set(PAUSE_REASON_OWNERS)
    assert all(wakers for wakers in PAUSE_REASON_WAKERS.values())
    assert (
        "Container.wake_external_graph_result" in PAUSE_REASON_WAKERS["awaiting_remote_delegation"]
    )
    assert "resume_due_graph_runs" in PAUSE_REASON_WAKERS["awaiting_remote_delegation"]
    _validate_pause_reason_wakers()


@pytest.mark.asyncio
async def test_cross_instance_polling_writes_the_canonical_external_result() -> None:
    """A remote peer has a real timer-tick ingress, not an in-process receipt assumption."""
    graph = _graph("ws-m1-e2-peer", "project-m1-e2-peer")
    run = Run(
        run_id="remote-poll-parent",
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        actor_principal_id="test-actor",
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.WAITING,
    )
    record = DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(
            run_id=run.run_id,
            active_node_ids=("work",),
            metadata={
                "pauses": {
                    "work": {
                        "kind": "wait",
                        "metadata": {
                            "paused_reason": "awaiting_remote_delegation",
                            "peer_name": "hub",
                            "task_id": "remote-1",
                        },
                    }
                }
            },
        ),
        node_runs=(
            NodeRun(run_id=run.run_id, node_id="work", ordinal=1, status=RunStatus.WAITING),
        ),
        version=1,
    )

    class _GraphStore:
        async def list_by_status(self, status: RunStatus, *, limit: int = 100, **kwargs: object):
            del kwargs
            return [record] if status is RunStatus.WAITING else []

        submit_external_result = AsyncMock()

    peers = SimpleNamespace(
        poll_result=AsyncMock(
            return_value=DelegationResult(
                task_id="remote-1",
                peer_name="hub",
                status="completed",
                result="done",
            )
        )
    )

    assert (
        await poll_external_results(
            store=_GraphStore(),
            guest_peers=peers,
            harness_adapters={},
            limit=10,
        )
        == 1
    )
    peers.poll_result.assert_awaited_once_with("hub", "remote-1")
    _GraphStore.submit_external_result.assert_awaited_once_with(
        "remote-poll-parent",
        "work",
        {"status": "completed", "task_id": "remote-1", "result": "done", "error": None},
    )


def _parked_record(
    run_id: str,
    *,
    status: RunStatus = RunStatus.WAITING,
    pauses: Any,
    resume_at: datetime | None = None,
) -> DurableRunRecord:
    """A system-owned parked Run whose frontier carries raw pause entries."""
    graph = _graph("ws-m1-e2-peer", "project-m1-e2-peer")
    run = Run(
        run_id=run_id,
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        actor_principal_id="test-actor",
        graph=GraphSnapshot.from_graph(graph),
        status=status,
    )
    node_status = RunStatus.WAITING if status is RunStatus.WAITING else RunStatus.PAUSED
    return DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(
            run_id=run_id,
            active_node_ids=("work",),
            metadata={"pauses": pauses},
        ),
        node_runs=(NodeRun(run_id=run_id, node_id="work", ordinal=1, status=node_status),),
        resume_at=resume_at,
        version=1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("victim_status", [RunStatus.WAITING, RunStatus.PAUSED])
async def test_external_poll_pages_past_unrelated_waits(victim_status: RunStatus) -> None:
    """Neither ownership filters nor the WAITING bucket can hide a completion."""
    store = InMemoryDurableRunStore()
    for index in range(3):
        await store.create(_parked_record(f"unrelated-{index}", pauses={}))
    victim = _remote_delegation_record(resume_at=None)
    victim = victim.model_copy(
        update={
            "run": victim.run.model_copy(update={"status": victim_status}),
            "node_runs": tuple(
                node.model_copy(update={"status": victim_status}) for node in victim.node_runs
            ),
        }
    )
    await store.create(victim)
    peers = SimpleNamespace(
        poll_result=AsyncMock(
            return_value=DelegationResult(
                task_id="remote-1", peer_name="hub", status="completed", result="done"
            )
        )
    )
    assert (
        await poll_external_results(
            store=store,
            guest_peers=peers,
            harness_adapters={},
            limit=1,
            eligible=lambda run: run.run_id == victim.run_id,
        )
        == 1
    )
    assert (await store.get(victim.run_id)).run.status is RunStatus.QUEUED
    peers.poll_result.assert_awaited_once_with("hub", "remote-1")


@pytest.mark.asyncio
async def test_external_poll_scan_advances_across_ticks_and_provider_failures() -> None:
    """A prefix longer than the inspection budget is a pace, not a horizon."""
    from maistro.graph.durable_runs import ScanContinuation

    store = InMemoryDurableRunStore()
    for index in range(5):
        await store.create(_parked_record(f"unrelated-{index}", pauses={}))
    victim = _remote_delegation_record(resume_at=None)
    await store.create(victim)
    peers = SimpleNamespace(poll_result=AsyncMock(side_effect=RuntimeError("offline")))
    scan = ScanContinuation()
    positions = []
    for _ in range(6):
        assert (
            await poll_external_results(
                store=store,
                guest_peers=peers,
                harness_adapters={},
                limit=1,
                max_inspected=2,
                scan=scan,
            )
            == 0
        )
        positions.append(scan.resume_after)
    assert peers.poll_result.await_count >= 1
    assert len(set(positions)) > 1
    assert (await store.get(victim.run_id)).run.status is RunStatus.WAITING
    peers.poll_result.side_effect = None
    peers.poll_result.return_value = DelegationResult(
        task_id="remote-1", peer_name="hub", status="completed", result="done"
    )
    delivered = 0
    for _ in range(6):
        delivered += await poll_external_results(
            store=store,
            guest_peers=peers,
            harness_adapters={},
            limit=1,
            max_inspected=2,
            scan=scan,
        )
    assert delivered == 1
    assert (await store.get(victim.run_id)).run.status is RunStatus.QUEUED


def _remote_delegation_record(resume_at: datetime | None) -> DurableRunRecord:
    """A system-owned WAITING remote-delegation pause with a chosen timer."""
    graph = _graph("ws-m1-e2-peer", "project-m1-e2-peer")
    run = Run(
        run_id="remote-poll-parent",
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        actor_principal_id="test-actor",
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.WAITING,
    )
    return DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(
            run_id=run.run_id,
            active_node_ids=("work",),
            metadata={
                "pauses": {
                    "work": {
                        "kind": "wait",
                        "metadata": {
                            "paused_reason": "awaiting_remote_delegation",
                            "peer_name": "hub",
                            "task_id": "remote-1",
                        },
                    }
                }
            },
        ),
        node_runs=(
            NodeRun(run_id=run.run_id, node_id="work", ordinal=1, status=RunStatus.WAITING),
        ),
        resume_at=resume_at,
        version=1,
    )


@pytest.mark.asyncio
async def test_the_external_seam_defers_a_due_timer_wait_to_the_timed_resume() -> None:
    """An elapsed wait belongs to the walker's fenced poll, not this seam.

    Polling it here first would read the same provider twice in one tick and
    then discard the result when the walker re-polls the settled receipt.
    """
    now = datetime.now(UTC)
    record = _remote_delegation_record(resume_at=now - timedelta(seconds=1))

    class _GraphStore:
        async def list_by_status(self, status: RunStatus, *, limit: int = 100, **kwargs: object):
            del kwargs
            return [record] if status is RunStatus.WAITING else []

        submit_external_result = AsyncMock()

    peers = SimpleNamespace(poll_result=AsyncMock())

    assert (
        await poll_external_results(
            store=_GraphStore(),
            guest_peers=peers,
            harness_adapters={},
            limit=10,
            now=now,
        )
        == 0
    )
    peers.poll_result.assert_not_awaited()
    _GraphStore.submit_external_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_external_seam_drains_a_completion_that_lands_before_the_timer() -> None:
    """A completion arriving ahead of the timer is still this seam's ingress."""
    now = datetime.now(UTC)
    record = _remote_delegation_record(resume_at=now + timedelta(minutes=1))

    class _GraphStore:
        async def list_by_status(self, status: RunStatus, *, limit: int = 100, **kwargs: object):
            del kwargs
            return [record] if status is RunStatus.WAITING else []

        submit_external_result = AsyncMock()

    peers = SimpleNamespace(
        poll_result=AsyncMock(
            return_value=DelegationResult(
                task_id="remote-1",
                peer_name="hub",
                status="completed",
                result="done",
            )
        )
    )

    assert (
        await poll_external_results(
            store=_GraphStore(),
            guest_peers=peers,
            harness_adapters={},
            limit=10,
            now=now,
        )
        == 1
    )
    peers.poll_result.assert_awaited_once_with("hub", "remote-1")
    _GraphStore.submit_external_result.assert_awaited_once()


class _RecordingGraphStore:
    """Store double answering ``list_by_status`` from a fixed record page."""

    def __init__(self, *records: DurableRunRecord) -> None:
        self._records = records
        self.submit_external_result = AsyncMock()

    async def list_by_status(self, status: RunStatus, *, limit: int = 100, **kwargs: object):
        del kwargs
        return [r for r in self._records if r.run.status is status][:limit]


@pytest.mark.asyncio
async def test_the_external_seam_refuses_a_non_positive_limit() -> None:
    """A misconfigured tick must not read the store at all, like its siblings."""

    class _MustNotRead:
        async def list_by_status(self, *args: object, **kwargs: object):
            raise AssertionError("a non-positive limit must not read the store")

    assert (
        await poll_external_results(
            store=_MustNotRead(),
            guest_peers=None,
            harness_adapters={},
            limit=0,
        )
        == 0
    )


@pytest.mark.asyncio
async def test_a_raising_provider_leaves_the_wait_parked_for_the_next_tick() -> None:
    """A transport failure is not a delegation outcome: the wait stays parked."""
    now = datetime.now(UTC)
    record = _remote_delegation_record(resume_at=None)
    store = _RecordingGraphStore(record)
    peers = SimpleNamespace(poll_result=AsyncMock(side_effect=RuntimeError("peer unreachable")))

    assert (
        await poll_external_results(
            store=store,
            guest_peers=peers,
            harness_adapters={},
            limit=10,
            now=now,
        )
        == 0
    )
    store.submit_external_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_pauses_without_an_external_waker_are_not_polled_here() -> None:
    """HITL-style pauses have their own answer seam; the tick must skip them."""
    now = datetime.now(UTC)
    record = _parked_record(
        "human-paused",
        pauses={
            "work": {
                "kind": "wait",
                "metadata": {"paused_reason": "awaiting_human_answer"},
            }
        },
    )
    store = _RecordingGraphStore(record)
    peers = SimpleNamespace(poll_result=AsyncMock())

    assert (
        await poll_external_results(
            store=store,
            guest_peers=peers,
            harness_adapters={},
            limit=10,
            now=now,
        )
        == 0
    )
    peers.poll_result.assert_not_awaited()
    store.submit_external_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_pause_records_cannot_crash_the_tick() -> None:
    """A corrupt pause entry parks that node, not the whole recovery sweep."""
    now = datetime.now(UTC)
    malformed_pauses = _parked_record("bad-pauses", pauses=["not-a-mapping"])
    malformed_metadata = _parked_record(
        "bad-metadata",
        pauses={"work": {"kind": "wait", "metadata": "not-a-mapping"}},
    )
    store = _RecordingGraphStore(malformed_pauses, malformed_metadata)
    peers = SimpleNamespace(poll_result=AsyncMock())

    assert (
        await poll_external_results(
            store=store,
            guest_peers=peers,
            harness_adapters={},
            limit=10,
            now=now,
        )
        == 0
    )
    peers.poll_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_paused_run_is_polled_even_when_its_own_timer_elapsed() -> None:
    """The due-timer deferral is scoped to WAITING: a PAUSED external pause has
    no timed resume of its own, so the seam stays its ingress."""
    now = datetime.now(UTC)
    record = _parked_record(
        "paused-delegation",
        status=RunStatus.PAUSED,
        pauses={
            "work": {
                "kind": "wait",
                "metadata": {
                    "paused_reason": "awaiting_remote_delegation",
                    "peer_name": "hub",
                    "task_id": "remote-1",
                },
            }
        },
        resume_at=now - timedelta(seconds=1),
    )
    store = _RecordingGraphStore(record)
    peers = SimpleNamespace(
        poll_result=AsyncMock(
            return_value=DelegationResult(
                task_id="remote-1",
                peer_name="hub",
                status="completed",
                result="done",
            )
        )
    )

    assert (
        await poll_external_results(
            store=store,
            guest_peers=peers,
            harness_adapters={},
            limit=10,
            now=now,
        )
        == 1
    )
    store.submit_external_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_receipt_the_store_refuses_is_not_counted_as_delivered() -> None:
    """At-least-once polling races a timeout or another replica: the canonical
    store keeps the winner and the tick must not claim the delivery."""
    now = datetime.now(UTC)
    record = _remote_delegation_record(resume_at=None)
    store = _RecordingGraphStore(record)
    store.submit_external_result = AsyncMock(side_effect=ValueError("already settled"))
    peers = SimpleNamespace(
        poll_result=AsyncMock(
            return_value=DelegationResult(
                task_id="remote-1",
                peer_name="hub",
                status="completed",
                result="done",
            )
        )
    )

    assert (
        await poll_external_results(
            store=store,
            guest_peers=peers,
            harness_adapters={},
            limit=10,
            now=now,
        )
        == 0
    )


@pytest.mark.asyncio
async def test_an_injected_harness_completion_is_delivered_by_the_seam() -> None:
    """Harness pauses are polled through their registered adapter, not peers."""
    now = datetime.now(UTC)
    record = _parked_record(
        "harness-paused",
        pauses={
            "work": {
                "kind": "wait",
                "metadata": {
                    "paused_reason": "awaiting_harness",
                    "harness_type": "shell",
                    "handle_id": "h-1",
                },
            }
        },
    )
    store = _RecordingGraphStore(record)
    adapter = SimpleNamespace(
        poll=AsyncMock(
            return_value=SimpleNamespace(
                success=True,
                handle_id="h-1",
                output="ok",
                error=None,
                metadata={},
            )
        )
    )

    assert (
        await poll_external_results(
            store=store,
            guest_peers=None,
            harness_adapters={"shell": adapter},
            limit=10,
            now=now,
        )
        == 1
    )
    adapter.poll.assert_awaited_once()
    store.submit_external_result.assert_awaited_once_with(
        "harness-paused",
        "work",
        {
            "status": "completed",
            "handle_id": "h-1",
            "output": "ok",
            "error": None,
            "metadata": {},
        },
    )


@pytest.mark.asyncio
async def test_a_failed_harness_completion_writes_a_failed_result() -> None:
    """A terminal harness failure is an outcome, not a poll error."""
    now = datetime.now(UTC)
    record = _parked_record(
        "harness-failed",
        pauses={
            "work": {
                "kind": "wait",
                "metadata": {
                    "paused_reason": "awaiting_harness",
                    "harness_type": "shell",
                    "handle_id": "h-2",
                },
            }
        },
    )
    store = _RecordingGraphStore(record)
    adapter = SimpleNamespace(
        poll=AsyncMock(
            return_value=SimpleNamespace(
                success=False,
                handle_id="h-2",
                output=None,
                error="boom",
                metadata={},
            )
        )
    )

    assert (
        await poll_external_results(
            store=store,
            guest_peers=None,
            harness_adapters={"shell": adapter},
            limit=10,
            now=now,
        )
        == 1
    )
    store.submit_external_result.assert_awaited_once_with(
        "harness-failed",
        "work",
        {
            "status": "failed",
            "handle_id": "h-2",
            "output": None,
            "error": "boom",
            "metadata": {},
        },
    )


@pytest.mark.asyncio
async def test_a_harness_pause_without_a_registered_adapter_stays_parked() -> None:
    """An unknown harness type has no waker here; the pause must survive."""
    now = datetime.now(UTC)
    record = _parked_record(
        "harness-unknown",
        pauses={
            "work": {
                "kind": "wait",
                "metadata": {
                    "paused_reason": "awaiting_harness",
                    "harness_type": "mystery",
                    "handle_id": "h-3",
                },
            }
        },
    )
    store = _RecordingGraphStore(record)

    assert (
        await poll_external_results(
            store=store,
            guest_peers=None,
            harness_adapters={},
            limit=10,
            now=now,
        )
        == 0
    )
    store.submit_external_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_peer_metadata_without_a_destination_is_left_parked() -> None:
    """A delegation pause that names no peer/task, or whose task still runs,
    is not deliverable yet: the seam must leave it for a later tick."""
    now = datetime.now(UTC)
    no_peer = _parked_record(
        "delegation-no-peer",
        pauses={
            "work": {
                "kind": "wait",
                "metadata": {"paused_reason": "awaiting_remote_delegation"},
            }
        },
    )
    still_running = _parked_record(
        "delegation-running",
        pauses={
            "work": {
                "kind": "wait",
                "metadata": {
                    "paused_reason": "awaiting_remote_delegation",
                    "peer_name": "hub",
                    "task_id": "remote-2",
                },
            }
        },
    )
    store = _RecordingGraphStore(no_peer, still_running)
    peers = SimpleNamespace(poll_result=AsyncMock(return_value=None))

    assert (
        await poll_external_results(
            store=store,
            guest_peers=peers,
            harness_adapters={},
            limit=10,
            now=now,
        )
        == 0
    )
    peers.poll_result.assert_awaited_once_with("hub", "remote-2")
    store.submit_external_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_a2a_receipt_waker_writes_the_canonical_external_result() -> None:
    """The in-process completion bridge is the reachable waker for A2A receipts."""
    container = Container.__new__(Container)
    container.graph_run_store = _RecordingGraphStore()
    task = SimpleNamespace(
        metadata={"parent_run_id": "run-1", "parent_node_id": "work"},
        status=SimpleNamespace(value="completed"),
        id="t-1",
        result="r",
        error=None,
    )

    await container.wake_external_graph_result(task)

    container.graph_run_store.submit_external_result.assert_awaited_once_with(
        "run-1",
        "work",
        {"status": "completed", "task_id": "t-1", "result": "r", "error": None},
    )


@pytest.mark.asyncio
async def test_the_a2a_receipt_waker_ignores_receipts_it_cannot_route() -> None:
    """Receipts without canonical routing metadata are transport noise."""
    container = Container.__new__(Container)
    container.graph_run_store = _RecordingGraphStore()

    # No store at all: a standalone Conductor must not crash on a receipt.
    naked = Container.__new__(Container)
    naked.graph_run_store = None
    await naked.wake_external_graph_result(SimpleNamespace(metadata={"parent_run_id": "r"}))

    unroutable = [
        SimpleNamespace(metadata="not-a-dict", status=SimpleNamespace(value="completed")),
        SimpleNamespace(
            metadata={"parent_node_id": "work"}, status=SimpleNamespace(value="completed")
        ),
        SimpleNamespace(
            metadata={"parent_run_id": "run-1"}, status=SimpleNamespace(value="completed")
        ),
        SimpleNamespace(
            metadata={"parent_run_id": "run-1", "parent_node_id": "work"},
            status=SimpleNamespace(value="running"),
        ),
    ]
    for task in unroutable:
        await container.wake_external_graph_result(task)

    container.graph_run_store.submit_external_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_stale_a2a_receipt_cannot_rewrite_its_parent() -> None:
    """A parent answered, timed out, or purged before the receipt stays won."""
    container = Container.__new__(Container)
    store = _RecordingGraphStore()
    store.submit_external_result = AsyncMock(side_effect=ValueError("already settled"))
    container.graph_run_store = store
    task = SimpleNamespace(
        metadata={"parent_run_id": "run-1", "parent_node_id": "work"},
        status=SimpleNamespace(value="failed"),
        id="t-2",
        result=None,
        error="boom",
    )

    await container.wake_external_graph_result(task)

    store.submit_external_result.assert_awaited_once()


def test_the_receipt_scheduler_needs_a_running_loop() -> None:
    """Outside asyncio the scheduler warns and drops the wake instead of raising
    through A2A's synchronous receipt API."""
    container = Container.__new__(Container)
    task = SimpleNamespace(metadata={"parent_run_id": "run-1"}, id="t-3")

    assert container._schedule_external_graph_result(task) is None


@pytest.mark.asyncio
async def test_the_stranded_sweep_skips_what_it_cannot_replay() -> None:
    """No attempts, a still-running attempt, or a vanished row each leave the
    parent untouched, and a non-positive limit reads nothing at all."""
    projects = InMemoryProjectScopeStore()
    workspace_id = "ws-m1-e2-stranded-gaps"
    root = await projects.create_root(workspace_id)
    project = await projects.create(
        workspace_id=workspace_id,
        parent_project_id=root.project_id,
        name="M1-E2 stranded gaps",
    )
    store = InMemoryRunStore(project_store=projects)

    assert await reconcile_stranded_runs(store, limit=0) == 0

    graph = _graph(workspace_id, project.project_id)
    stranded = await store.create_run(graph, actor_principal_id="test-actor")
    await store.transition_run(stranded.run_id, RunStatus.QUEUED)
    await store.transition_run(stranded.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(stranded.run_id, node_id="work")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    node_run = await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)

    # An attemptless frontier and a still-running attempt are both non-evidence.
    attemptless = await store.create_node_run(stranded.run_id, node_id="work")
    await store.transition_node_run(attemptless.node_run_id, RunStatus.QUEUED)
    attemptless = await store.transition_node_run(attemptless.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)

    assert await reconcile_stranded_runs(store) == 0
    assert (await store.get_run(stranded.run_id)).status is RunStatus.RUNNING  # type: ignore[union-attr]

    class _VanishingStore:
        async def list_by_status(self, status: RunStatus, *, limit: int = 100):
            return [] if status is not RunStatus.RUNNING else [SimpleNamespace(run_id="evaporated")]

        async def get_run(self, run_id: str):
            return None

        async def list_node_runs(self, run_id: str):
            return []

        async def list_attempts(self, node_run_id: str):
            return []

    assert await reconcile_stranded_runs(_VanishingStore()) == 0


@pytest.mark.asyncio
async def test_external_completion_wakes_a_system_owned_waiting_run() -> None:
    graph = _graph("ws-m1-e2", "project-m1-e2")
    run = Run(
        run_id="remote-parent",
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        actor_principal_id="test-actor",
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.WAITING,
    )
    node_run = NodeRun(
        run_id=run.run_id,
        node_id="work",
        ordinal=1,
        status=RunStatus.WAITING,
    )
    deadline = datetime.now(UTC) + timedelta(minutes=1)
    record = DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(
            run_id=run.run_id,
            active_node_ids=("work",),
            metadata={
                "pauses": {
                    "work": {
                        "kind": "wait",
                        "metadata": {
                            "paused_reason": "awaiting_remote_delegation",
                            "task_id": "remote-task",
                        },
                        "resume_at": deadline.isoformat(),
                    }
                }
            },
        ),
        node_runs=(node_run,),
        version=1,
    )
    updated = external_result_record(
        record,
        "work",
        {"status": "completed", "task_id": "remote-task"},
    )

    assert updated.run.status is RunStatus.QUEUED
    assert updated.node_runs[0].status is RunStatus.QUEUED
    assert updated.hitl_answers["work"]["task_id"] == "remote-task"
    assert updated.graph_state.metadata.get("pauses") is None


@pytest.mark.asyncio
async def test_recovery_rederives_parent_after_node_run_settlement_write() -> None:
    projects = InMemoryProjectScopeStore()
    workspace_id = "ws-m1-e2-replay"
    root = await projects.create_root(workspace_id)
    project = await projects.create(
        workspace_id=workspace_id,
        parent_project_id=root.project_id,
        name="M1-E2 replay",
    )
    store = InMemoryRunStore(project_store=projects)
    graph = _graph(workspace_id, project.project_id)
    run = await store.create_run(graph, actor_principal_id="test-actor")
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="work")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    node_run = await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.COMPLETED,
        result={"ok": True},
    )
    accepted = AcceptedNodeOutcome(
        node_run_id=node_run.node_run_id,
        attempt_result=AttemptResult.from_attempt(attempt),
        logical_status=RunStatus.COMPLETED,
        result={"ok": True},
    )
    await store.transition_node_run(
        node_run.node_run_id,
        RunStatus.COMPLETED,
        result={"ok": True},
        accepted_outcome=accepted,
    )

    assert await reconcile_stranded_runs(store) == 1
    repaired = await store.get_run(run.run_id)
    assert repaired is not None and repaired.status is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_terminal_a2a_receipt_reaches_the_canonical_external_waker() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    class _GraphStore:
        async def submit_external_result(
            self, run_id: str, node_id: str, result: dict[str, object]
        ) -> None:
            calls.append((run_id, node_id, result))

    task = A2ATask(
        id="a2a-task",
        from_agent="planner",
        to_agent="coder",
        task="work",
        status=TaskStatus.COMPLETED,
        created_at=datetime.now(UTC),
        assigned_at=None,
        completed_at=datetime.now(UTC),
        result="done",
        error=None,
        delegation_mode=DelegationMode.ALLOW_LIST,
        metadata={"parent_run_id": "parent", "parent_node_id": "delegate"},
    )
    container = type("_Container", (), {"graph_run_store": _GraphStore()})()

    await Container.wake_external_graph_result(container, task)  # type: ignore[arg-type]

    assert calls == [
        (
            "parent",
            "delegate",
            {"status": "completed", "task_id": "a2a-task", "result": "done", "error": None},
        )
    ]


def test_external_result_preserves_a_second_parked_frontier_deadline() -> None:
    graph = Graph(
        graph_id="m1-e2-frontier",
        workspace_id="ws-m1-e2-frontier",
        project_id="project-m1-e2-frontier",
        name="M1-E2 frontier",
        nodes=[
            Node(node_id="first", node_type="test.m1_e2"),
            Node(node_id="second", node_type="test.m1_e2"),
        ],
    )
    run = Run(
        run_id="frontier-parent",
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        actor_principal_id="test-actor",
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.WAITING,
    )
    first_deadline = datetime.now(UTC) - timedelta(seconds=1)
    second_deadline = datetime.now(UTC) + timedelta(minutes=1)
    record = DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(
            run_id=run.run_id,
            active_node_ids=("first", "second"),
            metadata={
                "pauses": {
                    node_id: {
                        "kind": "wait",
                        "metadata": {
                            "paused_reason": "awaiting_remote_delegation",
                            "task_id": f"remote-{node_id}",
                        },
                        "resume_at": deadline.isoformat(),
                    }
                    for node_id, deadline in (
                        ("first", first_deadline),
                        ("second", second_deadline),
                    )
                }
            },
        ),
        node_runs=(
            NodeRun(run_id=run.run_id, node_id="first", ordinal=1, status=RunStatus.WAITING),
            NodeRun(run_id=run.run_id, node_id="second", ordinal=2, status=RunStatus.WAITING),
        ),
        resume_at=first_deadline,
        version=1,
    )

    updated = external_result_record(
        record, "first", {"status": "completed", "task_id": "remote-first"}
    )

    assert updated.run.status is RunStatus.WAITING
    assert updated.resume_at == second_deadline
    assert updated.node_runs[0].status is RunStatus.QUEUED
    assert updated.node_runs[1].status is RunStatus.WAITING


@pytest.mark.asyncio
async def test_external_result_is_persisted_by_the_in_memory_checkpoint_store() -> None:
    """The public store seam survives the same optimistic record boundary."""
    store = InMemoryDurableRunStore()
    graph = _graph("ws-m1-e2-store", "project-m1-e2-store")
    run = Run(
        run_id="external-store",
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        actor_principal_id="test-actor",
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.WAITING,
    )
    node = NodeRun(
        run_id=run.run_id,
        node_id="work",
        ordinal=1,
        status=RunStatus.WAITING,
    )
    await store.create(
        DurableRunRecord(
            run=run,
            graph_state=GraphExecutionState(
                run_id=run.run_id,
                active_node_ids=("work",),
                metadata={
                    "pauses": {
                        "work": {
                            "kind": "wait",
                            "metadata": {"paused_reason": "awaiting_harness", "handle_id": "h-1"},
                        }
                    }
                },
            ),
            node_runs=(node,),
            version=1,
        )
    )
    updated = await store.submit_external_result(
        run.run_id,
        "work",
        {"status": "completed", "handle_id": "h-1", "output": "ok"},
    )
    assert updated.run.status is RunStatus.QUEUED
    persisted = await store.get(run.run_id)
    assert persisted is not None and persisted.hitl_answers["work"]["output"] == "ok"
    replayed = await store.submit_external_result(
        run.run_id,
        "work",
        {"status": "completed", "handle_id": "h-1", "output": "ok"},
    )
    assert replayed.version == updated.version
