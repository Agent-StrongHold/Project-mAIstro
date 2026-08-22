"""Delegated work is a child Run, not just an A2A task id (#147).

`RunStore.create_run` has always accepted `parent_run_id`/`parent_node_run_id`
and has always refused a child that crosses a Workspace or implicitly crosses a
Project. Delegation never reached either guard, because it created no Run: the
delegated work's identity was an `A2ATask` id and a `TaskStatus` running
alongside the spine rather than on it.

The guards are the sharp part of this suite. They are the "scoped authority"
half of #47, and until now nothing exercised them from the delegation path.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.a2a.admission import (
    A2A_TASK_ID_KEY,
    DELEGATION_MODE_KEY,
    DELEGATION_SOURCE,
    FROM_AGENT_KEY,
    PEER_NAME_KEY,
    TO_AGENT_KEY,
    DelegationRunAdmitter,
)
from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.admission import ADMISSION_SOURCE
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore, RunIntegrityError
from maistro.runs.task_kinds import DELEGATE_NODE_KIND

WORKSPACE = "delegation-workspace"


@pytest.fixture
async def seam():
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    other = await projects.create(
        workspace_id=WORKSPACE, parent_project_id=root.project_id, name="Elsewhere"
    )
    runs = InMemoryRunStore(project_store=projects)
    admitter = DelegationRunAdmitter(runs)
    return admitter, runs, projects, root.project_id, other.project_id


async def _parent(seam: Any, *, project_id: str | None = None):
    """A running parent Run with one NodeRun — the delegating node."""
    _admitter, runs, _projects, root_project, _other = seam
    graph = Graph(
        workspace_id=WORKSPACE,
        project_id=project_id or root_project,
        name="parent",
        nodes=[Node(node_id="n1", node_type=DELEGATE_NODE_KIND, name="delegate")],
    )
    run = await runs.create_run(graph)
    await runs.transition_run(run.run_id, RunStatus.QUEUED)
    await runs.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await runs.create_node_run(run.run_id, node_id="n1")
    return run, node_run


# ── the child Run exists and points back ──────────────────────────


async def test_a_delegation_produces_a_child_run(seam) -> None:
    admitter, runs, _projects, _root, _other = seam
    parent, node_run = await _parent(seam)

    child = await admitter.admit_delegation(
        parent_run_id=parent.run_id,
        parent_node_run_id=node_run.node_run_id,
        task="summarise the incident",
        to_agent="scribe",
        from_agent="planner",
        a2a_task_id="a2a-1",
    )

    assert await runs.get_run(child.run_id) is not None
    assert child.run_id != parent.run_id


async def test_the_child_points_at_the_delegating_run_and_node_run(seam) -> None:
    """`parent_run_id`/`child_run_id` correlation is the first thing #47 asks
    for, and it is what makes a delegation tree walkable at all."""
    admitter, _runs, _projects, _root, _other = seam
    parent, node_run = await _parent(seam)

    child = await admitter.admit_delegation(
        parent_run_id=parent.run_id,
        parent_node_run_id=node_run.node_run_id,
        task="x",
        to_agent="scribe",
    )

    assert child.parent_run_id == parent.run_id
    assert child.parent_node_run_id == node_run.node_run_id


async def test_the_child_inherits_the_parents_scope(seam) -> None:
    """Never the caller's word for it. A delegation that could name its own
    Workspace would be a way to move work into a tenant the delegating agent
    has no authority in."""
    admitter, _runs, _projects, root, _other = seam
    parent, node_run = await _parent(seam)

    child = await admitter.admit_delegation(
        parent_run_id=parent.run_id,
        parent_node_run_id=node_run.node_run_id,
        task="x",
        to_agent="scribe",
    )

    assert child.workspace_id == WORKSPACE
    assert child.project_id == root


async def test_the_child_graph_is_one_executable_delegation_node(seam) -> None:
    admitter, _runs, _projects, _root, _other = seam
    parent, node_run = await _parent(seam)

    child = await admitter.admit_delegation(
        parent_run_id=parent.run_id,
        parent_node_run_id=node_run.node_run_id,
        task="summarise the incident",
        to_agent="scribe",
        from_agent="planner",
    )

    nodes = child.graph.materialize().nodes
    assert len(nodes) == 1
    assert nodes[0].node_type == DELEGATE_NODE_KIND
    assert nodes[0].parameters["to_agent"] == "scribe"
    assert nodes[0].parameters["from_agent"] == "planner"
    assert nodes[0].parameters["task"] == "summarise the incident"


# ── provenance: the A2A task stays, as a receipt ──────────────────


async def test_provenance_records_the_delegation_and_its_receipt(seam) -> None:
    """The A2A task id is kept, not replaced. It is the transport's record of
    what it was asked to carry — the way `TaskResponse` remains the queue's."""
    admitter, _runs, _projects, _root, _other = seam
    parent, node_run = await _parent(seam)

    child = await admitter.admit_delegation(
        parent_run_id=parent.run_id,
        parent_node_run_id=node_run.node_run_id,
        task="x",
        to_agent="scribe",
        from_agent="planner",
        mode="in_process",
        a2a_task_id="a2a-42",
    )

    assert child.provenance[ADMISSION_SOURCE] == DELEGATION_SOURCE
    assert child.provenance[A2A_TASK_ID_KEY] == "a2a-42"
    assert child.provenance[FROM_AGENT_KEY] == "planner"
    assert child.provenance[TO_AGENT_KEY] == "scribe"
    assert child.provenance[DELEGATION_MODE_KEY] == "in_process"


