"""External Agent delegation is bound to canonical identity and evidence.

Issue #959 (M9-D2): every external Agent call is a governed delegation
attributable to the canonical caller, the Workspace scope, the delegated
Goal/Subgoal context, the dispatching Run/NodeRun/Attempt, and one canonical
Invocation; delegated authority never exceeds the declared ceiling; remote
Agent-generated ids stay receipts; result provenance survives storage.

These tests drive the real node against a real `GuestPeerManager` transport
(mocked HTTP) and the real governed Invocation seam.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from maistro.a2a.delegate import A2ADelegator
from maistro.a2a.guest_peers import DelegationResult, GuestPeerManager, PeerTrust
from maistro.capabilities.approval_store import InMemoryApprovalStore
from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import new_effect_context
from maistro.capabilities.governed_invocation import InvocationDenied
from maistro.capabilities.invocation import Invocation, InvocationStatus
from maistro.graph import Graph, Node
from maistro.graph.nodes import NodeContext
from maistro.graph.nodes.agent_delegate_remote import (
    AGENT_DELEGATION_CAPABILITY,
    AgentDelegateRemoteNode,
    DelegationContextError,
    DelegationNotConfiguredError,
)
from maistro.graph.nodes.base import replay_effect_key
from maistro.http import set_test_transport
from maistro.policy.types import Decision, PolicyVerdict
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

from ._delegation_governance import delegation_effects, guest_peers_with_hub


async def _spine() -> tuple[InMemoryRunStore, Any]:
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("workspace-1")
    project = await project_store.create(
        workspace_id="workspace-1", parent_project_id=root.project_id, name="Project"
    )
    return InMemoryRunStore(project_store=project_store), project


def _graph(project_id: str) -> Graph:
    return Graph(
        workspace_id="workspace-1",
        project_id=project_id,
        name="Delegating pipeline",
        nodes=[Node(node_id="delegate-1", node_type="agent.delegate_remote")],
    )


def _ctx(run_id: str, node_run_id: str, project_id: str) -> NodeContext:
    return NodeContext(
        run_id=run_id,
        dag_id="dag-1",
        node_id="delegate-1",
        node_run_id=node_run_id,
        attempt_id="attempt-1",
        workspace_id="workspace-1",
        project_id=project_id,
    )


async def _parent_and_ctx(store: InMemoryRunStore, project_id: str) -> tuple[NodeContext, Any]:
    parent = await store.create_run(
        _graph(project_id), actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
    return _ctx(parent.run_id, node_run.node_run_id, project_id), parent


def _inputs(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "from_agent": "planner",
        "task": "research X",
        "peer_name": "hub",
        "binding_id": "binding-hub",
    }
    values.update(overrides)
    return values


async def _governed_node(
    store: InMemoryRunStore,
    project_id: str,
    *,
    real_transport: bool = False,
) -> AgentDelegateRemoteNode:
    """The governed node. By default the transport seam returns an accepted
    dispatch; tests that assert on the HTTP bytes pass `real_transport` and
    install their own handler."""
    peers = guest_peers_with_hub()
    if not real_transport:
        peers.delegate = AsyncMock(  # type: ignore[method-assign]
            return_value=DelegationResult(
                task_id="remote-1",
                peer_name="hub",
                status="submitted",
                peer_url="http://hub",
            )
        )
    return AgentDelegateRemoteNode(
        guest_peers=peers,
        run_store=store,
        effect_context=await delegation_effects(workspace_id="workspace-1", project_id=project_id),
    )


async def _dispatch_invocations(
    node: AgentDelegateRemoteNode, run_id: str, key: str
) -> list[Invocation]:
    """The canonical Invocation rows for one delegation effect identity."""
    assert node._effects is not None
    binding = await node._effects.bindings.get("binding-hub")
    assert isinstance(binding, Binding)
    return await node._effects.invocation_store.list_effect(
        run_id=run_id,
        node_run_id=None,
        binding_id=binding.binding_id,
        effect_key=key,
    )


def _children_of(store: InMemoryRunStore, run_id: str) -> list[Any]:
    return [run for run in store._runs.values() if run.parent_run_id == run_id]  # type: ignore[attr-defined]


class TestNoExternalCallWithoutCanonicalCallerAndScope:
    """Acceptance: no external Agent call can occur without a canonical
    caller and Workspace scope."""

    async def test_a_node_without_the_effect_authority_refuses_the_dispatch(self) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = AgentDelegateRemoteNode(guest_peers=guest_peers_with_hub(), run_store=store)

        result = await node.run(_inputs(), ctx)

        assert result.success is False
        assert result.error_code == DelegationNotConfiguredError.__name__
        assert _children_of(store, ctx.run_id) == [], "an ungovernable dispatch files no work"

    async def test_a_dispatch_without_a_binding_is_refused_before_anything(self) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id)

        result = await node.run(_inputs(binding_id=""), ctx)

        assert result.success is False
        assert result.error_code == BindingNotFound.__name__

    async def test_a_dispatch_the_binding_store_does_not_know_is_refused(self) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id)

        result = await node.run(_inputs(binding_id="binding-unknown"), ctx)

        assert result.success is False
        assert result.error_code == BindingNotFound.__name__

    async def test_a_store_less_construction_refuses_rather_than_inventing_identity(
        self,
    ) -> None:
        """No run store means no canonical caller to name. The old behavior
        dispatched anyway with whatever the graph inputs claimed; the
        governed node refuses instead."""
        node = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(),
            effect_context=await delegation_effects(
                workspace_id="workspace-1", project_id="project-1"
            ),
        )
        ctx = NodeContext(
            run_id="run-1",
            dag_id="dag-1",
            node_id="delegate-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
        )

        result = await node.run(_inputs(), ctx)

        assert result.success is False
        assert result.error_code == DelegationContextError.__name__

    async def test_a_dispatch_without_a_delegating_agent_is_refused(self) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id)

        result = await node.run(_inputs(from_agent=""), ctx)

        assert result.success is False
        assert result.error_code == DelegationContextError.__name__

    async def test_the_transport_refuses_a_context_less_call_even_when_wired(self) -> None:
        """The boundary itself enforces the rule, so a caller that bypassed
        the node still cannot reach a peer unattributed."""
        peers = guest_peers_with_hub()
        result = await peers.delegate("hub", "planner", [{"role": "user", "content": "x"}])
        assert result.status == "rejected"
        assert "canonical caller" in (result.error or "")

    async def test_an_inactive_peer_is_refused_before_admission(self) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(active=False),
            run_store=store,
            effect_context=await delegation_effects(
                workspace_id="workspace-1", project_id=project.project_id
            ),
        )

        result = await node.run(_inputs(), ctx)

        assert result.status == "completed"
        assert result.output is not None
        assert result.output.status == "rejected"
        assert result.output.error == "peer inactive"
        assert _children_of(store, ctx.run_id) == []

    async def test_the_admitted_call_carries_caller_and_scope_to_the_peer(self) -> None:
        """Acceptance has a positive half: the canonical caller and the
        Workspace/Project scope ride the request that does go out."""
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"task_id": "remote-1"})

        set_test_transport(httpx.MockTransport(handler))
        store, project = await _spine()
        ctx, parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id, real_transport=True)

        result = await node.run(_inputs(), ctx)

        assert result.status == "paused"
        sent = seen["body"]["delegation_context"]
        assert sent["caller_principal_id"] == DEFAULT_TEST_ACTOR_PRINCIPAL_ID
        assert sent["workspace_id"] == "workspace-1"
        assert sent["project_id"] == project.project_id
        assert sent["run_id"] == parent.run_id
        assert sent["node_run_id"] == ctx.node_run_id
        assert sent["delegating_agent"] == "planner"


class TestRefusedAdmissionCannotStrandAClaimedDispatch:
    """Admission decides whether a *new* dispatch may start. A previous
    visit's claimed effect is settled by the recovery paths even when the
    peer is later disabled or its ceiling tightened -- a refusal by current
    configuration must never strand a possibly-accepted remote effect, and
    must never be reported as a peer decline."""

    async def test_a_claimed_dispatch_recovers_when_the_peer_is_later_disabled(
        self,
    ) -> None:
        """The first POST's outcome was lost (claimed, no receipt); the peer
        was then disabled. The retry enters reconciliation -- it does not
        report a normal rejection over work that may already be running, and
        it never re-POSTs."""
        posts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                posts["n"] += 1
                raise httpx.ConnectError("connection lost after send")
            return httpx.Response(405)

        set_test_transport(httpx.MockTransport(handler))
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        first = await (await _governed_node(store, project.project_id, real_transport=True)).run(
            _inputs(), ctx
        )
        assert first.status == "paused"
        assert first.metadata["paused_reason"] == "awaiting_delegation_reconciliation"
        child = await store.get_run(first.metadata["child_run_id"])
        assert child is not None
        assert child.provenance["transport_attempted"] is True
        assert not child.provenance.get("a2a_task_id")

        retry = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(active=False),
            run_store=store,
            effect_context=await delegation_effects(
                workspace_id="workspace-1", project_id=project.project_id
            ),
        )
        second = await retry.run(_inputs(), ctx)

        assert second.status == "paused"
        assert second.metadata["paused_reason"] == "awaiting_delegation_reconciliation"
        assert posts["n"] == 1, "an uncertain dispatch is settled by polling, never re-POSTed"
        still_there = await store.get_run(child.run_id)
        assert still_there is not None, "claimed work is not discarded behind a refusal"

    async def test_a_durable_receipt_pauses_the_delegation_when_the_peer_is_disabled(
        self,
    ) -> None:
        """A receipt is durable acceptance: a retry whose peer went inactive
        after the dispatch pauses on the recorded receipt so the answer can
        still settle the child, instead of rejecting accepted work."""
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        first = await (await _governed_node(store, project.project_id)).run(_inputs(), ctx)
        assert first.status == "paused"
        child = await store.get_run(first.metadata["run_id"])
        assert child is not None
        assert child.provenance["a2a_task_id"] == "remote-1"

        retry = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(active=False),
            run_store=store,
            effect_context=await delegation_effects(
                workspace_id="workspace-1", project_id=project.project_id
            ),
        )
        second = await retry.run(_inputs(), ctx)

        assert second.status == "paused"
        assert second.metadata["paused_reason"] == "awaiting_remote_delegation"
        assert second.metadata["task_id"] == "remote-1"
        assert second.metadata["run_id"] == child.run_id

    async def test_an_unclaimed_reservation_is_released_when_admission_later_refuses(
        self,
    ) -> None:
        """A reservation whose boundary was never crossed has no remote
        effect: the refusal owns it, so the child is released and the
        rejection stands -- a repaired retry dispatches fresh instead of
        reconciling work that provably never started."""
        store, project = await _spine()
        ctx, parent = await _parent_and_ctx(store, project.project_id)
        crash = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(),
            run_store=store,
            effect_context=await delegation_effects(
                workspace_id="workspace-1", project_id=project.project_id
            ),
        )
        await crash._reserve_child(
            crash.input_schema.model_validate(_inputs()),
            ctx,
            parent=parent,
            mode="guest_peer",
            target="hub",
        )
        assert _children_of(store, ctx.run_id)

        retry = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(active=False),
            run_store=store,
            effect_context=await delegation_effects(
                workspace_id="workspace-1", project_id=project.project_id
            ),
        )
        result = await retry.run(_inputs(), ctx)

        assert result.status == "completed"
        assert result.output is not None
        assert result.output.status == "rejected"
        assert result.output.error == "peer inactive"
        assert _children_of(store, ctx.run_id) == [], (
            "an unclaimed reservation must not survive a refusal as canonical "
            "evidence implying remote work"
        )
        key = retry._delegation_key(retry.input_schema.model_validate(_inputs()), ctx)
        assert await store.find_delegation_run(key) is None


class TestDelegatedAuthorityIsAttenuated:
    """Acceptance: delegated authority cannot exceed caller/host/Workspace
    policy."""

    async def test_a_scope_claim_beyond_the_peer_ceiling_is_refused(self) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(allowed_scopes=("web.read",)),
            run_store=store,
            effect_context=await delegation_effects(
                workspace_id="workspace-1", project_id=project.project_id
            ),
        )

        result = await node.run(_inputs(delegated_scopes=("web.read", "shell.exec")), ctx)

        assert result.status == "completed"
        assert result.output is not None
        assert result.output.status == "rejected"
        assert "shell.exec" in (result.output.error or "")
        assert _children_of(store, ctx.run_id) == [], "a refused authority files no execution"

    async def test_any_scope_claim_against_an_undeclared_ceiling_is_refused(self) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id)

        result = await node.run(_inputs(delegated_scopes=("web.read",)), ctx)

        assert result.output is not None
        assert result.output.status == "rejected"

    async def test_a_scope_claim_within_the_ceiling_is_narrowed_onto_the_request(
        self,
    ) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"task_id": "remote-1"})

        set_test_transport(httpx.MockTransport(handler))
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(allowed_scopes=("web.read", "extra.scope")),
            run_store=store,
            effect_context=await delegation_effects(
                workspace_id="workspace-1", project_id=project.project_id
            ),
        )

        result = await node.run(_inputs(delegated_scopes=("web.read",)), ctx)

        assert result.status == "paused"
        assert seen["body"]["delegation_context"]["delegated_scopes"] == ["web.read"]

    async def test_a_binding_pinned_to_another_provider_cannot_be_widened(self) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(),
            run_store=store,
            effect_context=await delegation_effects(
                workspace_id="workspace-1",
                project_id=project.project_id,
                provider_name="some-other-peer",
            ),
        )

        result = await node.run(_inputs(), ctx)

        assert result.success is False
        assert result.error_code == "CapabilityUnavailable"
        assert "some-other-peer" in (result.error_message or "")
        assert _children_of(store, ctx.run_id) == [], (
            "a refusal this instance owns releases the reservation: the child "
            "must not survive as a canonical Run implying remote work, and its "
            "spent transport claim would otherwise send every retry to "
            "reconcile a dispatch that provably never started"
        )

    async def test_a_policy_denial_stops_the_dispatch_before_the_transport(self) -> None:
        posts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            posts["n"] += 1
            return httpx.Response(200, json={"task_id": "remote-1"})

        set_test_transport(httpx.MockTransport(handler))
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)

        async def deny(_binding: Any, _request: Any, _context: Any) -> PolicyVerdict:
            return PolicyVerdict(Decision.DENY, reason="delegation paused", rule="test")

        effects = new_effect_context(policy_evaluator=deny)
        await effects.bindings.put(
            Binding(
                binding_id="binding-hub",
                workspace_id="workspace-1",
                project_id=project.project_id,
                capability=AGENT_DELEGATION_CAPABILITY,
            )
        )
        node = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(),
            run_store=store,
            effect_context=effects,
        )

        result = await node.run(_inputs(), ctx)

        assert result.success is False
        assert result.error_code == InvocationDenied.__name__
        assert posts["n"] == 0, "a denied authority never reaches the peer"

    async def test_a_repaired_retry_claims_a_fresh_transport_attempt(self) -> None:
        """After a pre-transport refusal released the reservation, a retry
        dispatches instead of reconciling work that never started.

        The first visit fails on a binding pinned to another provider; the
        operator repairs the binding and the same Run re-enters the node.
        A retained child would carry its spent transport claim, forcing this
        retry to reconcile a dispatch that provably never started (parking
        until the delegation timeout); a released one lets the dispatch
        proceed immediately.
        """
        posts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            posts["n"] += 1
            return httpx.Response(200, json={"task_id": "remote-1"})

        set_test_transport(httpx.MockTransport(handler))
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)

        mispinned = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(),
            run_store=store,
            effect_context=await delegation_effects(
                workspace_id="workspace-1",
                project_id=project.project_id,
                provider_name="some-other-peer",
            ),
        )
        refused = await mispinned.run(_inputs(), ctx)
        assert refused.success is False
        assert refused.error_code == "CapabilityUnavailable"
        assert _children_of(store, ctx.run_id) == []

        repaired = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(),
            run_store=store,
            effect_context=await delegation_effects(
                workspace_id="workspace-1", project_id=project.project_id
            ),
        )
        result = await repaired.run(_inputs(), ctx)

        assert result.status == "paused"
        assert posts["n"] == 1, "the retry dispatched fresh instead of reconciling"

    async def test_a_require_approval_policy_parks_on_the_human_pause(self) -> None:
        """A manageable approval decision is a durable HITL pause -- the same
        primitive every other governed effect pauses on -- never a
        reconciliation park and never a dispatch."""
        posts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            posts["n"] += 1
            return httpx.Response(200, json={"task_id": "remote-1"})

        set_test_transport(httpx.MockTransport(handler))
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)

        async def require_approval(_binding: Any, _request: Any, _context: Any) -> PolicyVerdict:
            return PolicyVerdict(
                Decision.REQUIRE_APPROVAL, reason="delegation needs a human", rule="test"
            )

        effects = new_effect_context(
            policy_evaluator=require_approval,
            approval_store=InMemoryApprovalStore(),
        )
        await effects.bindings.put(
            Binding(
                binding_id="binding-hub",
                workspace_id="workspace-1",
                project_id=project.project_id,
                capability=AGENT_DELEGATION_CAPABILITY,
            )
        )
        node = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(),
            run_store=store,
            effect_context=effects,
        )

        result = await node.run(_inputs(), ctx)

        assert result.status == "paused"
        assert result.metadata["paused_reason"] == "awaiting_human_approval"
        assert result.metadata["effect_key"]
        assert posts["n"] == 0

    async def test_an_approved_delegation_dispatches_instead_of_reconciling(self) -> None:
        """The transport boundary is claimed by the executor, not the visit.

        An approval pause must leave the boundary unclaimed: the post-approval
        resume crosses it -- a fresh POST -- rather than finding a spent claim
        with no Invocation and parking the approved delegation on a
        reconciliation loop until timeout.
        """
        posts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            posts["n"] += 1
            return httpx.Response(200, json={"task_id": "remote-1"})

        set_test_transport(httpx.MockTransport(handler))
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)

        async def require_approval(_binding: Any, _request: Any, context: Any) -> PolicyVerdict:
            # The real engine's shape: a human approval satisfies the
            # REQUIRE_APPROVAL rule, so the approved re-run is ALLOW.
            if getattr(context, "approved", False):
                return PolicyVerdict(Decision.ALLOW, rule="test")
            return PolicyVerdict(
                Decision.REQUIRE_APPROVAL, reason="delegation needs a human", rule="test"
            )

        effects = new_effect_context(
            policy_evaluator=require_approval,
            approval_store=InMemoryApprovalStore(),
        )
        await effects.bindings.put(
            Binding(
                binding_id="binding-hub",
                workspace_id="workspace-1",
                project_id=project.project_id,
                capability=AGENT_DELEGATION_CAPABILITY,
            )
        )
        node = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(),
            run_store=store,
            effect_context=effects,
        )

        first = await node.run(_inputs(), ctx)
        assert first.metadata["paused_reason"] == "awaiting_human_approval"
        assert posts["n"] == 0
        assert effects.approval_store is not None
        await effects.approval_store.resolve(
            str(first.metadata["approval_request_id"]), approved=True, actor="human-1"
        )

        second = await node.run(_inputs(), ctx)

        assert posts["n"] == 1, "the approved delegation dispatched instead of reconciling"
        assert second.status == "paused"
        assert second.metadata["paused_reason"] == "awaiting_remote_delegation"
        assert second.metadata["task_id"] == "remote-1"

    async def test_an_unmanageable_approval_requirement_fails_the_node(self) -> None:
        """No approval store wired: the instance cannot manage the decision,
        so the node fails instead of parking work on a loop nobody answers."""
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)

        async def require_approval(_binding: Any, _request: Any, _context: Any) -> PolicyVerdict:
            return PolicyVerdict(Decision.REQUIRE_APPROVAL, reason="needs a human", rule="test")

        effects = new_effect_context(policy_evaluator=require_approval)
        await effects.bindings.put(
            Binding(
                binding_id="binding-hub",
                workspace_id="workspace-1",
                project_id=project.project_id,
                capability=AGENT_DELEGATION_CAPABILITY,
            )
        )
        node = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(),
            run_store=store,
            effect_context=effects,
        )

        result = await node.run(_inputs(), ctx)

        assert result.success is False
        assert result.error_code == "InvocationApprovalRequired"


class TestEveryRemoteExecutionIsTraceable:
    """Acceptance: every remote execution is traceable from canonical
    Goal/Run evidence."""

    async def test_the_child_run_carries_the_full_identity_binding(self) -> None:
        store, project = await _spine()
        ctx, parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id)

        result = await node.run(
            _inputs(goal_id="goal-1", goal_revision=2, subgoal_of="goal-0"), ctx
        )

        assert result.status == "paused"
        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        binding = child.provenance["delegation_context"]
        assert binding["caller_principal_id"] == DEFAULT_TEST_ACTOR_PRINCIPAL_ID
        assert binding["workspace_id"] == parent.workspace_id
        assert binding["project_id"] == parent.project_id
        assert binding["run_id"] == parent.run_id
        assert binding["node_run_id"] == ctx.node_run_id
        assert binding["delegation_key"] == child.provenance["delegation_key"]
        assert binding["goal_id"] == "goal-1"
        assert binding["goal_revision"] == 2
        assert binding["subgoal_of"] == "goal-0"

    async def test_a_goal_binding_requires_its_revision(self) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id)

        result = await node.run(_inputs(goal_id="goal-1"), ctx)

        assert result.success is False
        assert result.error_code == DelegationContextError.__name__

    async def test_the_in_process_child_carries_the_binding_too(self) -> None:
        store, project = await _spine()
        ctx, parent = await _parent_and_ctx(store, project.project_id)
        delegator = A2ADelegator()
        delegator.register_agent_capability("planner", ["researcher"])
        node = AgentDelegateRemoteNode(a2a_delegator=delegator, run_store=store)

        result = await node.run(
            {"from_agent": "planner", "task": "x", "to_agent": "researcher"}, ctx
        )

        assert result.status == "paused"
        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        binding = child.provenance["delegation_context"]
        assert binding["caller_principal_id"] == DEFAULT_TEST_ACTOR_PRINCIPAL_ID
        assert binding["run_id"] == parent.run_id


class TestRemoteEffectsFollowInvocationRules:
    """Acceptance: remote side effects follow canonical Invocation
    retry/idempotency rules."""

    async def test_the_dispatch_is_one_governed_invocation_on_the_canonical_ledger(
        self,
    ) -> None:
        store, project = await _spine()
        ctx, parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id)

        result = await node.run(_inputs(), ctx)

        assert result.status == "paused"
        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        key = child.provenance["delegation_key"]
        history = await _dispatch_invocations(node, parent.run_id, key)
        assert len(history) == 1
        invocation = history[0]
        assert invocation.status is InvocationStatus.COMPLETED
        assert invocation.effect_key == key, "the effect identity is the delegation key"
        assert invocation.run_id == parent.run_id
        assert invocation.node_run_id == ctx.node_run_id
        assert invocation.attempt_id == ctx.attempt_id
        assert invocation.workspace_id == parent.workspace_id
        assert invocation.actor_id == DEFAULT_TEST_ACTOR_PRINCIPAL_ID
        assert invocation.binding.capability == AGENT_DELEGATION_CAPABILITY
        assert invocation.binding.provider_name == "hub"
        assert invocation.request["delegation_context"]["run_id"] == parent.run_id
        assert invocation.result["task_id"] == "remote-1"

    async def test_a_transport_failure_lands_unknown_and_never_reposts_blindly(
        self,
    ) -> None:
        posts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                posts["n"] += 1
                raise httpx.ConnectError("connection lost after send")
            return httpx.Response(405)

        set_test_transport(httpx.MockTransport(handler))
        store, project = await _spine()
        ctx, parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id, real_transport=True)

        first = await node.run(_inputs(), ctx)
        assert first.status == "paused"
        assert first.metadata["paused_reason"] == "awaiting_delegation_reconciliation"

        child = await store.get_run(first.metadata["child_run_id"])
        assert child is not None
        history = await _dispatch_invocations(
            node, parent.run_id, child.provenance["delegation_key"]
        )
        assert [row.status for row in history] == [InvocationStatus.UNKNOWN]

        # The resume tick re-enters: an unresolved dispatch is never re-POSTed;
        # the node parks on reconciliation again.
        second = await node.run(_inputs(), ctx)
        assert second.status == "paused"
        assert second.metadata["paused_reason"] == "awaiting_delegation_reconciliation"
        assert posts["n"] == 1

    async def test_the_recovery_poll_settles_the_invocation_through_the_seam(
        self,
    ) -> None:
        calls = {"post": 0, "get": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                calls["post"] += 1
                raise httpx.ConnectError("connection lost after accept")
            if request.method == "GET":
                calls["get"] += 1
                return httpx.Response(200, json={"task_id": "remote-9"})
            return httpx.Response(405)

        set_test_transport(httpx.MockTransport(handler))
        peers = GuestPeerManager()
        peers.register_peer(
            PeerTrust(peer_url="http://hub", peer_name="hub", supports_idempotency=True)
        )
        store, project = await _spine()
        ctx, parent = await _parent_and_ctx(store, project.project_id)
        node = AgentDelegateRemoteNode(
            guest_peers=peers,
            run_store=store,
            effect_context=await delegation_effects(
                workspace_id="workspace-1", project_id=project.project_id
            ),
        )

        first = await node.run(_inputs(), ctx)
        assert first.metadata["paused_reason"] == "awaiting_delegation_reconciliation"

        second = await node.run(_inputs(), ctx)
        assert second.status == "paused"
        assert second.metadata["paused_reason"] == "awaiting_remote_delegation"
        assert calls == {"post": 1, "get": 1}

        child = await store.get_run(second.metadata["run_id"])
        assert child is not None
        history = await _dispatch_invocations(
            node, parent.run_id, child.provenance["delegation_key"]
        )
        assert [row.status for row in history] == [InvocationStatus.COMPLETED]
        assert history[0].result["task_id"] == "remote-9"
        assert child.provenance["a2a_task_id"] == "remote-9"

    async def test_a_crash_between_dispatch_and_pause_replays_the_invocation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A COMPLETED dispatch is the accepted effect: the next visit adopts
        its receipt without asking the transport again."""
        from maistro.graph.nodes import agent_delegate_remote as delegate_module

        posts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            posts["n"] += 1
            return httpx.Response(200, json={"task_id": "remote-7"})

        set_test_transport(httpx.MockTransport(handler))
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id, real_transport=True)

        def fail_pause(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("injected crash after dispatch")

        monkeypatch.setattr(delegate_module, "pause_until", fail_pause)
        first = await node.run(_inputs(), ctx)
        assert first.status == "failed"
        assert posts["n"] == 1

        monkeypatch.undo()
        second = await node.run(_inputs(), ctx)
        assert second.status == "paused"
        assert second.metadata["task_id"] == "remote-7"
        assert posts["n"] == 1, "the completed Invocation is the replay"

    @pytest.mark.parametrize("fresh_node_run", [False, True])
    async def test_a_crashed_running_dispatch_settles_from_the_peer_receipt(
        self, monkeypatch: pytest.MonkeyPatch, fresh_node_run: bool
    ) -> None:
        """A worker death after the peer accepted leaves the durable row
        RUNNING with dispatch_active=True. Recovery settles that row from the
        peer's receipt (with the staleness cutoff the evidence vouches for)
        instead of raising UnsafeEffectRetry on every recovery visit."""
        from maistro.graph.nodes import agent_delegate_remote as delegate_module

        calls = {"post": 0, "get": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                calls["post"] += 1
                return httpx.Response(200, json={"task_id": "remote-13"})
            if request.method == "GET":
                calls["get"] += 1
                return httpx.Response(200, json={"task_id": "remote-13"})
            return httpx.Response(405)

        set_test_transport(httpx.MockTransport(handler))
        store, project = await _spine()
        ctx, parent = await _parent_and_ctx(store, project.project_id)
        # One durable ledger across visits: the second visit is the new worker
        # recovering the row the crashed process left behind.
        effects = await delegation_effects(
            workspace_id="workspace-1", project_id=project.project_id
        )
        node = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(supports_idempotency=True),
            run_store=store,
            effect_context=effects,
        )
        real_execute = delegate_module.AgentDelegateRemoteNode._execute_peer_delegation

        async def die_after_peer_accept(
            self: AgentDelegateRemoteNode, provider: Any, request: Any, **kwargs: Any
        ) -> Any:
            # The real POST crosses the boundary and the peer accepts; the
            # worker then dies before the Invocation terminalizes.
            await real_execute(self, provider, request, **kwargs)
            raise KeyboardInterrupt("injected worker death after the peer accepted")

        monkeypatch.setattr(
            delegate_module.AgentDelegateRemoteNode,
            "_execute_peer_delegation",
            die_after_peer_accept,
        )
        with pytest.raises(KeyboardInterrupt):
            await node.run(_inputs(), ctx)
        monkeypatch.undo()

        history = await _dispatch_invocations(
            node,
            parent.run_id,
            (await store.get_run(_children_of(store, parent.run_id)[0].run_id)).provenance[
                "delegation_key"
            ],  # type: ignore[union-attr]
        )
        assert [row.status for row in history] == [InvocationStatus.RUNNING]
        assert history[0].dispatch_active is True

        # A fresh peer manager: the new worker holds no in-process receipt
        # memo, so recovery must query the peer for the idempotent receipt.
        recovered_node = AgentDelegateRemoteNode(
            guest_peers=guest_peers_with_hub(supports_idempotency=True),
            run_store=store,
            effect_context=effects,
        )
        recovery_ctx = ctx.model_copy(
            update={
                "node_run_id": "recovery-node-run" if fresh_node_run else ctx.node_run_id,
                "attempt_id": "recovery-attempt",
            }
        )
        recovered = await recovered_node.run(_inputs(), recovery_ctx)
        assert recovered.status == "paused"
        assert recovered.metadata["paused_reason"] == "awaiting_remote_delegation"
        assert recovered.metadata["task_id"] == "remote-13"
        assert calls == {"post": 1, "get": 1}, "the receipt query, never a re-POST"

        child = await store.get_run(recovered.metadata["run_id"])
        assert child is not None
        assert child.provenance["a2a_task_id"] == "remote-13"
        history = await _dispatch_invocations(
            node, parent.run_id, child.provenance["delegation_key"]
        )
        assert [row.status for row in history] == [InvocationStatus.COMPLETED]
        assert history[0].result["task_id"] == "remote-13"
        assert history[0].node_run_id == ctx.node_run_id
        assert history[0].attempt_id == ctx.attempt_id
        assert history[0].effect_scope == child.provenance["delegation_key"]

    async def test_a_retry_under_a_fresh_node_run_keeps_one_effect_identity(
        self,
    ) -> None:
        """The logical effect identity is (Run, Binding, effect key): a
        lease-loss retry under a new NodeRun reconciles against the same
        canonical row instead of double-dispatching."""
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"task_id": "remote-1"})

        set_test_transport(httpx.MockTransport(handler))
        store, project = await _spine()
        ctx, parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id, real_transport=True)

        first = await node.run(_inputs(), ctx)
        retry_ctx = ctx.model_copy(update={"node_run_id": "lease-loss-retry"})
        second = await node.run(_inputs(), retry_ctx)

        assert first.status == second.status == "paused"
        assert first.metadata["task_id"] == second.metadata["task_id"]
        child = await store.get_run(first.metadata["run_id"])
        assert child is not None
        history = await _dispatch_invocations(
            node, parent.run_id, child.provenance["delegation_key"]
        )
        assert len(history) == 1
        assert seen["body"]["delegation_context"]["delegation_key"] == history[0].effect_key


