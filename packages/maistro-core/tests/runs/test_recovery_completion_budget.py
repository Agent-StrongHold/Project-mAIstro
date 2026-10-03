"""Actual persisted progress, not replay success, spends the repair budget (#1850)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from maistro.container import Container, create_container
from maistro.graph import Edge, Graph, Node
from maistro.runs.model import (
    AcceptedNodeOutcome,
    Attempt,
    AttemptResult,
    AttemptStatus,
    NodeRun,
    RunStatus,
)
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.store import RunIntegrityError, RunStore
from maistro.types.config import AgentConfig


@pytest.fixture
async def recovery_container(spine: Any) -> Any:
    store, workspace, project_id = spine
    container = await create_container(
        AgentConfig(router_api_key="test-key", database_url="memory://")
    )
    container.run_store = store
    try:
        yield container, workspace, project_id
    finally:
        await container.aclose()


async def _completed_pair(
    container: Container, workspace: str, project_id: str, *, missing_node: bool = False
) -> tuple[str, list[NodeRun], list[Attempt]]:
    store = container.run_store
    graph = Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="completion budget",
        nodes=[Node(node_id="a", node_type="test"), Node(node_id="b", node_type="test")]
        + ([Node(node_id="unobserved", node_type="test")] if missing_node else []),
        edges=[Edge(from_node="a", to_node="b")],
    )
    run = await store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id="test:recovery-budget"
    )
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    nodes, attempts = [], []
    for node_id in ("a", "b"):
        node = await store.create_node_run(run.run_id, node_id=node_id)
        await store.transition_node_run(node.node_run_id, RunStatus.QUEUED)
        node = await store.transition_node_run(node.node_run_id, RunStatus.RUNNING)
        attempt = await store.create_attempt(node.node_run_id)
        await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
        attempt = await store.transition_attempt(
            attempt.attempt_id, AttemptStatus.COMPLETED, result={"node": node_id}
        )
        nodes.append(node)
        attempts.append(attempt)
    await AttemptLifecycleReconciler(store).reconcile(attempts[0])
    return run.run_id, nodes, attempts


async def _assert_evidence(store: RunStore, nodes: list[NodeRun], attempts: list[Attempt]) -> None:
    assert {n.node_run_id for n in await store.list_node_runs(nodes[0].run_id)} == {
        n.node_run_id for n in nodes
    }
    for node, attempt in zip(nodes, attempts, strict=True):
        assert await store.list_attempts(node.node_run_id) == [attempt]


async def test_accepted_prefix_does_not_starve_unreconciled_completion(
    recovery_container: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    container, workspace, project_id = recovery_container
    store = container.run_store
    run_id, nodes, attempts = await _completed_pair(container, workspace, project_id)
    accepted_a = await store.get_node_run(nodes[0].node_run_id)
    # Recovery must consume persisted facts, never create physical work.
    for name in ("create_attempt", "create_node_run"):
        monkeypatch.setattr(
            store, name, AsyncMock(side_effect=AssertionError("unexpected creation"))
        )
    monkeypatch.setattr(
        container.invocation_store,
        "create",
        AsyncMock(side_effect=AssertionError("unexpected invocation")),
    )
    assert await container.recover_abandoned_attempts(limit=1) == 1
    repaired_b = await store.get_node_run(nodes[1].node_run_id)
    assert repaired_b.accepted_outcome is not None
    assert repaired_b.status is RunStatus.COMPLETED
    assert (await store.get_run(run_id)).status is RunStatus.COMPLETED
    assert await store.get_node_run(nodes[0].node_run_id) == accepted_a
    await _assert_evidence(store, nodes, attempts)
    settled = await store.get_run(run_id)
    assert await container.recover_abandoned_attempts(limit=1) == 0
    assert await store.get_run(run_id) == settled
    assert await store.get_node_run(nodes[1].node_run_id) == repaired_b
    await _assert_evidence(store, nodes, attempts)


async def _accept_without_settlement(store: RunStore, attempt: Attempt) -> None:
    outcome = AcceptedNodeOutcome(
        node_run_id=attempt.node_run_id,
        attempt_result=AttemptResult.from_attempt(attempt),
        logical_status=RunStatus.COMPLETED,
        result=attempt.result,
    )
    await store.transition_node_run(
        attempt.node_run_id,
        RunStatus.COMPLETED,
        result=attempt.result,
        accepted_outcome=outcome,
    )


async def test_parent_only_settlement_counts_once(recovery_container: Any) -> None:
    container, workspace, project_id = recovery_container
    run_id, nodes, attempts = await _completed_pair(container, workspace, project_id)
    await _accept_without_settlement(container.run_store, attempts[1])
    before_nodes = await container.run_store.list_node_runs(run_id)
    assert await container.recover_abandoned_attempts(limit=1) == 1
    assert (await container.run_store.get_run(run_id)).status is RunStatus.COMPLETED
    assert await container.run_store.list_node_runs(run_id) == before_nodes
    assert await container.recover_abandoned_attempts(limit=1) == 0
    await _assert_evidence(container.run_store, nodes, attempts)


async def test_no_op_page_does_not_spend_repair_budget(
    recovery_container: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maistro.runs.store import run_cursor_key

    container, workspace, project_id = recovery_container
    store = container.run_store
    prefix_id, _, prefix_attempts = await _completed_pair(
        container, workspace, project_id, missing_node=True
    )
    await AttemptLifecycleReconciler(store).reconcile(prefix_attempts[1])
    prefix = await store.get_run(prefix_id)
    run_id, _, _ = await _completed_pair(container, workspace, project_id)
    page_reads = AsyncMock(wraps=store.list_by_status)
    monkeypatch.setattr(store, "list_by_status", page_reads)
    assert await container.recover_abandoned_attempts(limit=1) == 1
    assert (await store.get_run(run_id)).status is RunStatus.COMPLETED
    assert await store.get_run(prefix_id) == prefix
    assert [call.kwargs for call in page_reads.await_args_list] == [
        {"limit": 1, "after": None},
        {"limit": 1, "after": run_cursor_key(prefix)},
    ]
    assert await container.recover_abandoned_attempts(limit=1) == 0
    assert await store.get_run(prefix_id) == prefix


@pytest.mark.parametrize("peer_progress", ["acceptance", "settlement"])
async def test_concurrent_progress_then_unchanged_replay(
    recovery_container: Any, monkeypatch: pytest.MonkeyPatch, peer_progress: str
) -> None:
    container, workspace, project_id = recovery_container
    store = container.run_store
    run_id, nodes, attempts = await _completed_pair(
        container, workspace, project_id, missing_node=peer_progress == "acceptance"
    )
    target = attempts[1]
    if peer_progress == "settlement":
        await _accept_without_settlement(store, attempts[1])
        target = attempts[0]
    original = AttemptLifecycleReconciler.reconcile
    interleavings = 0

    async def peer_first(
        self: AttemptLifecycleReconciler, attempt: Attempt, **kwargs: Any
    ) -> NodeRun:
        nonlocal interleavings
        if attempt.attempt_id == target.attempt_id and interleavings == 0:
            interleavings += 1
            # Another replica finishes after the Container's before-read but
            # before its own reconcile. Both calls use canonical persisted facts.
            await original(AttemptLifecycleReconciler(store), attempt)
        return await original(self, attempt, **kwargs)

    monkeypatch.setattr(AttemptLifecycleReconciler, "reconcile", peer_first)
    assert await container.recover_abandoned_attempts(limit=1) == 1
    assert interleavings == 1
    snapshot = await store.get_run(run_id)
    before_nodes = await store.list_node_runs(run_id)
    assert await container.recover_abandoned_attempts(limit=1) == 0
    assert await store.get_run(run_id) == snapshot
    assert await store.list_node_runs(run_id) == before_nodes
    await _assert_evidence(store, nodes, attempts)


@pytest.mark.parametrize("read_phase", ["before", "after"])
async def test_progress_read_storage_failure_propagates(
    recovery_container: Any, monkeypatch: pytest.MonkeyPatch, read_phase: str
) -> None:
    container, workspace, project_id = recovery_container
    await _completed_pair(container, workspace, project_id)
    original = AttemptLifecycleReconciler.reconcile

    async def fail_after(
        self: AttemptLifecycleReconciler, attempt: Attempt, **kwargs: Any
    ) -> NodeRun:
        result = await original(self, attempt, **kwargs)
        monkeypatch.setattr(
            container.run_store, "get_run", AsyncMock(side_effect=OSError("storage unavailable"))
        )
        return result

    if read_phase == "after":
        monkeypatch.setattr(AttemptLifecycleReconciler, "reconcile", fail_after)
    else:
        monkeypatch.setattr(
            container.run_store, "get_run", AsyncMock(side_effect=OSError("storage unavailable"))
        )
    with pytest.raises(OSError, match="storage unavailable"):
        await container.recover_abandoned_attempts(limit=1)


@pytest.mark.parametrize("missing", ["get_node_run", "get_run"])
async def test_missing_progress_record_is_integrity_refusal(
    recovery_container: Any, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    container, workspace, project_id = recovery_container
    _, _, attempts = await _completed_pair(container, workspace, project_id)
    monkeypatch.setattr(container.run_store, missing, AsyncMock(return_value=None))
    with pytest.raises(RunIntegrityError, match="terminal replay is missing"):
        await container._reconcile_terminal_attempt_progress(
            attempts[0], AttemptLifecycleReconciler(container.run_store)
        )


async def test_sqlite_reopen_recovers_later_completion(tmp_path: Any) -> None:
    config = AgentConfig(
        router_api_key="test-key", database_url=f"sqlite:///{tmp_path / 'runs.db'}"
    )
    first = await create_container(config)
    try:
        project = await first.project_scope_store.create_root("recovery-restart")
        run_id, nodes, attempts = await _completed_pair(
            first, "recovery-restart", project.project_id
        )
        accepted_a = await first.run_store.get_node_run(nodes[0].node_run_id)
    finally:
        await first.aclose()
    restarted = await create_container(config)
    try:
        assert await restarted.recover_abandoned_attempts(limit=1) == 1
        assert (await restarted.run_store.get_run(run_id)).status is RunStatus.COMPLETED
        assert await restarted.run_store.get_node_run(nodes[0].node_run_id) == accepted_a
        await _assert_evidence(restarted.run_store, nodes, attempts)
        assert await restarted.recover_abandoned_attempts(limit=1) == 0
        await _assert_evidence(restarted.run_store, nodes, attempts)
    finally:
        await restarted.aclose()
