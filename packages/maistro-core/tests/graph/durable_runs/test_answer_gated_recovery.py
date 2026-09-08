"""Regression coverage for answer-gated durable continuation recovery (#1092)."""

from datetime import UTC, datetime, timedelta

import pytest

from maistro.graph import Graph, GraphExecutionState, Node
from maistro.graph.durable_runs import (
    DurableRunRecord,
    InMemoryDurableRunStore,
    RunStatus,
    attempt_executor,
)
from maistro.graph.durable_runs import executor as traversal
from maistro.graph.nodes import NodeContext, NodeResult
from maistro.graph.nodes.base import (
    PAUSE_AWAITING_HUMAN_ANSWER,
    PAUSE_AWAITING_REMOTE_DELEGATION,
    PAUSE_WAITING_ON_JIRA_SUBTASKS,
)
from maistro.runs import GraphSnapshot, NodeRun, Run


def _record(*, status: RunStatus = RunStatus.WAITING, answered: bool = False) -> DurableRunRecord:
    graph = Graph(
        workspace_id="ws-answer-recovery",
        project_id="project-answer-recovery",
        name="answer recovery",
        nodes=[Node(node_id="wait-step", node_type="trust.wait")],
    )
    answers = {"wait-step": {"status": "completed"}} if answered else {}
    return DurableRunRecord(
        run=Run(
            run_id="answer-recovery-run",
            workspace_id=graph.workspace_id,
            project_id=graph.project_id,
            graph=GraphSnapshot.from_graph(graph),
            status=status,
        ),
        graph_state=GraphExecutionState(
            run_id="answer-recovery-run",
            active_node_ids=("wait-step",),
            metadata={"hitl_answers": answers},
        ),
        version=1,
    )


def _pause(reason: str, *, resume_at: datetime | None) -> NodeResult:
    return NodeResult(
        success=True,
        status="paused",
        resume_at=resume_at,
        metadata={"paused_reason": reason},
    )


def test_system_owned_answer_wait_redispatches_when_durable_answer_exists() -> None:
    paused = _pause(
        PAUSE_AWAITING_REMOTE_DELEGATION,
        resume_at=datetime.now(UTC) + timedelta(hours=1),
    )

    assert attempt_executor._requires_continuation_redispatch(
        _record(answered=True), "wait-step", paused
    )


def test_system_owned_answer_wait_does_not_redispatch_on_elapsed_time_alone() -> None:
    paused = _pause(
        PAUSE_AWAITING_REMOTE_DELEGATION,
        resume_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert not attempt_executor._requires_continuation_redispatch(
        _record(answered=False), "wait-step", paused
    )


def test_human_answer_wait_still_uses_durable_answer_evidence() -> None:
    paused = _pause(PAUSE_AWAITING_HUMAN_ANSWER, resume_at=None)

    assert attempt_executor._requires_continuation_redispatch(
        _record(answered=True), "wait-step", paused
    )
    assert not attempt_executor._requires_continuation_redispatch(
        _record(answered=False), "wait-step", paused
    )


def test_elapsed_timer_wait_still_redispatches() -> None:
    paused = _pause(
        PAUSE_WAITING_ON_JIRA_SUBTASKS,
        resume_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert attempt_executor._requires_continuation_redispatch(
        _record(answered=False), "wait-step", paused
    )


@pytest.mark.asyncio
async def test_answer_deadline_is_persisted_as_pause_evidence_but_not_timer_due() -> None:
    record = _record(status=RunStatus.RUNNING)
    store = InMemoryDurableRunStore()
    await store.create(record)
    graph = record.run.graph.materialize()
    deadline = datetime.now(UTC) - timedelta(seconds=1)
    paused = _pause(PAUSE_AWAITING_REMOTE_DELEGATION, resume_at=deadline)
    item = traversal._FrontierItem(
        node_id="wait-step",
        spec=graph.nodes[0],
        node_run=NodeRun(run_id=record.run_id, node_id="wait-step", ordinal=1),
        ctx=NodeContext(run_id=record.run_id, dag_id=graph.graph_id, node_id="wait-step"),
        result=paused,
    )

    checkpointed = await traversal._checkpoint_paused_frontier(
        record,
        (item,),
        (),
        (),
        store=store,
    )

    assert checkpointed.run.status is RunStatus.WAITING
    assert checkpointed.resume_at is None
    assert checkpointed.graph_state.metadata["pauses"]["wait-step"]["resume_at"] == (
        deadline.isoformat()
    )


@pytest.mark.asyncio
async def test_timer_wait_deadline_remains_timer_due() -> None:
    record = _record(status=RunStatus.RUNNING)
    store = InMemoryDurableRunStore()
    await store.create(record)
    graph = record.run.graph.materialize()
    deadline = datetime.now(UTC) - timedelta(seconds=1)
    paused = _pause(PAUSE_WAITING_ON_JIRA_SUBTASKS, resume_at=deadline)
    item = traversal._FrontierItem(
        node_id="wait-step",
        spec=graph.nodes[0],
        node_run=NodeRun(run_id=record.run_id, node_id="wait-step", ordinal=1),
        ctx=NodeContext(run_id=record.run_id, dag_id=graph.graph_id, node_id="wait-step"),
        result=paused,
    )

    checkpointed = await traversal._checkpoint_paused_frontier(
        record,
        (item,),
        (),
        (),
        store=store,
    )

    assert checkpointed.run.status is RunStatus.WAITING
    assert checkpointed.resume_at == deadline
