"""Delegated work is a child Run, not a free-floating A2A task (#147).

Before this, `AgentDelegateRemoteNode` dispatched through `A2ADelegator` or
`GuestPeerManager`, got a `task_id`, and paused. The delegated work's only
identity was an `A2ATask` carrying its own `TaskStatus` enum and its own
`can_transition` table — a second lifecycle running beside the Run, which is
what #47's "A2A lifecycle no longer competes with Run after admission" is
about.

The identity needed was already in hand and unused: `NodeContext` carries
`run_id`, `node_run_id` and `project_id`, and both `_dispatch_*` methods took
`ctx` and never read it.

**The escape guards are the point of the last two tests.**
`RunStore.create_run` has always refused a child Run that crosses a Workspace
or implicitly crosses a Project — and delegation never reached them, so they
were never exercised from the path that most needs them. They are reachable
now because a delegation can name a destination; a delegation that names a
foreign one is refused rather than filed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from maistro.a2a.delegate import A2ADelegator
from maistro.a2a.guest_peers import DelegationResult, GuestPeerManager
from maistro.graph import Graph, Node
from maistro.graph.nodes import NodeContext
from maistro.graph.nodes.agent_delegate_remote import (
    AgentDelegateRemoteNode,
    DelegationNotConfiguredError,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore


async def _spine(
    *, workspace_id: str = "workspace-1"
) -> tuple[InMemoryRunStore, InMemoryProjectScopeStore, Any]:
    """A run store with one canonical Project, the way `runs/` tests build it."""
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root(workspace_id)
    project = await project_store.create(
        workspace_id=workspace_id,
        parent_project_id=root.project_id,
        name="Project",
    )
    return InMemoryRunStore(project_store=project_store), project_store, project


def _graph(*, workspace_id: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="Delegating pipeline",
        nodes=[Node(node_id="delegate-1", node_type="agent.delegate_remote")],
    )


def _ctx(*, run_id: str, node_run_id: str = "", project_id: str = "") -> NodeContext:
    return NodeContext(
        run_id=run_id,
        dag_id="dag-1",
        node_id="delegate-1",
        node_run_id=node_run_id,
        project_id=project_id or None,
    )


def _delegator() -> A2ADelegator:
    """A delegator that will accept `planner -> researcher`."""
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["researcher"])
    return delegator


class TestDelegationFilesAChildRun:
    async def test_an_in_process_delegation_creates_a_child_of_the_delegating_node_run(
        self,
    ) -> None:
        store, _projects, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        parent_node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")

        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
        result = await node.run(
            {"from_agent": "planner", "task": "research X", "to_agent": "researcher"},
            _ctx(run_id=parent.run_id, node_run_id=parent_node_run.node_run_id),
        )

        assert result.status == "paused", "the node still pauses; it now has an identity too"
        child_run_id = result.metadata["run_id"]
        assert child_run_id, "the pause metadata carries the child Run"

        child = await store.get_run(child_run_id)
        assert child is not None
        assert child.parent_run_id == parent.run_id
        assert child.parent_node_run_id == parent_node_run.node_run_id
        # Filed in the parent's scope, which is the only thing that succeeds
        # without an explicit cross-Project authorization.
        assert child.workspace_id == parent.workspace_id
        assert child.project_id == parent.project_id

    async def test_the_child_run_provenance_names_the_task_the_mode_and_both_agents(
        self,
    ) -> None:
        store, _projects, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")

        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
        result = await node.run(
            {"from_agent": "planner", "task": "research X", "to_agent": "researcher"},
            _ctx(run_id=parent.run_id, node_run_id=node_run.node_run_id),
        )

        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        provenance = child.provenance
        assert provenance["admission_source"] == "a2a_delegation"
        assert provenance["delegation_mode"] == "in_process"
        assert provenance["delegating_agent"] == "planner"
        assert provenance["target_agent"] == "researcher"
        # The A2A task id stays a receipt of the transport rather than the
        # work's identity — the Run is the identity now.
        assert provenance["a2a_task_id"] == result.metadata["task_id"]

    async def test_a_rejected_delegation_files_no_child_run(self) -> None:
        """Nothing was admitted, so there is no execution to give an identity.

        A target the delegator will not route to is a legitimate outcome the
        Graph may branch on — unlike a missing delegator, which is this
        instance being misconfigured.
        """
        store, _projects, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )

        node = AgentDelegateRemoteNode(a2a_delegator=A2ADelegator(), run_store=store)
        result = await node.run(
            {"from_agent": "planner", "task": "x"},
            _ctx(run_id=parent.run_id),
        )

        assert result.status == "completed"
        assert result.output.status == "rejected"
        assert result.output.run_id == "", "a rejection has no child Run to name"


class TestTheEscapeGuardsFire:
    """`RunStore.create_run`'s two refusals, reached from delegation at last."""

    async def test_a_delegation_naming_a_foreign_workspace_is_refused(self) -> None:
        store, project_store, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        # A real second Workspace, so the refusal is about crossing rather than
        # about the destination not existing.
        other_root = await project_store.create_root("workspace-2")

        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
        result = await node.run(
            {
                "from_agent": "planner",
                "task": "x",
                "to_agent": "researcher",
                "to_workspace_id": "workspace-2",
                "to_project_id": other_root.project_id,
            },
            _ctx(run_id=parent.run_id),
        )

        assert result.status == "failed"
        assert result.error_code == "RunIntegrityError"
        assert "Workspace" in (result.error_message or "")

    async def test_a_delegation_naming_a_sibling_project_is_refused(self) -> None:
        """Crossing a Project is refused *implicitly*: the guard's own message
        says the caller must authorize and request the destination, and this
        node never passes `allow_cross_project` — honouring such a request is
        an authorization decision that does not belong in a graph node."""
        store, project_store, project = await _spine()
        root = await project_store.root_for_workspace("workspace-1")
        sibling = await project_store.create(
            workspace_id="workspace-1",
            parent_project_id=root.project_id,
            name="Sibling",
        )
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )

        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
        result = await node.run(
            {
                "from_agent": "planner",
                "task": "x",
                "to_agent": "researcher",
                "to_project_id": sibling.project_id,
            },
            _ctx(run_id=parent.run_id),
        )

        assert result.status == "failed"
        assert result.error_code == "RunIntegrityError"
        assert "Project boundaries" in (result.error_message or "")


