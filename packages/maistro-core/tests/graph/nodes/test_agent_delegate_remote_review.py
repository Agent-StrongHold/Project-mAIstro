"""The child Run has a lifecycle, an identity and a scope check that fire in
the right order (#147, review round 2).

The first pass filed a canonical child Run and stopped there. Review found the
child was created and then abandoned: persisted `created`, never transitioned,
while the parent graph moved on with the delegate's answer. The rest of these
follow from the same gap — the node knew about the child at dispatch and forgot
it at resume.

Each case here is one of those, and each fails on the code as it was.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.a2a.delegate import A2ADelegator
from maistro.graph import Graph, Node
from maistro.graph.nodes import NodeContext
from maistro.graph.nodes.agent_delegate_remote import AgentDelegateRemoteNode
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore, RunIntegrityError, RunStatus


async def _spine(*, workspace_id: str = "workspace-1") -> tuple[InMemoryRunStore, Any]:
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root(workspace_id)
    project = await project_store.create(
        workspace_id=workspace_id, parent_project_id=root.project_id, name="Project"
    )
    return InMemoryRunStore(project_store=project_store), project


def _graph(*, workspace_id: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="Delegating pipeline",
        nodes=[Node(node_id="delegate-1", node_type="agent.delegate_remote")],
    )


def _ctx(*, run_id: str, node_run_id: str = "", answer: dict[str, Any] | None = None):
    return NodeContext(
        run_id=run_id,
        dag_id="dag-1",
        node_id="delegate-1",
        node_run_id=node_run_id,
        metadata={"hitl_answers": {"delegate-1": answer}} if answer is not None else {},
    )


def _delegator() -> A2ADelegator:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["researcher"])
    return delegator


class _RecordingDelegator(A2ADelegator):
    """A delegator that remembers whether it was ever asked to admit work.

    The property under test is "nothing was dispatched", and `A2ADelegator`
    exposes no way to list its queue — only `get_task_status(task_id)`, which
    needs the id a refused delegation never produced. Counting the calls states
    the property directly instead of inferring it from an absence.
    """

    def __init__(self) -> None:
        super().__init__()
        self.dispatched: list[tuple[str, str, str | None]] = []

    def delegate_task(self, from_agent, task, to_agent, *args: Any, **kwargs: Any) -> str:  # type: ignore[no-untyped-def]
        self.dispatched.append((from_agent, task, to_agent))
        return super().delegate_task(from_agent, task, to_agent, *args, **kwargs)


def _recording_delegator() -> _RecordingDelegator:
    delegator = _RecordingDelegator()
    delegator.register_agent_capability("planner", ["researcher"])
    return delegator


async def _dispatched(store: InMemoryRunStore, project_id: str, **inputs: Any):
    """Dispatch one delegation and return `(node, parent, child_run_id)`."""
    parent = await store.create_run(_graph(workspace_id="workspace-1", project_id=project_id))
    node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
    node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
    result = await node.run(
        {"from_agent": "planner", "task": "research X", "to_agent": "researcher", **inputs},
        _ctx(run_id=parent.run_id, node_run_id=node_run.node_run_id),
    )
    return node, parent, str(result.metadata["run_id"])


# --------------------------------------------------------------------------
# The child Run reaches a terminal state
# --------------------------------------------------------------------------


class TestTheChildRunIsSettled:
    """Before this, `create_run` was the child's whole life.

    Neither A2A transport touches the Run store, so a completed, failed or
    timed-out answer advanced the parent graph while the canonical child still
    reported `created` with no result and no error — the same "second lifecycle
    beside the Run" this node exists to remove, one level down.
    """

    @pytest.mark.parametrize(
        ("answered", "expected"),
        [
            ("completed", RunStatus.COMPLETED),
            ("failed", RunStatus.FAILED),
            ("timed_out", RunStatus.TIMED_OUT),
            # Admitted and then declined: `cancelled` rather than `failed`,
            # which would read as attempted-and-gone-wrong.
            ("rejected", RunStatus.CANCELLED),
        ],
    )
    async def test_the_answer_settles_the_child(self, answered: str, expected: RunStatus) -> None:
        store, project = await _spine()
        node, parent, child_run_id = await _dispatched(store, project.project_id)
        assert (await store.get_run(child_run_id)).status is RunStatus.CREATED

        await node.run(
            {"from_agent": "planner", "task": "research X"},
            _ctx(
                run_id=parent.run_id,
                answer={"status": answered, "_pause": {"run_id": child_run_id}},
            ),
        )

        child = await store.get_run(child_run_id)
        assert child is not None
        assert child.status is expected
        assert child.finished_at is not None

    async def test_the_delegates_result_lands_on_the_child(self) -> None:
        store, project = await _spine()
        node, parent, child_run_id = await _dispatched(store, project.project_id)

        await node.run(
            {"from_agent": "planner", "task": "research X"},
            _ctx(
                run_id=parent.run_id,
                answer={
                    "status": "completed",
                    "result": "X is documented",
                    "_pause": {"run_id": child_run_id},
                },
            ),
        )

        child = await store.get_run(child_run_id)
        assert child is not None
        assert child.result == "X is documented"

    async def test_an_unrecognised_status_fails_loudly_instead_of_crashing(self) -> None:
        """The status also selects the child's terminal state, so a value
        outside the four would `KeyError` in the middle of settling a Run.
        Reporting it as failed *with the reason* keeps a malformed answer from
        reading as a legitimate refusal."""
        store, project = await _spine()
        node, parent, child_run_id = await _dispatched(store, project.project_id)

        result = await node.run(
            {"from_agent": "planner", "task": "x"},
            _ctx(
                run_id=parent.run_id,
                answer={"status": "banana", "_pause": {"run_id": child_run_id}},
            ),
        )

        assert result.status == "completed", "a bad answer is a delegation outcome, not a crash"
        assert result.output.status == "failed"
        assert "banana" in (result.output.error or "")
        assert (await store.get_run(child_run_id)).status is RunStatus.FAILED

    async def test_a_second_resume_does_not_reopen_a_settled_child(self) -> None:
        """A terminal Run has no outgoing transitions, so a duplicate answer
        would raise and sink a delegation whose result is already in hand."""
        store, project = await _spine()
        node, parent, child_run_id = await _dispatched(store, project.project_id)
        ctx = _ctx(
            run_id=parent.run_id,
            answer={"status": "completed", "_pause": {"run_id": child_run_id}},
        )
        await node.run({"from_agent": "planner", "task": "x"}, ctx)

        result = await node.run({"from_agent": "planner", "task": "x"}, ctx)

        assert result.status == "completed"
        assert (await store.get_run(child_run_id)).status is RunStatus.COMPLETED


# --------------------------------------------------------------------------
# The Run id survives the resume, and comes from the server
# --------------------------------------------------------------------------


class TestTheRunIdIsNotSourcedFromTheResponder:
    async def test_the_pause_payload_supplies_the_run_id(self) -> None:
        """The store deletes the node's pause entry when it attaches the answer,
        so without the stamped copy the new `run_id` output was always `""` on
        the normal resume path — a field that could never be populated."""
        store, project = await _spine()
        node, parent, child_run_id = await _dispatched(store, project.project_id)

        result = await node.run(
            {"from_agent": "planner", "task": "x"},
            _ctx(
                run_id=parent.run_id,
                answer={"status": "completed", "_pause": {"run_id": child_run_id}},
            ),
        )

        assert result.output.run_id == child_run_id

    async def test_a_responder_cannot_name_the_run_it_answers_for(self) -> None:
        """Otherwise any caller could redirect a delegation's outcome onto
        someone else's Run — the responder is the party being waited on, and
        execution identity must not come from it."""
        store, project = await _spine()
        node, parent, child_run_id = await _dispatched(store, project.project_id)
        victim = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )

        result = await node.run(
            {"from_agent": "planner", "task": "x"},
            _ctx(
                run_id=parent.run_id,
                answer={
                    "status": "failed",
                    "run_id": victim.run_id,
                    "_pause": {"run_id": child_run_id},
                },
            ),
        )

        assert result.output.run_id == child_run_id
        assert (await store.get_run(victim.run_id)).status is RunStatus.CREATED, (
            "the submitted run_id must not reach the store at all"
        )
        assert (await store.get_run(child_run_id)).status is RunStatus.FAILED


# --------------------------------------------------------------------------
# Scope is settled before anything is dispatched
# --------------------------------------------------------------------------


class TestScopeIsCheckedBeforeDispatch:
    """`create_run` ran *after* the transport call, so a delegation naming a
    foreign Workspace was refused only once the work had already been handed
    over: the node reported failure while unauthorized work carried on
    elsewhere, and a retry dispatched it again."""

    async def test_a_foreign_workspace_is_refused_before_the_task_is_queued(self) -> None:
        store, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        delegator = _recording_delegator()
        node = AgentDelegateRemoteNode(a2a_delegator=delegator, run_store=store)

        result = await node.run(
            {
                "from_agent": "planner",
                "task": "x",
                "to_agent": "researcher",
                "to_workspace_id": "workspace-2",
            },
            _ctx(run_id=parent.run_id),
        )

        assert result.status == "failed"
        assert result.error_code == RunIntegrityError.__name__
        assert delegator.dispatched == [], "nothing may be admitted by a refused delegation"

    async def test_an_unknown_parent_is_refused_before_the_task_is_queued(self) -> None:
        store, _project = await _spine()
        delegator = _recording_delegator()
        node = AgentDelegateRemoteNode(a2a_delegator=delegator, run_store=store)

        result = await node.run(
            {"from_agent": "planner", "task": "x", "to_agent": "researcher"},
            _ctx(run_id="run-that-does-not-exist"),
        )

        assert result.status == "failed"
        assert delegator.dispatched == []

    async def test_a_delegation_in_the_parents_own_scope_still_dispatches(self) -> None:
        """The pre-flight must not become a refusal of the ordinary case."""
        store, project = await _spine()
        _node, _parent, child_run_id = await _dispatched(store, project.project_id)

        assert child_run_id


# --------------------------------------------------------------------------
# What the child records
# --------------------------------------------------------------------------


class TestWhatTheChildRecords:
    async def test_the_child_inherits_the_delegating_actor_and_persona(self) -> None:
        """Delegated work that loses its attribution cannot be audited or
        policed as the same person's, and both values were already on the
        parent record this code had just fetched."""
        store, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id),
            persona_id="persona-7",
            actor_principal_id="user-42",
        )
        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
        result = await node.run(
            {"from_agent": "planner", "task": "x", "to_agent": "researcher"},
            _ctx(run_id=parent.run_id),
        )

        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        assert child.actor_principal_id == "user-42"
        assert child.persona_id == "persona-7"

    async def test_an_automatic_delegation_records_the_agent_that_was_chosen(self) -> None:
        """With `to_agent=None` the delegator selects a concrete agent. Recording
        the literal "auto" left the child's name and provenance disagreeing with
        the admitted `A2ATask.to_agent` for every automatic delegation — the case
        the field is most needed for."""
        store, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)

        result = await node.run(
            {"from_agent": "planner", "task": "x"},
            _ctx(run_id=parent.run_id),
        )

        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        assert child.provenance["target_agent"] == "researcher"
        assert "auto" not in child.graph.materialize().nodes[0].name

    async def test_the_child_snapshot_is_not_another_delegation(self) -> None:
        """A child whose only node is `agent.delegate_remote` describes the
        dispatch rather than the work: inspecting it shows a second hand-off,
        and replaying it would delegate again."""
        store, project = await _spine()
        _node, _parent, child_run_id = await _dispatched(store, project.project_id)

        child = await store.get_run(child_run_id)
        assert child is not None
        kinds = [node.node_type for node in child.graph.materialize().nodes]
        assert "agent.delegate_remote" not in kinds
        assert kinds == ["agent.remote_work"]

    async def test_an_inline_subgraph_is_snapshotted_as_the_work(self) -> None:
        """When the delegation carries the work, that is what the child records
        — rescoped into the child's Workspace and Project, because a Graph must
        agree with the Run that holds it."""
        store, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)

        result = await node.run(
            {
                "from_agent": "planner",
                "task": "x",
                "to_agent": "researcher",
                "subgraph": {
                    "workspace_id": "somewhere-else",
                    "project_id": "some-other-project",
                    "name": "Research pipeline",
                    "nodes": [{"node_id": "summarise", "node_type": "llm.summarize"}],
                },
            },
            _ctx(run_id=parent.run_id),
        )

        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        graph = child.graph.materialize()
        assert [node.node_type for node in graph.nodes] == ["llm.summarize"]
        assert graph.workspace_id == parent.workspace_id
        assert graph.project_id == parent.project_id
