"""Crash-window and parked-waker contracts for M1-E2 (#62)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.a2a.delegate import A2ATask, DelegationMode, TaskStatus
from maistro.container import Container
from maistro.graph import Graph, Node
from maistro.graph.durable_runs.stores import InMemoryDurableRunStore, external_result_record
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes.base import PAUSE_REASON_OWNERS, PAUSE_REASON_WAKERS
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


def _graph(workspace_id: str, project_id: str) -> Graph:
    return Graph(
        graph_id="m1-e2-graph",
        workspace_id=workspace_id,
        project_id=project_id,
        name="M1-E2",
        nodes=[Node(node_id="work", node_type="test.m1_e2")],
    )


@pytest.mark.ac("M1-E2/#1192")
def test_every_registered_pause_reason_names_a_production_waker() -> None:
    """A new resumable reason cannot silently become an inert WAITING Run."""
    assert set(PAUSE_REASON_WAKERS) == set(PAUSE_REASON_OWNERS)
    assert all(wakers for wakers in PAUSE_REASON_WAKERS.values())
    assert (
        "Container.wake_external_graph_result" in PAUSE_REASON_WAKERS["awaiting_remote_delegation"]
    )
    assert "resume_due_graph_runs" in PAUSE_REASON_WAKERS["awaiting_remote_delegation"]


@pytest.mark.asyncio
@pytest.mark.ac("M1-E2/#1192")
async def test_external_completion_wakes_a_system_owned_waiting_run() -> None:
    graph = _graph("ws-m1-e2", "project-m1-e2")
    run = Run(
        run_id="remote-parent",
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
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
    run = await store.create_run(graph)
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
