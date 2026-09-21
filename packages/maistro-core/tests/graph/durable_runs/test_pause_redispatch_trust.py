"""Safety invariants for durable Graph pause redispatch."""

from datetime import UTC, datetime, timedelta

from maistro.graph import Graph, GraphExecutionState, Node
from maistro.graph.durable_runs import DurableRunRecord, RunStatus, attempt_executor
from maistro.graph.nodes import NodeResult
from maistro.graph.nodes.base import (
    PAUSE_AWAITING_REMOTE_DELEGATION,
    PAUSE_WAITING_ON_JIRA_SUBTASKS,
)
from maistro.runs import GraphSnapshot, Run


def _waiting_record() -> DurableRunRecord:
    graph = Graph(
        workspace_id="ws-trust",
        project_id="project-trust",
        name="pause redispatch",
        nodes=[Node(node_id="wait-step", node_type="trust.wait")],
    )
    return DurableRunRecord(
        run=Run(
            run_id="pause-trust-run",
            workspace_id=graph.workspace_id,
            project_id=graph.project_id,
            graph=GraphSnapshot.from_graph(graph),
            status=RunStatus.WAITING,
        ),
        graph_state=GraphExecutionState(run_id="pause-trust-run"),
        version=1,
    )


def test_elapsed_answer_gated_pause_does_not_redispatch_external_work() -> None:
    """A timeout timestamp is not permission to repeat an answer-gated dispatch."""
    paused = NodeResult(
        success=True,
        status="paused",
        resume_at=datetime.now(UTC) - timedelta(seconds=1),
        metadata={"paused_reason": PAUSE_AWAITING_REMOTE_DELEGATION},
    )

    assert not attempt_executor._requires_continuation_redispatch(
        _waiting_record(), "wait-step", paused
    )


def test_elapsed_polling_pause_does_redispatch() -> None:
    """Only reasons classified as elapsed-resumable may poll again on the clock."""
    paused = NodeResult(
        success=True,
        status="paused",
        resume_at=datetime.now(UTC) - timedelta(seconds=1),
        metadata={"paused_reason": PAUSE_WAITING_ON_JIRA_SUBTASKS},
    )

    assert attempt_executor._requires_continuation_redispatch(
        _waiting_record(), "wait-step", paused
    )
