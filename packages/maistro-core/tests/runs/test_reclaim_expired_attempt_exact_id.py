"""P2b: exact-ID store reclaim persists CANCELLED+RECOVERED under lock (#2358 / #232).

Protocol + in-memory / SQLite / PostgreSQL. Graph ``execution_store`` is P3a.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.runs.model import AttemptStatus, CancellationCause, RunStatus
from maistro.runs.store import AttemptNotFound
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


def _graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="exact reclaim",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


async def _leased_running_attempt(
    spine: Any, *, holder: str = "worker-A", ttl: timedelta
) -> tuple[Any, Any]:
    store, workspace, project_id = spine
    run = await store.create_run(
        _graph(workspace, project_id), actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder=holder, lease_ttl=ttl)
    assert attempt.execution_lease is not None
    running = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    return store, running


async def _assert_exact_id_reclaim_persists_recovered(spine: Any) -> None:
    store, attempt = await _leased_running_attempt(spine, ttl=timedelta(seconds=30))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    after = lease.expires_at + timedelta(seconds=1)

    written = await store.reclaim_expired_attempt(attempt.attempt_id, now=after)

    assert written is not None
    assert written.attempt_id == attempt.attempt_id
    assert written.status is AttemptStatus.CANCELLED
    assert written.cancellation_cause is CancellationCause.RECOVERED
    assert written.finished_at == after
    assert written.error is not None and "worker-A" in written.error

    reopened = await store.get_attempt(attempt.attempt_id)
    assert reopened is not None
    assert reopened.status is AttemptStatus.CANCELLED
    assert reopened.cancellation_cause is CancellationCause.RECOVERED
    assert reopened.model_dump(mode="json")["cancellation_cause"] == "recovered"


async def _assert_live_lease_returns_none(spine: Any) -> None:
    store, attempt = await _leased_running_attempt(spine, ttl=timedelta(minutes=5))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None

    assert (
        await store.reclaim_expired_attempt(
            attempt.attempt_id, now=lease.expires_at - timedelta(seconds=1)
        )
        is None
    )
    still = await store.get_attempt(attempt.attempt_id)
    assert still is not None and still.status is AttemptStatus.RUNNING
    assert still.cancellation_cause is None


async def _assert_already_reclaimed_is_idempotent(spine: Any) -> None:
    store, attempt = await _leased_running_attempt(spine, ttl=timedelta(seconds=30))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    after = lease.expires_at + timedelta(seconds=1)

    first = await store.reclaim_expired_attempt(attempt.attempt_id, now=after)
    second = await store.reclaim_expired_attempt(attempt.attempt_id, now=after + timedelta(hours=1))

    assert first is not None
    assert first.cancellation_cause is CancellationCause.RECOVERED
    assert second is None
    again = await store.get_attempt(attempt.attempt_id)
    assert again is not None
    assert again.cancellation_cause is CancellationCause.RECOVERED


async def _assert_requested_terminal_is_not_rewritten(spine: Any) -> None:
    store, attempt = await _leased_running_attempt(spine, ttl=timedelta(seconds=30))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    cancelled = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.CANCELLED,
        fencing_token=lease.fencing_token,
        error="user cancelled",
    )
    assert cancelled.cancellation_cause is None

    assert (
        await store.reclaim_expired_attempt(
            attempt.attempt_id, now=lease.expires_at + timedelta(days=1)
        )
        is None
    )
    still = await store.get_attempt(attempt.attempt_id)
    assert still is not None
    assert still.status is AttemptStatus.CANCELLED
    assert still.cancellation_cause is None
    assert still.error == "user cancelled"


async def _assert_batch_persists_recovered_and_returns_only_new(spine: Any) -> None:
    store, attempt = await _leased_running_attempt(spine, ttl=timedelta(seconds=30))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    after = lease.expires_at + timedelta(seconds=1)

    first = await store.reclaim_expired_attempts(now=after)
    second = await store.reclaim_expired_attempts(now=after + timedelta(hours=1))

    assert [item.attempt_id for item in first] == [attempt.attempt_id]
    assert first[0].cancellation_cause is CancellationCause.RECOVERED
    assert second == []
    reopened = await store.get_attempt(attempt.attempt_id)
    assert reopened is not None
    assert reopened.cancellation_cause is CancellationCause.RECOVERED


async def _assert_missing_raises(spine: Any) -> None:
    store, _workspace, _project_id = spine
    with pytest.raises(AttemptNotFound):
        await store.reclaim_expired_attempt("no-such-attempt")


async def test_exact_id_reclaim_persists_recovered(spine: Any) -> None:
    await _assert_exact_id_reclaim_persists_recovered(spine)


async def test_exact_id_live_lease_returns_none(spine: Any) -> None:
    await _assert_live_lease_returns_none(spine)


async def test_exact_id_already_reclaimed_returns_none(spine: Any) -> None:
    await _assert_already_reclaimed_is_idempotent(spine)


async def test_exact_id_requested_terminal_is_not_rewritten(spine: Any) -> None:
    await _assert_requested_terminal_is_not_rewritten(spine)


async def test_batch_reclaim_persists_recovered_cause(spine: Any) -> None:
    await _assert_batch_persists_recovered_and_returns_only_new(spine)


async def test_exact_id_missing_raises_attempt_not_found(spine: Any) -> None:
    await _assert_missing_raises(spine)


async def test_exact_id_reclaim_persists_recovered_in_memory(memory_spine: Any) -> None:
    await _assert_exact_id_reclaim_persists_recovered(memory_spine)


async def test_exact_id_live_lease_returns_none_in_memory(memory_spine: Any) -> None:
    await _assert_live_lease_returns_none(memory_spine)


async def test_exact_id_already_reclaimed_returns_none_in_memory(memory_spine: Any) -> None:
    await _assert_already_reclaimed_is_idempotent(memory_spine)


async def test_exact_id_requested_terminal_is_not_rewritten_in_memory(memory_spine: Any) -> None:
    await _assert_requested_terminal_is_not_rewritten(memory_spine)


async def test_batch_reclaim_persists_recovered_cause_in_memory(memory_spine: Any) -> None:
    await _assert_batch_persists_recovered_and_returns_only_new(memory_spine)


async def test_exact_id_missing_raises_attempt_not_found_in_memory(memory_spine: Any) -> None:
    await _assert_missing_raises(memory_spine)