async def test_a_cross_instance_delegation_names_its_peer(seam) -> None:
    admitter, _runs, _projects, _root, _other = seam
    parent, node_run = await _parent(seam)

    child = await admitter.admit_delegation(
        parent_run_id=parent.run_id,
        parent_node_run_id=node_run.node_run_id,
        task="x",
        to_agent="hub",
        mode="guest_peer",
        peer_name="hub",
    )

    assert child.provenance[DELEGATION_MODE_KEY] == "guest_peer"
    assert child.provenance[PEER_NAME_KEY] == "hub"


async def test_an_in_process_delegation_has_no_peer_key(seam) -> None:
    """An empty peer_name in provenance would look like a peer that exists and
    has no name."""
    admitter, _runs, _projects, _root, _other = seam
    parent, node_run = await _parent(seam)

    child = await admitter.admit_delegation(
        parent_run_id=parent.run_id,
        parent_node_run_id=node_run.node_run_id,
        task="x",
        to_agent="scribe",
    )

    assert PEER_NAME_KEY not in child.provenance


# ── the escape guards, reached from delegation for the first time ──


async def test_a_delegation_cannot_cross_a_workspace(seam) -> None:
    """The child takes the parent's Workspace by construction, so the only way
    to attempt an escape is to delegate from a Run in another Workspace — and
    the store refuses to parent across the boundary."""
    _admitter, runs, projects, _root, _other = seam
    foreign_root = await projects.create_root("somebody-elses-workspace")
    parent, node_run = await _parent(seam)
    foreign_graph = Graph(
        workspace_id="somebody-elses-workspace",
        project_id=foreign_root.project_id,
        name="foreign",
        nodes=[Node(node_id="n1", node_type=DELEGATE_NODE_KIND, name="d")],
    )
    foreign = await runs.create_run(foreign_graph)

    with pytest.raises(RunIntegrityError, match="Workspace"):
        await runs.create_run(
            Graph(
                workspace_id=WORKSPACE,
                project_id=parent.project_id,
                name="child",
                nodes=[Node(node_id="n1", node_type=DELEGATE_NODE_KIND, name="d")],
            ),
            parent_run_id=foreign.run_id,
            parent_node_run_id=None,
        )
    assert node_run.run_id == parent.run_id


async def test_a_delegation_cannot_implicitly_cross_a_project(seam) -> None:
    """Two Projects in one Workspace is the ordinary case, and a child that
    silently landed in a sibling Project would be an authority escape the
    Workspace check cannot catch."""
    _admitter, runs, _projects, _root, other_project = seam
    parent, _node_run = await _parent(seam)

    with pytest.raises(RunIntegrityError, match="Project"):
        await runs.create_run(
            Graph(
                workspace_id=WORKSPACE,
                project_id=other_project,
                name="child",
                nodes=[Node(node_id="n1", node_type=DELEGATE_NODE_KIND, name="d")],
            ),
            parent_run_id=parent.run_id,
        )


async def test_delegating_from_a_run_that_does_not_resolve_is_refused(seam) -> None:
    """A parent_run_id nothing can find means the delegating Run is an orphan;
    filing a child under it would compound the problem rather than record it."""
    admitter, _runs, _projects, _root, _other = seam

    with pytest.raises(RunIntegrityError, match="does not resolve"):
        await admitter.admit_delegation(
            parent_run_id="no-such-run",
            parent_node_run_id=None,
            task="x",
            to_agent="scribe",
        )


async def test_a_delegation_without_a_node_run_still_admits(seam) -> None:
    """`NodeContext.node_run_id` is empty until physical execution begins, and
    a delegation dispatched before then is still a real child of the Run."""
    admitter, _runs, _projects, _root, _other = seam
    parent, _node_run = await _parent(seam)

    child = await admitter.admit_delegation(
        parent_run_id=parent.run_id,
        parent_node_run_id=None,
        task="x",
        to_agent="scribe",
    )

    assert child.parent_run_id == parent.run_id
    assert child.parent_node_run_id is None


