"""Terminal replay cannot overwrite an independently cancelled logical node."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maistro.container import create_container
from maistro.graph import Graph, Node
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.store import RunIntegrityError
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.types.config import AgentConfig


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_terminal_replay_preserves_logical_cancellation(
    backend: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    database_url = (
        f"sqlite:///{tmp_path / 'replay-refusal.db'}" if backend == "sqlite" else "memory://"
    )
    container = await create_container(
        AgentConfig(router_api_key="test-key", database_url=database_url)
    )
    try:
        project = await container.project_scope_store.create_root("replay-refusal")
        graph = Graph(
            workspace_id="replay-refusal",
            project_id=project.project_id,
            name="terminal replay refusal",
            nodes=[
                Node(node_id="cancelled", node_type="test.replay"),
                Node(node_id="pending", node_type="test.replay"),
            ],
        )
        store = container.run_store
        run = await store.create_run(
            graph,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        run = await store.transition_run(run.run_id, RunStatus.RUNNING)
        node = await store.create_node_run(run.run_id, node_id="cancelled")
        await store.transition_node_run(node.node_run_id, RunStatus.QUEUED)
        await store.transition_node_run(node.node_run_id, RunStatus.RUNNING)
        attempt = await store.create_attempt(node.node_run_id)
        await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
        completed = await store.transition_attempt(
            attempt.attempt_id, AttemptStatus.COMPLETED, result={"physical": "complete"}
        )
        # A physical completion can precede an independent logical disposition.
        # Keep the Run active: its other Graph node has not been observed yet.
        cancelled = await store.transition_node_run(node.node_run_id, RunStatus.CANCELLED)

        # Establish a real reconciler refusal from persisted canonical state,
        # rather than replacing the store or mocking the error being handled.
        with pytest.raises(RunIntegrityError, match="requires a running logical NodeRun"):
            await AttemptLifecycleReconciler(store).reconcile(completed)

        with caplog.at_level(logging.WARNING, logger="maistro.container"):
            recovered = await container.recover_abandoned_attempts(now=datetime.now(UTC), limit=1)

        assert recovered == 0
        assert await store.get_run(run.run_id) == run
        assert await store.get_node_run(node.node_run_id) == cancelled
        assert await store.get_attempt(attempt.attempt_id) == completed
        warnings = [
            record
            for record in caplog.records
            if record.getMessage()
            == f"terminal Attempt {attempt.attempt_id} could not be reconciled"
        ]
        assert len(warnings) == 1
        assert warnings[0].exc_info is not None
        assert isinstance(warnings[0].exc_info[1], RunIntegrityError)
    finally:
        await container.aclose()
