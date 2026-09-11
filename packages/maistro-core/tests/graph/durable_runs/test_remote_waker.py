"""Production wakers for answer-gated remote Graph waits (#1192)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from maistro.a2a.delegate import A2ADelegator
from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
    resume_due_graph_runs,
    resume_durable_graph,
    run_durable_graph,
)
from maistro.graph.durable_runs.protocol import DurableRunStore
from maistro.graph.nodes.agent_delegate_remote import AgentDelegateRemoteNode
from maistro.graph.nodes.base import PAUSE_PRODUCTION_WAKERS, PAUSE_RESUME_CONDITIONS
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import RunStatus


async def _spine() -> tuple[InMemoryRunStore, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("remote-waker-ws")
    project = await projects.create(
        workspace_id="remote-waker-ws", parent_project_id=root.project_id, name="Graphs"
    )
    return InMemoryRunStore(project_store=projects), "remote-waker-ws", project.project_id


def _graph(workspace_id: str, project_id: str, timeout_seconds: int = 3600) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="remote delegation",
        nodes=[
            Node(
                node_id="delegate",
                node_type="agent.delegate_remote",
                inputs={
                    "from_agent": "planner",
                    "to_agent": "researcher",
                    "task": "research X",
                    "timeout_seconds": timeout_seconds,
                },
            )
        ],
    )


async def _paused_remote(
    *, timeout_seconds: int = 3600
) -> tuple[CanonicalDurableRunStore, InMemoryRunStore, Any]:
    run_store, workspace_id, project_id = await _spine()
    graph_store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["researcher"])
    node = AgentDelegateRemoteNode(a2a_delegator=delegator, run_store=run_store)
    graph = _graph(workspace_id, project_id, timeout_seconds)
    admitted = await run_store.create_run(graph, initial_status=RunStatus.QUEUED)
    paused = await run_durable_graph(
        graph,
        store=graph_store,
        node_resolver=lambda _node_id, _graph: node,
        run_id=admitted.run_id,
        run_store=run_store,
    )
    assert paused.status is RunStatus.WAITING
    pause = paused.graph_state.metadata["pauses"]["delegate"]
    return graph_store, run_store, (paused, pause, node, graph)


@pytest.mark.contract("behavioral")
async def test_remote_completion_wakes_parent_and_settles_exact_child() -> None:
    store, run_store, (paused, pause, node, _graph) = await _paused_remote()
    child_run_id = str(pause["metadata"]["run_id"])
    task_id = str(pause["metadata"]["task_id"])

    queued = await store.complete_remote_delegation(
        paused.run_id,
        "delegate",
        task_id=task_id,
        child_run_id=child_run_id,
        status="completed",
        result="research complete",
    )
    assert queued.status is RunStatus.QUEUED
    duplicate = await store.complete_remote_delegation(
        paused.run_id,
        "delegate",
        task_id=task_id,
        child_run_id=child_run_id,
        status="completed",
        result="different retry payload",
    )
    assert duplicate.version == queued.version

    resumed = await resume_durable_graph(
        paused.run_id,
        store=store,
        node_resolver=lambda _node_id, _graph: node,
        run_store=run_store,
    )
    assert resumed.status is RunStatus.COMPLETED
    child = await run_store.get_run(child_run_id)
    assert child is not None
    assert child.parent_run_id == paused.run_id
    assert child.parent_node_run_id == resumed.node_runs[0].node_run_id
    assert child.status is RunStatus.COMPLETED
    assert child.result == "research complete"


@pytest.mark.contract("behavioral")
async def test_foreign_receipt_cannot_wake_a_parked_parent() -> None:
    store, _run_store, (paused, pause, _node, _graph) = await _paused_remote()
    with pytest.raises(ValueError, match="child_run_id"):
        await store.complete_remote_delegation(
            paused.run_id,
            "delegate",
            task_id=str(pause["metadata"]["task_id"]),
            child_run_id="foreign-child",
            status="failed",
            error="nope",
        )
    current = await store.get(paused.run_id)
    assert current is not None and current.status is RunStatus.WAITING


@pytest.mark.contract("behavioral")
async def test_remote_deadline_is_a_durable_timer_waker() -> None:
    store, run_store, (paused, pause, node, _graph) = await _paused_remote(timeout_seconds=1)
    deadline = datetime.fromisoformat(str(pause["resume_at"]))
    assert (
        await resume_due_graph_runs(
            store=store,
            run_store=run_store,
            node_resolver=lambda _node_id, _graph: node,
            now=deadline + timedelta(microseconds=1),
        )
        == 1
    )
    resumed = await store.get(paused.run_id)
    assert resumed is not None
    assert resumed.status is RunStatus.COMPLETED
    child_id = str(pause["metadata"]["run_id"])
    child = await run_store.get_run(child_id)
    assert child is not None and child.status is RunStatus.TIMED_OUT


def test_every_registered_resume_condition_names_a_production_waker() -> None:
    assert set(PAUSE_PRODUCTION_WAKERS) == set(PAUSE_RESUME_CONDITIONS)
    assert all(PAUSE_PRODUCTION_WAKERS.values())
    assert hasattr(DurableRunStore, "complete_remote_delegation")
    assert "resume_due_graph_runs(timer)" in PAUSE_PRODUCTION_WAKERS.values()
