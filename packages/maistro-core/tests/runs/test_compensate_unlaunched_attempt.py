"""P2d: compensate_unlaunched_attempt is the CREATED prelaunch RECOVERED writer (#2369)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.runs.lifecycle import (
    InvalidLifecycleTransition,
    compensate_unlaunched_attempt,
    transition_attempt,
)
from maistro.runs.model import Attempt, AttemptStatus, CancellationCause, ExecutionLease
from maistro.runs.store import AttemptNotFound, InMemoryRunStore, StaleExecutionFence
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


def _t(offset_s: int = 0) -> datetime:
    return datetime(2026, 10, 26, 6, 0, 0, tzinfo=UTC) + timedelta(seconds=offset_s)


def _created(
    *, started_at: datetime | None = None, cause: CancellationCause | None = None
) -> Attempt:
    created = Attempt(node_run_id="nr-1", ordinal=1, created_at=_t(0))
    values = created.model_dump(mode="python")
    values["execution_lease"] = ExecutionLease(
        node_run_id=created.node_run_id,
        attempt_id=created.attempt_id,
        lease_epoch=1,
        holder="worker-1",
        issued_at=_t(0),
        expires_at=_t(30),
    )
    if started_at is not None:
        values["started_at"] = started_at
    if cause is not None:
        values["status"] = AttemptStatus.CANCELLED
        values["finished_at"] = _t(1)
        values["cancellation_cause"] = cause
        values["error"] = "prior"
    return Attempt.model_validate(values)


class TestCompensateConstruction:
    def test_created_unstarted_commits_cancelled_recovered(self) -> None:
        created = _created()
        settled = compensate_unlaunched_attempt(created, at=_t(2), error="setup failed")

        assert settled.status is AttemptStatus.CANCELLED
        assert settled.cancellation_cause is CancellationCause.RECOVERED
        assert settled.finished_at == _t(2)
        assert settled.error == "setup failed"
        assert settled.started_at is None

    def test_running_is_refused(self) -> None:
        running = transition_attempt(_created(), AttemptStatus.RUNNING, at=_t(1))
        with pytest.raises(InvalidLifecycleTransition, match="CREATED"):
            compensate_unlaunched_attempt(running, at=_t(2))

    def test_started_at_set_is_refused(self) -> None:
        with pytest.raises(InvalidLifecycleTransition, match="started"):
            compensate_unlaunched_attempt(_created(started_at=_t(1)), at=_t(2))

    def test_already_cancelled_with_cause_is_refused(self) -> None:
        """A terminal race winner is refused; cause rewrite is impossible here."""
        with pytest.raises(InvalidLifecycleTransition, match="CREATED"):
            compensate_unlaunched_attempt(_created(cause=CancellationCause.REQUESTED), at=_t(2))


async def _spine_store() -> tuple[InMemoryRunStore, str]:
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs.model import RunStatus

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-p2d")
    project = await projects.create(
        workspace_id="ws-p2d", parent_project_id=root.project_id, name="P2d"
    )
    store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="ws-p2d",
        project_id=project.project_id,
        name="p2d",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    return store, node_run.node_run_id


class TestCompensateStore:
    async def test_store_persists_recovered_under_matching_fence(self) -> None:
        store, node_run_id = await _spine_store()
        attempt = await store.create_attempt(
            node_run_id,
            lease_holder="worker-1",
            lease_ttl=timedelta(seconds=30),
        )
        assert attempt.execution_lease is not None

        settled = await store.compensate_unlaunched_attempt(
            attempt.attempt_id,
            fencing_token=attempt.execution_lease.fencing_token,
            error="launch boom",
        )

        assert settled.cancellation_cause is CancellationCause.RECOVERED
        reopened = await store.get_attempt(attempt.attempt_id)
        assert reopened is not None
        assert reopened.cancellation_cause is CancellationCause.RECOVERED
        assert reopened.error == "launch boom"

    async def test_stale_fence_is_refused(self) -> None:
        store, node_run_id = await _spine_store()
        attempt = await store.create_attempt(
            node_run_id,
            lease_holder="worker-1",
            lease_ttl=timedelta(seconds=30),
        )
        with pytest.raises(StaleExecutionFence):
            await store.compensate_unlaunched_attempt(
                attempt.attempt_id, fencing_token="not-the-token", error="x"
            )

    async def test_running_winner_is_refused(self) -> None:
        store, node_run_id = await _spine_store()
        attempt = await store.create_attempt(
            node_run_id,
            lease_holder="worker-1",
            lease_ttl=timedelta(seconds=30),
        )
        assert attempt.execution_lease is not None
        await store.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.RUNNING,
            fencing_token=attempt.execution_lease.fencing_token,
        )
        with pytest.raises(InvalidLifecycleTransition, match="CREATED"):
            await store.compensate_unlaunched_attempt(
                attempt.attempt_id,
                fencing_token=attempt.execution_lease.fencing_token,
                error="late",
            )

    async def test_missing_raises(self) -> None:
        store, _node_run_id = await _spine_store()
        with pytest.raises(AttemptNotFound):
            await store.compensate_unlaunched_attempt("missing", fencing_token="tok", error="x")
