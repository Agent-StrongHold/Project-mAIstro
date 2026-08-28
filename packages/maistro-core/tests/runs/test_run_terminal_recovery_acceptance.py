"""Concrete AC-5 proof for replay repair and cyclic-frontier safety (#237)."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.graph import Edge, Graph, Node
from maistro.runs.model import AcceptedNodeOutcome, AttemptResult, AttemptStatus, RunStatus
from maistro.runs.reconciliation import AttemptLifecycleReconciler


@pytest.mark.ac("ADR-082526-237d/AC-5")
async def test_replay_repairs_parent_without_false_cyclic_settlement(
    memory_spine: Any,
) -> None:
    store, workspace, project_id = memory_spine

    direct = Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Replay repair",
        nodes=[Node(node_id="only", node_type="agent")],
    )
    run = await store.create_run(direct)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="only")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    node_run = await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.COMPLETED,
        result={"ok": True},
    )
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run.node_run_id,
        attempt_result=AttemptResult.from_attempt(attempt),
        logical_status=RunStatus.COMPLETED,
        result={"ok": True},
    )
    await store.transition_node_run(
        node_run.node_run_id,
        RunStatus.COMPLETED,
        result=outcome.result,
        accepted_outcome=outcome,
    )
    await AttemptLifecycleReconciler(store).reconcile(attempt)
    repaired = await store.get_run(run.run_id)
    assert repaired is not None and repaired.status is RunStatus.COMPLETED

    cyclic = Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Cycle safety",
        nodes=[
            Node(node_id="a", node_type="agent"),
            Node(node_id="b", node_type="agent"),
        ],
        edges=[
            Edge(from_node="a", to_node="b"),
            Edge(from_node="b", to_node="a"),
        ],
    )
    cyclic_run = await store.create_run(cyclic)
    await store.transition_run(cyclic_run.run_id, RunStatus.QUEUED)
    await store.transition_run(cyclic_run.run_id, RunStatus.RUNNING)
    reconciler = AttemptLifecycleReconciler(store)
    for node_id in ("a", "b"):
        current = await store.create_node_run(cyclic_run.run_id, node_id=node_id)
        await store.transition_node_run(current.node_run_id, RunStatus.QUEUED)
        current = await store.transition_node_run(current.node_run_id, RunStatus.RUNNING)
        current_attempt = await store.create_attempt(current.node_run_id)
        await store.transition_attempt(current_attempt.attempt_id, AttemptStatus.RUNNING)
        current_attempt = await store.transition_attempt(
            current_attempt.attempt_id,
            AttemptStatus.COMPLETED,
            result={"node": node_id},
        )
        await reconciler.reconcile(current_attempt)

    unsettled = await store.get_run(cyclic_run.run_id)
    assert unsettled is not None and unsettled.status is RunStatus.RUNNING
