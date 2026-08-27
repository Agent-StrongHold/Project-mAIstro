"""Canonical Run terminal derivation from logical NodeRun outcomes (#237)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.graph import Edge, Graph, Node
from maistro.runs.model import AcceptedNodeOutcome, AttemptResult, AttemptStatus, RunStatus
from maistro.runs.reconciliation import AttemptLifecycleReconciler


def _graph(workspace: str, project_id: str, node_ids: tuple[str, ...]) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Run derivation",
        nodes=[Node(node_id=node_id, node_type="agent") for node_id in node_ids],
    )


async def _running_nodes(spine: Any, node_ids: tuple[str, ...]) -> tuple[Any, Any, tuple[Any, ...]]:
    store, workspace, project_id = spine
    run = await store.create_run(_graph(workspace, project_id, node_ids))
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_runs = []
    for node_id in node_ids:
        node_run = await store.create_node_run(run.run_id, node_id=node_id)
        await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
        node_run = await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
        node_runs.append(node_run)
    return store, run, tuple(node_runs)


async def _completed_attempt(store: Any, node_run: Any, *, result: object) -> Any:
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    return await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.COMPLETED,
        result=result,
    )


async def _assert_one_node_completes(spine: Any) -> None:
    store, run, (node_run,) = await _running_nodes(spine, ("node-1",))
    attempt = await _completed_attempt(store, node_run, result={"ok": True})
    await AttemptLifecycleReconciler(store).reconcile(attempt)
    settled = await store.get_run(run.run_id)
    assert settled is not None
    assert settled.status is RunStatus.COMPLETED
    assert settled.result == {"ok": True}


async def test_one_node_run_completes_from_reconciliation(spine: Any) -> None:
    await _assert_one_node_completes(spine)


@pytest.mark.ac("ADR-082526-237d/AC-1")
async def test_one_node_run_completes_from_reconciliation_in_memory(memory_spine: Any) -> None:
    await _assert_one_node_completes(memory_spine)


async def _assert_live_sibling_blocks_completion(spine: Any) -> None:
    store, run, node_runs = await _running_nodes(spine, ("node-1", "node-2"))
    first = await _completed_attempt(store, node_runs[0], result={"first": True})
    reconciler = AttemptLifecycleReconciler(store)
    await reconciler.reconcile(first)
    midway = await store.get_run(run.run_id)
    assert midway is not None and midway.status is RunStatus.RUNNING

    second = await _completed_attempt(store, node_runs[1], result={"second": True})
    await reconciler.reconcile(second)
    settled = await store.get_run(run.run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED


async def test_live_sibling_blocks_completion(spine: Any) -> None:
    await _assert_live_sibling_blocks_completion(spine)


@pytest.mark.ac("ADR-082526-237d/AC-2")
async def test_live_sibling_blocks_completion_in_memory(memory_spine: Any) -> None:
    await _assert_live_sibling_blocks_completion(memory_spine)


async def _assert_waiting_is_not_terminal(spine: Any) -> None:
    store, run, (node_run,) = await _running_nodes(spine, ("node-1",))
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.FAILED,
        error="retryable",
    )
    await AttemptLifecycleReconciler(store).reconcile(attempt)
    settled = await store.get_run(run.run_id)
    assert settled is not None and settled.status is RunStatus.WAITING


async def test_waiting_node_does_not_terminalize_run(spine: Any) -> None:
    await _assert_waiting_is_not_terminal(spine)


@pytest.mark.ac("ADR-082526-237d/AC-2")
async def test_waiting_node_does_not_terminalize_run_in_memory(memory_spine: Any) -> None:
    await _assert_waiting_is_not_terminal(memory_spine)


async def _assert_failure_precedence(spine: Any) -> None:
    store, run, node_runs = await _running_nodes(spine, ("node-1", "node-2"))
    first = await _completed_attempt(store, node_runs[0], result={"ok": True})
    second = await _completed_attempt(store, node_runs[1], result={"raw": "done"})
    reconciler = AttemptLifecycleReconciler(store)
    await reconciler.accept_outcome(
        AcceptedNodeOutcome(
            node_run_id=node_runs[0].node_run_id,
            attempt_result=AttemptResult.from_attempt(first),
            logical_status=RunStatus.COMPLETED,
            result={"ok": True},
        )
    )
    await reconciler.accept_outcome(
        AcceptedNodeOutcome(
            node_run_id=node_runs[1].node_run_id,
            attempt_result=AttemptResult.from_attempt(second),
            logical_status=RunStatus.FAILED,
            error="logical failure",
        )
    )
    settled = await store.get_run(run.run_id)
    assert settled is not None
    assert settled.status is RunStatus.FAILED
    assert settled.error == "logical failure"


async def test_mixed_terminal_outcomes_use_failure_precedence(spine: Any) -> None:
    await _assert_failure_precedence(spine)


@pytest.mark.ac("ADR-082526-237d/AC-3")
async def test_mixed_terminal_outcomes_use_failure_precedence_in_memory(memory_spine: Any) -> None:
    await _assert_failure_precedence(memory_spine)


async def _assert_concurrent_last_two_converge(spine: Any) -> None:
    store, run, node_runs = await _running_nodes(spine, ("node-1", "node-2"))
    attempts = await asyncio.gather(
        _completed_attempt(store, node_runs[0], result={"node": 1}),
        _completed_attempt(store, node_runs[1], result={"node": 2}),
    )
    reconciler = AttemptLifecycleReconciler(store)
    outcomes = [
        AcceptedNodeOutcome(
            node_run_id=node_run.node_run_id,
            attempt_result=AttemptResult.from_attempt(attempt),
            logical_status=RunStatus.COMPLETED,
            result={"node": index},
        )
        for index, (node_run, attempt) in enumerate(zip(node_runs, attempts, strict=True), start=1)
    ]
    results = await asyncio.gather(
        *(reconciler.accept_outcome(outcome) for outcome in outcomes),
        return_exceptions=True,
    )
    assert not [result for result in results if isinstance(result, BaseException)]
    settled = await store.get_run(run.run_id)
    assert settled is not None and settled.status is RunStatus.COMPLETED


async def test_concurrent_last_two_node_runs_converge(spine: Any) -> None:
    await _assert_concurrent_last_two_converge(spine)


@pytest.mark.ac("ADR-082526-237d/AC-4")
async def test_concurrent_last_two_node_runs_converge_in_memory(memory_spine: Any) -> None:
    await _assert_concurrent_last_two_converge(memory_spine)


@pytest.mark.ac("ADR-082526-237d/AC-5")
async def test_replay_settles_run_after_crash_between_node_acceptance_and_parent_fold(
    spine: Any,
) -> None:
    """An already-accepted Attempt must repair a Run stranded before settlement."""
    store, run, (node_run,) = await _running_nodes(spine, ("node-1",))
    attempt = await _completed_attempt(store, node_run, result={"ok": True})
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
    stranded = await store.get_run(run.run_id)
    assert stranded is not None and stranded.status is RunStatus.RUNNING

    await AttemptLifecycleReconciler(store).reconcile(attempt)

    settled = await store.get_run(run.run_id)
    assert settled is not None
    assert settled.status is RunStatus.COMPLETED
    assert settled.result == {"ok": True}


@pytest.mark.ac("ADR-082526-237d/AC-5")
async def test_generic_reconciliation_does_not_settle_a_cyclic_graph(spine: Any) -> None:
    """Observed node ids are not frontier completion when a topology can revisit them."""
    store, workspace, project_id = spine
    graph = Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Cycle",
        nodes=[
            Node(node_id="a", node_type="agent"),
            Node(node_id="b", node_type="agent"),
        ],
        edges=[
            Edge(from_node="a", to_node="b"),
            Edge(from_node="b", to_node="a"),
        ],
    )
    run = await store.create_run(graph)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_runs = []
    for node_id in ("a", "b"):
        node_run = await store.create_node_run(run.run_id, node_id=node_id)
        await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
        node_runs.append(await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING))

    reconciler = AttemptLifecycleReconciler(store)
    for index, node_run in enumerate(node_runs):
        attempt = await _completed_attempt(store, node_run, result={"visit": index})
        await reconciler.reconcile(attempt)

    unsettled = await store.get_run(run.run_id)
    assert unsettled is not None
    assert unsettled.status is RunStatus.RUNNING
