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

import httpx

from maistro.a2a.delegate import A2ADelegator
from maistro.a2a.guest_peers import DelegationResult, GuestPeerManager, PeerTrust
from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
    resume_durable_graph,
    run_durable_graph,
)
from maistro.graph.nodes import NodeContext
from maistro.graph.nodes.agent_delegate_remote import (
    AgentDelegateRemoteNode,
    DelegateRemoteIn,
    DelegationNotConfiguredError,
)
from maistro.http import set_test_transport
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore, RunStatus
from maistro.runs.store import RunIntegrityError


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
        parent_node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")

        node = AgentDelegateRemoteNode(a2a_delegator=A2ADelegator(), run_store=store)
        result = await node.run(
            {"from_agent": "planner", "task": "x"},
            _ctx(run_id=parent.run_id, node_run_id=parent_node_run.node_run_id),
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


class TestInterruptedChildAdmission:
    """Reservation is two durable stages; a death between them must neither
    pause the parent on an unanswerable child nor strand one nothing revisits.

    These are the #147 verification findings made executable: adopting a
    partially-created child left a paused parent plus a child with zero
    NodeRuns, and the child was admitted QUEUED before its evidence while
    `a2a_delegation` is deliberately not a consumable source — so that partial
    child had no recovery path at all.
    """

    @staticmethod
    async def _parent(store: InMemoryRunStore, project: Any) -> tuple[Any, Any]:
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        parent_node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
        return parent, parent_node_run

    async def test_a_transient_fault_during_evidence_writing_is_healed_before_the_pause(
        self,
    ) -> None:
        """The verification fault: the store dies after `create_run`.

        `_reserve_child` used to adopt its own half-written child and pause,
        leaving a paused parent beside a child with zero NodeRuns that no
        answer could ever settle. Adoption now completes the child's canonical
        evidence first, so the pause lands on an answerable Run.
        """
        store, _projects, project = await _spine()
        parent, parent_node_run = await self._parent(store, project)
        real_create_node_run = store.create_node_run
        calls = 0

        async def fail_once(run_id: str, *, node_id: str) -> Any:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RunIntegrityError("injected: store died mid-admission")
            return await real_create_node_run(run_id, node_id=node_id)

        store.create_node_run = fail_once  # type: ignore[method-assign]

        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
        result = await node.run(
            {"from_agent": "planner", "task": "research X", "to_agent": "researcher"},
            _ctx(run_id=parent.run_id, node_run_id=parent_node_run.node_run_id),
        )

        assert result.status == "paused", result.error_message
        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        node_runs = await store.list_node_runs(child.run_id)
        assert len(node_runs) == 1, "the adopted child was completed, not adopted half-way"
        attempts = await store.list_attempts(node_runs[0].node_run_id)
        assert [attempt.status.value for attempt in attempts] == ["yielded"]
        assert child.status.value == "waiting"

    async def test_a_persistent_fault_fails_the_dispatch_loudly_without_pausing(
        self,
    ) -> None:
        """A store that stays broken must not park the parent on an unanswerable
        child. The dispatch fails as an Attempt error the retry machinery can
        act on, and the reservation it leaves behind is a CREATED resting
        projection — never a QUEUED Run that reads as admitted work while no
        consumer will ever execute it.
        """
        store, _projects, project = await _spine()
        parent, parent_node_run = await self._parent(store, project)

        async def always_fails(run_id: str, *, node_id: str) -> Any:
            raise RunIntegrityError("injected: store unavailable")

        store.create_node_run = always_fails  # type: ignore[method-assign]

        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
        result = await node.run(
            {"from_agent": "planner", "task": "research X", "to_agent": "researcher"},
            _ctx(run_id=parent.run_id, node_run_id=parent_node_run.node_run_id),
        )

        assert result.status == "failed"
        assert result.error_code == "RunIntegrityError"
        children = [
            run
            for run in store._runs.values()
            if run.parent_run_id == parent.run_id  # type: ignore[attr-defined]
        ]
        assert len(children) == 1
        leftover = children[0]
        assert leftover.status is RunStatus.CREATED, (
            "an interrupted reservation rests in CREATED, not in QUEUED-with-no-evidence"
        )
        assert leftover.provenance.get("a2a_task_id", "") == ""
        assert await store.list_node_runs(leftover.run_id) == []

    async def test_a_crashed_replicas_partial_child_is_completed_and_answerable(
        self,
    ) -> None:
        """Recoverability, not just non-repetition. A replica that died between
        the child Run row and its evidence leaves a durable partial; the next
        dispatch through this node completes it — `a2a_delegation` has no
        consumer by design (ADR-082426-6201), so this visit is the recovery
        path — and the resumed answer settles the healed child.
        """
        store, _projects, project = await _spine()
        parent, parent_node_run = await self._parent(store, project)
        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
        inputs = DelegateRemoteIn(from_agent="planner", task="research X", to_agent="researcher")
        ctx = _ctx(run_id=parent.run_id, node_run_id=parent_node_run.node_run_id)

        # What a crashed replica leaves behind: the child Run row, durable and
        # keyed, with none of its canonical evidence.
        child = await store.create_run(
            node._child_graph(inputs, parent=parent, target="researcher"),
            parent_run_id=parent.run_id,
            parent_node_run_id=parent_node_run.node_run_id,
            provenance={
                "admission_source": "a2a_delegation",
                "delegation_key": node._delegation_key(inputs, ctx),
                "delegation_mode": "in_process",
            },
        )

        first = await node.run(inputs, ctx)

        assert first.status == "paused", first.error_message
        healed = await store.get_run(child.run_id)
        assert healed is not None
        node_runs = await store.list_node_runs(child.run_id)
        assert len(node_runs) == 1
        attempts = await store.list_attempts(node_runs[0].node_run_id)
        assert [attempt.status.value for attempt in attempts] == ["yielded"]
        assert healed.provenance["a2a_task_id"] == first.metadata["task_id"]

        answered = await node.run(
            inputs,
            ctx.model_copy(
                update={
                    "metadata": {
                        "hitl_answers": {
                            "delegate-1": {
                                "status": "completed",
                                "task_id": first.metadata["task_id"],
                                "result": "ok",
                                "_pause": {"run_id": child.run_id},
                            }
                        }
                    }
                }
            ),
        )

        assert answered.output.status == "completed"
        settled = await store.get_run(child.run_id)
        assert settled is not None
        assert settled.status.value == "completed"

    async def test_the_child_row_is_admitted_created_and_only_parks_with_evidence(
        self,
    ) -> None:
        """Pins the ordering that closes the unrecoverable window: the child Run
        becomes durable in CREATED — the recovery model's resting state for a
        projection — and reaches WAITING only through its yielded Attempt,
        never through a QUEUED row with no NodeRun.
        """
        store, _projects, project = await _spine()
        parent, parent_node_run = await self._parent(store, project)
        real_create_run = store.create_run
        admitted_as: list[str] = []

        async def spy_create_run(graph: Any, **kwargs: Any) -> Any:
            run = await real_create_run(graph, **kwargs)
            if run.parent_run_id == parent.run_id:
                admitted_as.append(run.status.value)
            return run

        store.create_run = spy_create_run  # type: ignore[method-assign]

        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=store)
        result = await node.run(
            {"from_agent": "planner", "task": "research X", "to_agent": "researcher"},
            _ctx(run_id=parent.run_id, node_run_id=parent_node_run.node_run_id),
        )

        assert result.status == "paused", result.error_message
        assert admitted_as == ["created"], (
            "the child row must be durable in CREATED before its evidence exists"
        )
        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        assert child.status.value == "waiting"
        assert len(await store.list_node_runs(child.run_id)) == 1


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
    def _peers(
        status: str = "submitted",
        error: str | None = None,
        task_id: str = "remote-1",
    ) -> GuestPeerManager:
        guest_peers = GuestPeerManager()
        guest_peers.delegate = AsyncMock(  # type: ignore[method-assign]
            return_value=DelegationResult(
                task_id=task_id, peer_name="hub", status=status, error=error
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

    async def test_cross_instance_transport_and_child_admission_are_one_path(self) -> None:
        """Exercise the node through GuestPeerManager's real HTTP seam."""
        store, _projects, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        parent_node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["json"] = request.content
            return httpx.Response(200, json={"task_id": "http-remote-1"})

        set_test_transport(httpx.MockTransport(handler))
        peers = GuestPeerManager()
        peers.register_peer(PeerTrust(peer_url="http://hub", peer_name="hub"))
        node = AgentDelegateRemoteNode(guest_peers=peers, run_store=store)

        result = await node.run(
            {"from_agent": "planner", "task": "research X", "peer_name": "hub"},
            _ctx(run_id=parent.run_id, node_run_id=parent_node_run.node_run_id),
        )

        assert result.status == "paused"
        assert seen["url"] == "http://hub/a2a/tasks/create"
        assert b'"agent_id":"planner"' in seen["json"]
        assert b'"content":"research X"' in seen["json"]
        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        assert child.parent_run_id == parent.run_id
        assert child.parent_node_run_id == parent_node_run.node_run_id
        assert child.provenance["a2a_task_id"] == "http-remote-1"

    async def test_the_cross_instance_answer_completes_the_child_attempt(self) -> None:
        """A peer answer settles canonical evidence, not the Run directly."""
        store, _projects, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        parent_node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
        node = AgentDelegateRemoteNode(guest_peers=self._peers(), run_store=store)
        first = await node.run(
            {"from_agent": "planner", "task": "research X", "peer_name": "hub"},
            _ctx(run_id=parent.run_id, node_run_id=parent_node_run.node_run_id),
        )
        child_run_id = first.metadata["run_id"]

        await node.run(
            {"from_agent": "planner", "task": "research X", "peer_name": "hub"},
            _ctx(
                run_id=parent.run_id,
                node_run_id=parent_node_run.node_run_id,
            ).model_copy(
                update={
                    "metadata": {
                        "hitl_answers": {
                            "delegate-1": {
                                "status": "completed",
                                "task_id": "remote-1",
                                "result": "ok",
                                "_pause": {"run_id": child_run_id},
                            }
                        }
                    }
                }
            ),
        )

        child = await store.get_run(child_run_id)
        assert child is not None
        assert child.status.value == "completed"
        node_runs = await store.list_node_runs(child_run_id)
        assert len(node_runs) == 1
        attempts = await store.list_attempts(node_runs[0].node_run_id)
        assert [attempt.status.value for attempt in attempts] == ["yielded", "completed"]

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

    async def test_a_submitted_peer_response_without_a_receipt_pauses_for_reconciliation(
        self,
    ) -> None:
        """An uncertain transport keeps its reserved child and polls for its receipt."""
        store, _projects, project = await _spine()
        parent = await store.create_run(
            _graph(workspace_id="workspace-1", project_id=project.project_id)
        )
        parent_node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")

        node = AgentDelegateRemoteNode(guest_peers=self._peers(task_id=""), run_store=store)
        result = await node.run(
            {"from_agent": "planner", "task": "research X", "peer_name": "hub"},
            _ctx(run_id=parent.run_id, node_run_id=parent_node_run.node_run_id),
        )

        assert result.status == "paused"
        assert result.metadata["paused_reason"] == "awaiting_delegation_reconciliation"
        child = await store.get_run(result.metadata["child_run_id"])
        assert child is not None
        assert child.parent_run_id == parent.run_id
        assert child.provenance["a2a_task_id"] == ""

    async def test_durable_parent_resumes_from_the_answer_and_settles_child(self) -> None:
        """The production checkpoint can accept the remote answer.

        ``awaiting_remote_delegation`` is answer-gated, not a timer/poll. The
        parent therefore parks PAUSED, allowing the canonical durable answer
        path to stamp the server-owned child ``run_id`` and queue the parent.
        """
        run_store, _projects, project = await _spine()
        graph = Graph(
            workspace_id="workspace-1",
            project_id=project.project_id,
            name="Delegating pipeline",
            nodes=[
                Node(
                    node_id="delegate-1",
                    node_type="agent.delegate_remote",
                    inputs={
                        "from_agent": "planner",
                        "task": "research X",
                        "to_agent": "researcher",
                    },
                )
            ],
        )
        parent = await run_store.create_run(graph)
        await run_store.transition_run(parent.run_id, RunStatus.QUEUED)
        durable = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
        node = AgentDelegateRemoteNode(a2a_delegator=_delegator(), run_store=run_store)

        def resolver(_node_id: str, _graph: Graph) -> AgentDelegateRemoteNode:
            return node

        started = await run_durable_graph(
            graph,
            store=durable,
            node_resolver=resolver,
            run_id=parent.run_id,
            run_store=run_store,
        )

        assert started.status is RunStatus.PAUSED
        pause = started.graph_state.metadata["pauses"]["delegate-1"]
        child_run_id = pause["metadata"]["run_id"]
        assert child_run_id
        child = await run_store.get_run(child_run_id)
        assert child is not None
        assert child.parent_run_id == parent.run_id

        answered = await durable.submit_hitl_answer(
            parent.run_id,
            "delegate-1",
            {"status": "completed", "task_id": pause["metadata"]["task_id"], "result": "ok"},
        )
        assert answered.status is RunStatus.QUEUED
        assert answered.hitl_answers["delegate-1"]["_pause"]["metadata"]["run_id"] == child_run_id
        resumed = await resume_durable_graph(
            parent.run_id,
            store=durable,
            node_resolver=resolver,
            run_store=run_store,
        )

        assert resumed.status is RunStatus.COMPLETED
        parent_nodes = await run_store.list_node_runs(parent.run_id)
        parent_attempts = await run_store.list_attempts(parent_nodes[0].node_run_id)
        settled_child = await run_store.get_run(child_run_id)
        assert settled_child is not None
        child_nodes = await run_store.list_node_runs(child_run_id)
        child_attempts = await run_store.list_attempts(child_nodes[0].node_run_id)
        assert len(parent_attempts) == 2, (
            [(attempt.status, attempt.result) for attempt in parent_attempts],
            resumed,
        )
        assert parent_nodes[0].result["run_id"] == child_run_id
        assert len(child_attempts) == 2, (
            [(attempt.status, attempt.result) for attempt in child_attempts],
            [(node.status, node.result) for node in parent_nodes],
            resumed,
        )
        assert settled_child.status is RunStatus.COMPLETED, (
            settled_child.status,
            [(node.node_run_id, node.status, node.accepted_outcome) for node in child_nodes],
            [(attempt.status, attempt.result) for attempt in child_attempts],
            [(node.status, node.result) for node in parent_nodes],
            [(attempt.status, attempt.result) for attempt in parent_attempts],
        )
        assert settled_child.result == "ok"