class TestRemoteIdsStayReceipts:
    """Acceptance: remote Agent-generated IDs never replace canonical
    Goal/Run/Invocation identity."""

    async def test_the_answer_cannot_redirect_the_outcome_onto_another_run(self) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id)

        first = await node.run(_inputs(), ctx)
        child_run_id = first.metadata["run_id"]

        ctx_with_answer = ctx.model_copy(
            update={
                "metadata": {
                    "hitl_answers": {
                        "delegate-1": {
                            "status": "completed",
                            "task_id": "remote-1",
                            "result": "ok",
                            # A forged identity in the answer: ignored.
                            "run_id": "somebody-elses-run",
                            "_pause": {"run_id": child_run_id},
                        }
                    }
                }
            }
        )
        resumed = await node.run(_inputs(), ctx_with_answer)

        assert resumed.output is not None
        assert resumed.output.run_id == child_run_id, (
            "the answered outcome settles the Run the pause named"
        )
        assert await store.get_run("somebody-elses-run") is None, "the forged id created nothing"

    async def test_the_remote_task_id_is_provenance_never_the_identity(self) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id)

        result = await node.run(_inputs(), ctx)

        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        assert child.run_id != "remote-1"
        assert child.provenance["a2a_task_id"] == "remote-1"
        # The canonical identity keys remain the ones the delegating side
        # minted; the receipt sits beside them.
        assert child.provenance["delegation_key"] == replay_effect_key(
            ctx, node.kind, node.input_schema.model_validate(_inputs()).model_dump(mode="json")
        )