class TestAnUnknownParentIsRefused:
    async def test_delegating_under_a_run_the_store_does_not_know(self) -> None:
        """A delegation cannot be filed as a child of a Run that does not
        exist, and pretending otherwise would produce an orphan."""
        store, _projects, _project = await _spine()

        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
        result = await node.run(
            {"from_agent": "planner", "task": "x", "to_agent": "researcher"},
            _ctx(run_id="run-that-does-not-exist"),
        )

        assert result.status == "failed"
        assert result.error_code == DelegationNotConfiguredError.__name__


class TestTheResolverWiresTheNode:
    def test_build_node_resolver_supplies_the_delegate_nodes_dependencies(self) -> None:
        """The second half of #147: production resolved this node through the
        plain `get_node(kind)()` fallback, which constructs it with
        `a2a_delegator=None` and `guest_peers=None` — so every delegation
        failed on a `None` check before reaching any transport."""
        from maistro.container import build_node_resolver

        delegator = A2ADelegator()
        resolver = build_node_resolver(a2a_delegator=delegator, run_store="run-store-sentinel")
        graph = Graph(
            workspace_id="workspace-1",
            project_id="project-1",
            name="g",
            nodes=[Node(node_id="delegate-1", node_type="agent.delegate_remote")],
        )

        node = resolver("delegate-1", graph)

        assert isinstance(node, AgentDelegateRemoteNode)
        assert node._a2a_delegator is delegator
        assert node._run_store == "run-store-sentinel"

    def test_the_unwired_resolver_still_produces_the_node(self) -> None:
        """`build_node_resolver()` with no arguments is what
        `hive-conductor/services/dag_agents.py` calls, exactly as it does for
        `agent.spawn_harness`'s adapters. The node is still constructed; it
        simply has no delegator, and now says so loudly instead of returning a
        result shaped like a refusal."""
        from maistro.container import build_node_resolver

        graph = Graph(
            workspace_id="workspace-1",
            project_id="project-1",
            name="g",
            nodes=[Node(node_id="delegate-1", node_type="agent.delegate_remote")],
        )

        node = build_node_resolver()("delegate-1", graph)

        assert isinstance(node, AgentDelegateRemoteNode)
        assert node._a2a_delegator is None
        assert node._run_store is None


