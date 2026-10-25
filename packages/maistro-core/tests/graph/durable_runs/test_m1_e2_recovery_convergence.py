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


@pytest.mark.ac("M1-E2/#1192")
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
@pytest.mark.ac("M1-E2/#1192")
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


@pytest.mark.asyncio
@pytest.mark.ac("M1-E2/#1192")
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
                        "metadata": {"paused_reason": "awaiting_remote_delegation"},
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
@pytest.mark.ac("M1-E2/#1151")
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
@pytest.mark.asyncio
@pytest.mark.ac("M1-E2/#1192")
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
                        "metadata": {"paused_reason": "awaiting_remote_delegation"},
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

    updated = external_result_record(record, "first", {"status": "completed"})

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
                            "metadata": {"paused_reason": "awaiting_harness"},
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
        {"status": "completed", "output": "ok"},
    )
    assert updated.run.status is RunStatus.QUEUED
    persisted = await store.get(run.run_id)
    assert persisted is not None and persisted.hitl_answers["work"]["output"] == "ok"
    replayed = await store.submit_external_result(
        run.run_id,
        "work",
        {"status": "completed", "output": "ok"},
    )
    assert replayed.version == updated.version