class TestResultProvenanceSurvives:
    """Acceptance: result provenance survives storage, replay, and later
    extension/Agent version changes."""

    async def test_the_peer_endpoint_is_recorded_before_dispatch(self) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id)

        result = await node.run(_inputs(), ctx)

        child = await store.get_run(result.metadata["run_id"])
        assert child is not None
        assert child.provenance["a2a_peer_url"] == "http://hub"

    async def test_the_settling_attempt_evidence_carries_the_remote_provenance(
        self,
    ) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id)
        first = await node.run(_inputs(), ctx)
        child_run_id = first.metadata["run_id"]

        answered = ctx.model_copy(
            update={
                "metadata": {
                    "hitl_answers": {
                        "delegate-1": {
                            "status": "completed",
                            "task_id": "remote-1",
                            "result": "ok",
                            "remote_agent_version": "peer-agent 2.7.1",
                            "_pause": {"run_id": child_run_id},
                        }
                    }
                }
            }
        )
        await node.run(_inputs(), answered)

        node_runs = await store.list_node_runs(child_run_id)
        attempts = await store.list_attempts(node_runs[0].node_run_id)
        terminal = [a for a in attempts if a.status.value == "completed"]
        assert len(terminal) == 1
        evidence = terminal[0].result
        assert evidence["task_id"] == "remote-1"
        assert evidence["remote_agent_version"] == "peer-agent 2.7.1"
        assert evidence["peer_name"] == "hub"
        assert evidence["a2a_peer_url"] == "http://hub"

    async def test_an_answer_without_remote_version_records_no_placeholder(self) -> None:
        store, project = await _spine()
        ctx, _parent = await _parent_and_ctx(store, project.project_id)
        node = await _governed_node(store, project.project_id)
        first = await node.run(_inputs(), ctx)
        child_run_id = first.metadata["run_id"]

        answered = ctx.model_copy(
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
        )
        await node.run(_inputs(), answered)

        node_runs = await store.list_node_runs(child_run_id)
        attempts = await store.list_attempts(node_runs[0].node_run_id)
        terminal = [a for a in attempts if a.status.value == "completed"]
        assert "remote_agent_version" not in (terminal[0].result or {})