class TestCrossInstanceDelegationFilesAChildRun:
    """#47's fifth criterion asks for **one local and one remote** delegation
    path covered end to end. The in-process path above had it; the
    cross-instance path filed a child Run in `_dispatch_cross_instance` that no
    test read back, so "delegation creates a child Run" was proven for one of
    the two ways delegation happens.
    """

    @staticmethod
    def _peers(status: str = "submitted", error: str | None = None) -> GuestPeerManager:
        guest_peers = GuestPeerManager()
        guest_peers.delegate = AsyncMock(  # type: ignore[method-assign]
            return_value=DelegationResult(
                task_id="remote-1", peer_name="hub", status=status, error=error
            )
        )
        return guest_peers

    async def test_a_cross_instance_delegation_creates_a_child_of_the_delegating_node_run(
        self,
    ) -> None:
        store, _projects, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        parent_node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")

        node = AgentDelegateRemoteNode(guest_peers=self._peers(), run_store=store)
        result = await node.run(
            {"from_agent": "planner", "task": "research X", "peer_name": "hub"},
            _ctx(run_id=parent.run_id, node_run_id=parent_node_run.node_run_id),
        )

        assert result.status == "paused"
        child_run_id = result.metadata["run_id"]
        assert child_run_id

        child = await store.get_run(child_run_id)
        assert child is not None
        assert child.parent_run_id == parent.run_id
        assert child.parent_node_run_id == parent_node_run.node_run_id
        assert child.workspace_id == parent.workspace_id
        assert child.project_id == parent.project_id

    async def test_the_cross_instance_child_names_the_peer_the_task_and_the_mode(self) -> None:
        """The receipt stays a receipt: the A2A task_id is provenance on the
        Run rather than the only record of the delegation."""
        store, _projects, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        parent_node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")

        node = AgentDelegateRemoteNode(guest_peers=self._peers(), run_store=store)
        result = await node.run(
            {"from_agent": "planner", "task": "research X", "peer_name": "hub"},
            _ctx(run_id=parent.run_id, node_run_id=parent_node_run.node_run_id),
        )

        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        provenance = child.provenance
        assert provenance["admission_source"] == "a2a_delegation"
        assert provenance["a2a_task_id"] == "remote-1"
        assert provenance["delegation_mode"] == "guest_peer"
        assert provenance["delegating_agent"] == "planner"
        assert provenance["target_agent"] == "hub"
        assert provenance["peer_name"] == "hub"

    async def test_a_peer_that_declines_files_no_child_run(self) -> None:
        """Nothing was admitted, so there is no execution to give an identity
        to — the same rule the in-process rejection follows."""
        store, _projects, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        parent_node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")

        node = AgentDelegateRemoteNode(
            guest_peers=self._peers(status="rejected", error="peer not found"), run_store=store
        )
        result = await node.run(
            {"from_agent": "planner", "task": "research X", "peer_name": "hub"},
            _ctx(run_id=parent.run_id, node_run_id=parent_node_run.node_run_id),
        )

        assert result.status == "completed"
        assert result.output.status == "rejected"
        children = [
            run
            for run in store._runs.values()  # type: ignore[attr-defined]
            if run.parent_run_id == parent.run_id
        ]
        assert children == []
