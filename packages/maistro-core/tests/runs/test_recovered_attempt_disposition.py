"""P4a: apply_recovered_attempt_disposition parks NodeRun/Run atomically (#232).

Protocol + in-memory / SQLite / PostgreSQL. Reconciler wiring is P4b.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.runs.model import (
    Attempt,
    AttemptStatus,
    CancellationCause,
    RunStatus,
)
from maistro.runs.recovered_disposition import (
    RecoveredDispositionRefused,
    is_typed_recovered_attempt,
    plan_recovered_attempt_disposition,
)
from maistro.runs.store import AttemptNotFound
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


def _graph(workspace: str, project_id: str, *, nodes: list[str] | None = None) -> Graph:
    ids = nodes or ["node-1"]
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="recovered disposition",
        nodes=[Node(node_id=node_id, node_type="agent") for node_id in ids],
    )


async def _running_recovered(
    spine: Any,
    *,
    nodes: list[str] | None = None,
    holder: str = "worker-A",
    ttl: timedelta = timedelta(seconds=30),
) -> tuple[Any, Attempt, Any, Any]:
    """Admit a RUNNING NodeRun whose Attempt is already CANCELLED+RECOVERED."""
    store, workspace, project_id = spine
    run = await store.create_run(
        _graph(workspace, project_id, nodes=nodes),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id=(nodes or ["node-1"])[0])
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder=holder, lease_ttl=ttl)
    assert attempt.execution_lease is not None
    running = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    lease = running.execution_lease
    assert lease is not None and lease.expires_at is not None
    after = lease.expires_at + timedelta(seconds=1)
    reclaimed = await store.reclaim_expired_attempt(running.attempt_id, now=after)
    assert reclaimed is not None
    assert is_typed_recovered_attempt(reclaimed)
    return store, reclaimed, node_run, run


async def _assert_parks_node_and_run(spine: Any) -> None:
    store, attempt, _node_run, _run = await _running_recovered(spine)

    parked_node, parked_run = await store.apply_recovered_attempt_disposition(attempt.attempt_id)

    assert parked_node.status is RunStatus.WAITING
    assert parked_run.status is RunStatus.WAITING
    assert parked_node.error == attempt.error

    again_node, again_run = await store.apply_recovered_attempt_disposition(attempt.attempt_id)
    assert again_node.status is RunStatus.WAITING
    assert again_run.status is RunStatus.WAITING
    assert again_node.node_run_id == parked_node.node_run_id


async def _assert_parent_only_when_already_waiting(spine: Any) -> None:
    store, attempt, node_run, run = await _running_recovered(spine)
    await store.transition_node_run(node_run.node_run_id, RunStatus.WAITING)

    parked_node, parked_run = await store.apply_recovered_attempt_disposition(attempt.attempt_id)

    assert parked_node.status is RunStatus.WAITING
    assert parked_node.node_run_id == node_run.node_run_id
    assert parked_run.status is RunStatus.WAITING
    assert parked_run.run_id == run.run_id


async def _assert_active_sibling_keeps_parent_running(spine: Any) -> None:
    store, attempt, _node_run, run = await _running_recovered(spine, nodes=["node-1", "node-2"])
    sibling = await store.create_node_run(run.run_id, node_id="node-2")
    await store.transition_node_run(sibling.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(sibling.node_run_id, RunStatus.RUNNING)

    parked_node, parked_run = await store.apply_recovered_attempt_disposition(attempt.attempt_id)

    assert parked_node.status is RunStatus.WAITING
    assert parked_run.status is RunStatus.RUNNING


async def _assert_higher_ordinal_preserves(spine: Any) -> None:
    store, attempt, node_run, _run = await _running_recovered(spine)
    # A fresh Attempt under the same NodeRun supersedes the recovered row.
    # NodeRun must leave WAITING/terminal — keep RUNNING so create_attempt works.
    retry = await store.create_attempt(node_run.node_run_id)

    parked_node, parked_run = await store.apply_recovered_attempt_disposition(attempt.attempt_id)

    assert parked_node.status is RunStatus.RUNNING
    assert parked_run.status is RunStatus.RUNNING
    assert retry.status is AttemptStatus.CREATED


async def _assert_superseded_node_run_preserves(spine: Any) -> None:
    store, attempt, node_run, run = await _running_recovered(spine)
    newer = await store.create_node_run(run.run_id, node_id=node_run.node_id)
    assert newer.ordinal > node_run.ordinal

    parked_node, parked_run = await store.apply_recovered_attempt_disposition(attempt.attempt_id)

    assert parked_node.status is RunStatus.RUNNING
    assert parked_node.node_run_id == node_run.node_run_id
    assert parked_run.status is RunStatus.RUNNING


async def _assert_paused_preserves(spine: Any) -> None:
    store, attempt, node_run, _run = await _running_recovered(spine)
    await store.transition_node_run(node_run.node_run_id, RunStatus.PAUSED)

    parked_node, parked_run = await store.apply_recovered_attempt_disposition(attempt.attempt_id)

    assert parked_node.status is RunStatus.PAUSED
    assert parked_run.status is RunStatus.RUNNING


async def _assert_terminal_node_preserves(spine: Any) -> None:
    store, attempt, node_run, _run = await _running_recovered(spine)
    await store.transition_node_run(node_run.node_run_id, RunStatus.FAILED, error="already failed")

    parked_node, parked_run = await store.apply_recovered_attempt_disposition(attempt.attempt_id)

    assert parked_node.status is RunStatus.FAILED
    assert parked_run.status is RunStatus.RUNNING


async def _assert_unknown_cause_refuses(spine: Any) -> None:
    store, workspace, project_id = spine
    run = await store.create_run(
        _graph(workspace, project_id),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(node_run.node_run_id)
    cancelled = await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.CANCELLED, error="user cancelled"
    )
    assert cancelled.cancellation_cause is None

    with pytest.raises(RecoveredDispositionRefused):
        await store.apply_recovered_attempt_disposition(cancelled.attempt_id)

    still = await store.get_attempt(cancelled.attempt_id)
    assert still is not None and still.cancellation_cause is None
    still_node = await store.get_node_run(node_run.node_run_id)
    assert still_node is not None and still_node.status is RunStatus.RUNNING


async def _assert_missing_raises(spine: Any) -> None:
    store, _workspace, _project_id = spine
    with pytest.raises(AttemptNotFound):
        await store.apply_recovered_attempt_disposition("no-such-attempt")


async def _assert_unleased_created_sibling_blocks_parent(spine: Any) -> None:
    """Active physical work includes unleased CREATED Attempts (#232 D)."""
    store, attempt, node_run, run = await _running_recovered(spine, nodes=["node-1", "node-2"])
    sibling = await store.create_node_run(run.run_id, node_id="node-2")
    await store.transition_node_run(sibling.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(sibling.node_run_id, RunStatus.RUNNING)
    # Park the recovered node first would still see the sibling Attempt as active.
    await store.create_attempt(sibling.node_run_id)  # CREATED, no lease

    parked_node, parked_run = await store.apply_recovered_attempt_disposition(attempt.attempt_id)

    assert parked_node.status is RunStatus.WAITING
    assert parked_run.status is RunStatus.RUNNING
    assert node_run.node_run_id == parked_node.node_run_id


# --- spine (memory / sqlite / postgres) -------------------------------------#


async def test_parks_node_and_run(spine: Any) -> None:
    await _assert_parks_node_and_run(spine)


async def test_parent_only_when_already_waiting(spine: Any) -> None:
    await _assert_parent_only_when_already_waiting(spine)


async def test_active_sibling_keeps_parent_running(spine: Any) -> None:
    await _assert_active_sibling_keeps_parent_running(spine)


async def test_higher_ordinal_preserves(spine: Any) -> None:
    await _assert_higher_ordinal_preserves(spine)


async def test_superseded_node_run_preserves(spine: Any) -> None:
    await _assert_superseded_node_run_preserves(spine)


async def test_paused_preserves(spine: Any) -> None:
    await _assert_paused_preserves(spine)


async def test_terminal_node_preserves(spine: Any) -> None:
    await _assert_terminal_node_preserves(spine)


async def test_unknown_cause_refuses(spine: Any) -> None:
    await _assert_unknown_cause_refuses(spine)


async def test_missing_raises_attempt_not_found(spine: Any) -> None:
    await _assert_missing_raises(spine)


async def test_unleased_created_sibling_blocks_parent(spine: Any) -> None:
    await _assert_unleased_created_sibling_blocks_parent(spine)


# --- memory-only: REQUESTED cause + CREATED NodeRun refusal -----------------#


async def test_requested_cause_refuses(memory_spine: Any) -> None:
    store, attempt, _node_run, _run = await _running_recovered(memory_spine)
    # Inject REQUESTED without going through a writer that is still P3c-scoped.
    requested = attempt.model_copy(update={"cancellation_cause": CancellationCause.REQUESTED})
    store._attempts[attempt.attempt_id] = requested

    with pytest.raises(RecoveredDispositionRefused):
        await store.apply_recovered_attempt_disposition(attempt.attempt_id)


async def test_created_node_run_refuses(memory_spine: Any) -> None:
    store, workspace, project_id = memory_spine
    run = await store.create_run(
        _graph(workspace, project_id),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    # CREATED NodeRun + RECOVERED Attempt is the D.1 prelaunch leaf — refuse.
    attempt = await store.create_attempt(
        node_run.node_run_id, lease_holder="worker-A", lease_ttl=timedelta(seconds=1)
    )
    assert attempt.execution_lease is not None
    after = attempt.execution_lease.expires_at + timedelta(seconds=1)  # type: ignore[operator]
    reclaimed = await store.reclaim_expired_attempt(attempt.attempt_id, now=after)
    assert reclaimed is not None

    with pytest.raises(RecoveredDispositionRefused):
        await store.apply_recovered_attempt_disposition(reclaimed.attempt_id)

    still = await store.get_node_run(node_run.node_run_id)
    assert still is not None and still.status is RunStatus.CREATED


def test_planner_refuses_lineage_mismatch() -> None:
    from datetime import UTC, datetime

    from maistro.runs.model import GraphSnapshot, NodeRun, Run

    graph = Graph(
        workspace_id="w",
        project_id="p",
        name="g",
        nodes=[Node(node_id="n1", node_type="agent")],
    )
    run = Run(
        workspace_id="w",
        project_id="p",
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.RUNNING,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    node_run = NodeRun(run_id=run.run_id, node_id="n1", ordinal=1, status=RunStatus.RUNNING)
    other = NodeRun(run_id=run.run_id, node_id="n1", ordinal=1, status=RunStatus.RUNNING)
    attempt = Attempt(
        node_run_id=other.node_run_id,
        ordinal=1,
        status=AttemptStatus.CANCELLED,
        finished_at=datetime.now(UTC),
        cancellation_cause=CancellationCause.RECOVERED,
        error="lease expired; holder 'x' stopped renewing before the Attempt finished",
    )
    with pytest.raises(RecoveredDispositionRefused):
        plan_recovered_attempt_disposition(
            attempt=attempt,
            run=run,
            node_run=node_run,
            all_node_runs=[node_run],
            attempts_by_node_run={node_run.node_run_id: [attempt]},
        )


async def test_sqlite_cancelled_error_rolls_back_open_transaction(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CancelledError must not leave BEGIN IMMEDIATE open on the shared conn."""
    import aiosqlite

    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs.sqlite_store import SqliteRunStore

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-cancel")
    project = await projects.create(
        workspace_id="ws-cancel", parent_project_id=root.project_id, name="c"
    )
    conn = await aiosqlite.connect(tmp_path / "disposition.db")
    store = SqliteRunStore(conn, project_store=projects)
    await store.ensure_schema()
    try:
        spine = (store, "ws-cancel", project.project_id)
        store_inner, attempt, _node, _run = await _running_recovered(spine)

        real_require = store_inner._require_attempt

        async def _cancel_after_begin(attempt_id: str) -> Any:
            raise asyncio.CancelledError()

        monkeypatch.setattr(store_inner, "_require_attempt", _cancel_after_begin)

        with pytest.raises(asyncio.CancelledError):
            await store_inner.apply_recovered_attempt_disposition(attempt.attempt_id)

        monkeypatch.setattr(store_inner, "_require_attempt", real_require)
        # A later writer must be able to BEGIN IMMEDIATE again — proof the
        # cancelled disposition rolled back rather than leaving a nested txn.
        parked_node, parked_run = await store_inner.apply_recovered_attempt_disposition(
            attempt.attempt_id
        )
        assert parked_node.status is RunStatus.WAITING
        assert parked_run.status is RunStatus.WAITING
    finally:
        await conn.close()