# ── through the node, and through the resolver that builds it ──────


async def _node_seam(seam: Any):
    """The delegate node wired the way `build_node_resolver` now wires it."""
    from maistro.a2a.delegate import A2ADelegator
    from maistro.graph.nodes.agent_delegate_remote import AgentDelegateRemoteNode

    admitter, runs, _projects, _root, _other = seam
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["scribe"])
    node = AgentDelegateRemoteNode(a2a_delegator=delegator, delegation_admitter=admitter)
    return node, runs


def _node_ctx(parent_run_id: str, node_run_id: str) -> Any:
    from maistro.graph.nodes.base import NodeContext

    return NodeContext(
        run_id=parent_run_id,
        dag_id="dag-1",
        node_id="delegate-1",
        node_run_id=node_run_id,
        user_id="alice",
    )


async def test_the_node_admits_a_child_run_and_pauses(seam) -> None:
    node, runs = await _node_seam(seam)
    parent, node_run = await _parent(seam)

    result = await node.run(
        {"from_agent": "planner", "task": "summarise", "to_agent": "scribe"},
        _node_ctx(parent.run_id, node_run.node_run_id),
    )

    assert result.status == "paused"
    child_run_id = result.metadata["run_id"]
    assert child_run_id
    child = await runs.get_run(child_run_id)
    assert child is not None
    assert child.parent_run_id == parent.run_id
    assert child.parent_node_run_id == node_run.node_run_id


async def test_the_pause_carries_both_identities(seam) -> None:
    """The A2A task id alone was all a resumer had to correlate on; it now has
    the child Run too, which is the identity everything else in the spine uses."""
    node, _runs = await _node_seam(seam)
    parent, node_run = await _parent(seam)

    result = await node.run(
        {"from_agent": "planner", "task": "summarise", "to_agent": "scribe"},
        _node_ctx(parent.run_id, node_run.node_run_id),
    )

    assert result.metadata["task_id"]
    assert result.metadata["run_id"]
    assert result.metadata["mode"] == "in_process"


async def test_a_policy_rejection_admits_no_child_run(seam) -> None:
    """Rejected work was handed to nobody, so a Run recording it would be a
    record of something that never happened."""
    from maistro.a2a.delegate import A2ADelegator
    from maistro.graph.nodes.agent_delegate_remote import AgentDelegateRemoteNode

    admitter, runs, _projects, _root, _other = seam
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["scribe"])
    node = AgentDelegateRemoteNode(a2a_delegator=delegator, delegation_admitter=admitter)
    parent, node_run = await _parent(seam)
    before = len(await runs.list_node_runs(parent.run_id))

    result = await node.run(
        # "auditor" is not on planner's allow-list.
        {"from_agent": "planner", "task": "x", "to_agent": "auditor"},
        _node_ctx(parent.run_id, node_run.node_run_id),
    )

    assert result.status == "completed"
    assert result.output.status == "rejected"
    assert result.output.run_id == ""
    assert len(await runs.list_node_runs(parent.run_id)) == before


async def test_the_resumed_result_carries_the_child_run_id(seam) -> None:
    node, _runs = await _node_seam(seam)
    parent, node_run = await _parent(seam)
    ctx = _node_ctx(parent.run_id, node_run.node_run_id)
    ctx.metadata = {
        "hitl_answers": {
            "delegate-1": {
                "status": "completed",
                "task_id": "a2a-1",
                "run_id": "child-run-1",
                "result": "done",
            }
        }
    }

    result = await node.run({"from_agent": "planner", "task": "x", "to_agent": "scribe"}, ctx)

    assert result.status == "completed"
    assert result.output.run_id == "child-run-1"
    assert result.output.result == "done"


def test_the_resolver_wires_the_delegate_node() -> None:
    """It previously fell through to `get_node(kind)()`, so both dependencies
    were None in every production process (#147)."""
    from maistro.container import build_node_resolver

    graph = Graph(
        workspace_id="w",
        project_id="p",
        name="g",
        nodes=[Node(node_id="n1", node_type=DELEGATE_NODE_KIND, name="d")],
    )
    sentinel_delegator = object()
    sentinel_admitter = object()

    node = build_node_resolver(
        a2a_delegator=sentinel_delegator, delegation_admitter=sentinel_admitter
    )("n1", graph)

    assert node._a2a_delegator is sentinel_delegator
    assert node._delegation_admitter is sentinel_admitter
