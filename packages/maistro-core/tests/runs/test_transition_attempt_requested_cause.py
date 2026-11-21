"""P3c: transition_attempt may stamp REQUESTED (not RECOVERED) on CANCELLED (#2421)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.runs.lifecycle import InvalidLifecycleTransition, transition_attempt
from maistro.runs.model import Attempt, AttemptStatus, CancellationCause, ExecutionLease
from maistro.runs.store import InMemoryRunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


def _t(offset_s: int = 0) -> datetime:
    return datetime(2026, 11, 20, 3, 0, 0, tzinfo=UTC) + timedelta(seconds=offset_s)


def _created(*, with_lease: bool = False) -> Attempt:
    attempt = Attempt(node_run_id="nr-1", ordinal=1, created_at=_t(0))
    if not with_lease:
        return attempt
    values = attempt.model_dump(mode="python")
    values["execution_lease"] = ExecutionLease(
        node_run_id=attempt.node_run_id,
        attempt_id=attempt.attempt_id,
        lease_epoch=1,
        holder="worker-1",
        issued_at=_t(0),
        expires_at=_t(30),
    )
    return Attempt.model_validate(values)


class TestTransitionAttemptRequestedCause:
    def test_cancelled_with_requested_stamps_cause(self) -> None:
        settled = transition_attempt(
            _created(),
            AttemptStatus.CANCELLED,
            at=_t(2),
            error="auth refused",
            cancellation_cause=CancellationCause.REQUESTED,
        )

        assert settled.status is AttemptStatus.CANCELLED
        assert settled.cancellation_cause is CancellationCause.REQUESTED
        assert settled.finished_at == _t(2)
        assert settled.error == "auth refused"

    def test_cancelled_without_cause_leaves_cause_unset(self) -> None:
        settled = transition_attempt(_created(), AttemptStatus.CANCELLED, at=_t(2))

        assert settled.status is AttemptStatus.CANCELLED
        assert settled.cancellation_cause is None

    def test_recovered_is_refused(self) -> None:
        with pytest.raises(InvalidLifecycleTransition, match="RECOVERED"):
            transition_attempt(
                _created(),
                AttemptStatus.CANCELLED,
                at=_t(2),
                cancellation_cause=CancellationCause.RECOVERED,
            )

    def test_requested_on_non_cancelled_is_refused(self) -> None:
        with pytest.raises(InvalidLifecycleTransition, match="CANCELLED"):
            transition_attempt(
                _created(),
                AttemptStatus.RUNNING,
                at=_t(1),
                cancellation_cause=CancellationCause.REQUESTED,
            )


async def _spine_store() -> tuple[InMemoryRunStore, str]:
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs.model import RunStatus

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-p3c")
    project = await projects.create(
        workspace_id="ws-p3c", parent_project_id=root.project_id, name="P3c"
    )
    store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="ws-p3c",
        project_id=project.project_id,
        name="p3c",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    return store, node_run.node_run_id


class TestTransitionAttemptRequestedStore:
    async def test_store_persists_requested_on_cancel(self) -> None:
        store, node_run_id = await _spine_store()
        attempt = await store.create_attempt(node_run_id)

        settled = await store.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.CANCELLED,
            error="auth refused",
            cancellation_cause=CancellationCause.REQUESTED,
        )

        assert settled.cancellation_cause is CancellationCause.REQUESTED
        reopened = await store.get_attempt(attempt.attempt_id)
        assert reopened is not None
        assert reopened.cancellation_cause is CancellationCause.REQUESTED
        assert reopened.error == "auth refused"

    async def test_store_refuses_recovered(self) -> None:
        store, node_run_id = await _spine_store()
        attempt = await store.create_attempt(node_run_id)

        with pytest.raises(InvalidLifecycleTransition, match="RECOVERED"):
            await store.transition_attempt(
                attempt.attempt_id,
                AttemptStatus.CANCELLED,
                cancellation_cause=CancellationCause.RECOVERED,
            )

        reopened = await store.get_attempt(attempt.attempt_id)
        assert reopened is not None
        assert reopened.status is AttemptStatus.CREATED
        assert reopened.cancellation_cause is None
