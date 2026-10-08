"""Epic M9-D (#941): discovery and invocation compose without core modification.

The epic's first acceptance criterion — *"an external Agent can be discovered
and invoked without core source modification"* — is a composition claim: the
discovery half (``maistro.a2a.external``, #958) and the invocation half (the
governed ``agent.delegate_remote`` path, #959/#960) are tested separately, but
nothing yet proves they **compose**: that an operator can ingest an A2A-style
card, project it through policy, and then invoke *that discovered agent*
through the canonical delegation seam using only exported surfaces — no core
source edited, no second authority introduced.

These tests drive exactly that composition end to end against a real
external-style A2A implementation (its own state engine, its own wire
protocol, served over real httpx transport semantics):

1. **Discovered → eligible → invoked.** The card is ingested by
   ``ExternalAgentRegistry``, projected (clamped, provenance retained,
   availability-unknown), made eligible by a reported probe, registered as a
   peer *from the projection's own endpoint*, dispatched under an authorized
   ``agent_delegation`` Binding, and settled — with the remote Agent version
   from the discovered card surviving into the canonical Attempt evidence.
2. **Authority stays attenuated across both halves.** The projected card
   carries only the authorized subset of the declared surface; a broadening
   refresh is refused without policy approval; a scope claim beyond the
   peer's declared ceiling is refused before any bytes reach the peer; and a
   refused delegation files no child Run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from maistro.a2a.external import (
    EXTERNAL_PRIORITY_TIER,
    EXTERNAL_TRUST_TIER,
    AuthorityEscalationRefused,
    AvailabilityState,
    CapabilityAuthorization,
    ExternalAgentRegistry,
    RemoteAgentDescriptor,
    SpecialistProjection,
)
from maistro.a2a.guest_peers import GuestPeerManager, PeerTrust
from maistro.a2a.normalize import PROGRESS_HISTORY_KEY
from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import (
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.graph import Graph, Node
from maistro.graph.nodes import NodeContext
from maistro.graph.nodes.agent_delegate_remote import (
    AGENT_DELEGATION_CAPABILITY,
    AgentDelegateRemoteNode,
)
from maistro.http import override_transport
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore, RunStatus
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

_WORKSPACE = "workspace-1"
_PEER_BASE = "http://external-agent.test"
_CARD_URL = _PEER_BASE


def _clock() -> datetime:
    return datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# Operator-side policy: the only authority over external-specialist grants
# --------------------------------------------------------------------------


@dataclass
class OperatorPolicy:
    """A deployment's own projection policy — written out-of-core.

    Grants an explicit capability-token set, clamped to whatever the
    descriptor actually declares; broadening refreshes are refused unless the
    operator flips ``approve_broadening``.
    """

    capabilities: frozenset[str]
    policy_id_value: str = "operator-policy"
    approve_broadening: bool = False

    def policy_id(self) -> str:
        return self.policy_id_value

    def authorize(
        self, descriptor: RemoteAgentDescriptor, *, now: datetime
    ) -> CapabilityAuthorization:
        granted = frozenset(self.capabilities & descriptor.capabilities.surface())
        return CapabilityAuthorization(
            authorized=bool(granted),
            capabilities=granted,
            policy_id=self.policy_id(),
            decided_at=now,
        )

    def allows_refresh(
        self, current: RemoteAgentDescriptor, candidate: RemoteAgentDescriptor
    ) -> bool:
        return self.approve_broadening


def _card(**overrides: Any) -> dict[str, Any]:
    """An A2A-style card as an external publisher would serve it."""
    card: dict[str, Any] = {
        "name": "Deep Researcher",
        "version": "2.4.1",
        "url": _CARD_URL,
        "protocolVersion": "0.2.9",
        "description": "External research specialist",
        "provider": {"organization": "Example Labs"},
        "capabilities": {"streaming": True},
        "tools": ["web_search", "crawl"],
        "skills": [{"id": "literature-review"}],
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
    }
    card.update(overrides)
    return card


def _registry(**kwargs: Any) -> ExternalAgentRegistry:
    return ExternalAgentRegistry(clock=_clock, **kwargs)


async def _discovered_and_eligible(
    policy: OperatorPolicy, card: dict[str, Any]
) -> SpecialistProjection:
    """Discover a card, probe it available, and return the live projection."""
    registry = _registry(policy=policy)
    record = registry.register(json.dumps(card), source_url=_CARD_URL)
    assert record.availability.state is AvailabilityState.UNKNOWN
    registry.report_availability(record.descriptor.agent_id, available=True)
    return registry.project(record.descriptor.agent_id)


# --------------------------------------------------------------------------
# An external-style A2A Agent implementation (its own thing, again)
# --------------------------------------------------------------------------


class _ExternalResearchAgent:
    """A stateful poll-driven A2A peer with idempotent admission.

    Modeled on the conformance implementation: ``POST /a2a/tasks/create``
    (idempotent by ``idempotency_key``), ``GET
    /a2a/tasks/by-idempotency-key/{key}`` reconciliation, and a pollable
    ``GET /a2a/tasks/{id}`` status resource whose engine advances one script
    step per poll.
    """

    def __init__(self, script: list[str]) -> None:
        self.script = script
        self.creates = 0
        self._by_key: dict[str, str] = {}
        self._tasks: dict[str, dict[str, str]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/a2a/tasks/create":
            return self._create(request)
        if request.method == "GET" and path.startswith("/a2a/tasks/by-idempotency-key/"):
            task_id = self._by_key.get(path.rsplit("/", 1)[-1])
            if task_id is None:
                return httpx.Response(404, json={"detail": "unknown idempotency key"})
            return httpx.Response(200, json={"task_id": task_id})
        if request.method == "GET" and path.startswith("/a2a/tasks/"):
            return self._status(path.rsplit("/", 1)[-1])
        return httpx.Response(404, json={"detail": "not found"})

    def _create(self, request: httpx.Request) -> httpx.Response:
        self.creates += 1
        payload = json.loads(request.content)
        key = str(payload.get("idempotency_key") or "")
        existing = self._by_key.get(key)
        if existing is not None:
            return httpx.Response(202, json={"task_id": existing, "status": "submitted"})
        if not key:
            return httpx.Response(422, json={"detail": "idempotency key required"})
        task_id = f"ext-task-{self.creates}"
        self._by_key[key] = task_id
        self._tasks[task_id] = {"status": self.script[0]}
        return httpx.Response(202, json={"task_id": task_id, "status": "submitted"})

    def _status(self, task_id: str) -> httpx.Response:
        task = self._tasks.get(task_id)
        if task is None:
            return httpx.Response(404, json={"detail": "unknown task"})
        state = task["status"]
        if state in self.script and self.script.index(state) < len(self.script) - 1:
            task["status"] = self.script[self.script.index(state) + 1]
        return httpx.Response(200, json={"task_id": task_id, "status": state})


# --------------------------------------------------------------------------
# Canonical spine + governed invocation wiring (all exported surfaces)
# --------------------------------------------------------------------------


async def _spine() -> tuple[InMemoryRunStore, Any]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(_WORKSPACE)
    project = await projects.create(
        workspace_id=_WORKSPACE, parent_project_id=root.project_id, name="Project"
    )
    return InMemoryRunStore(project_store=projects), project


def _graph(project_id: str) -> Graph:
    return Graph(
        workspace_id=_WORKSPACE,
        project_id=project_id,
        name="Delegating pipeline",
        nodes=[Node(node_id="delegate-1", node_type="agent.delegate_remote")],
    )


def _ctx(run_id: str, node_run_id: str, answer: dict[str, Any] | None = None) -> NodeContext:
    metadata: dict[str, Any] = {}
    if answer is not None:
        metadata["hitl_answers"] = {"delegate-1": answer}
    return NodeContext(
        run_id=run_id,
        dag_id="dag-1",
        node_id="delegate-1",
        node_run_id=node_run_id,
        attempt_id="attempt-1",
        metadata=metadata,
    )


async def _governed_effects(project_id: str) -> Any:
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    await effects.bindings.put(
        Binding(
            binding_id="binding-discovered",
            workspace_id=_WORKSPACE,
            project_id=project_id,
            capability=AGENT_DELEGATION_CAPABILITY,
        )
    )
    return effects


async def _invocable_node(
    store: InMemoryRunStore, project: Any, projection: SpecialistProjection
) -> AgentDelegateRemoteNode:
    """Register the discovered agent as a peer *from its projection alone*."""
    peers = GuestPeerManager()
    peers.register_peer(
        PeerTrust(
            peer_url=projection.descriptor.endpoint_url,
            peer_name=projection.descriptor.agent_id,
            allowed_agents=("planner",),
            supports_idempotency=True,
        )
    )
    return AgentDelegateRemoteNode(
        guest_peers=peers,
        run_store=store,
        effect_context=await _governed_effects(project.project_id),
    )


def _inputs(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "from_agent": "planner",
        "task": "research X",
        "peer_name": "deep-researcher",
        "binding_id": "binding-discovered",
    }
    values.update(overrides)
    return values


def _poll_status(agent: _ExternalResearchAgent, task_id: str) -> str:
    transport = httpx.MockTransport(agent.handler)
    with httpx.Client(transport=transport) as client:
        response = client.get(f"{_PEER_BASE}/a2a/tasks/{task_id}")
    assert response.status_code == 200
    return str(response.json()["status"])


# --------------------------------------------------------------------------
# 1. Discovered → eligible → invoked, end to end
# --------------------------------------------------------------------------


async def test_a_discovered_external_agent_is_projected_eligible_and_invocable() -> None:
    """The epic composition: ingest a card, project it through policy, then
    invoke *that discovered agent* through the canonical delegation seam —
    with the card's remote version surviving into the Attempt evidence."""
    projection = await _discovered_and_eligible(
        OperatorPolicy(capabilities=frozenset({"tool:web_search"})),
        _card(),
    )

    # Discovery half: clamped projection, remote provenance retained,
    # eligibility earned by the probe — not by the card's own claims.
    assert projection.card.trust_tier == EXTERNAL_TRUST_TIER
    assert projection.card.priority_tier == EXTERNAL_PRIORITY_TIER
    assert projection.card.delegation_mode == "none"
    assert projection.card.sub_agents == ()
    assert projection.card.scope == "external"
    assert projection.card.tools == ("web_search",), "only the authorized subset projects"
    assert projection.provenance.remote_version == "2.4.1"
    assert projection.provenance.publisher == "Example Labs"
    assert projection.provenance.protocol_version == "0.2.9"
    assert projection.availability.state is AvailabilityState.AVAILABLE
    assert projection.eligible is True

    store, project = await _spine()
    agent = _ExternalResearchAgent(["working", "completed"])
    node = await _invocable_node(store, project, projection)

    parent = await store.create_run(
        _graph(project.project_id), actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
    ctx = _ctx(parent.run_id, node_run.node_run_id)

    with override_transport(httpx.MockTransport(agent.handler)):
        dispatched = await node.run(_inputs(), ctx)
    assert dispatched.status == "paused"
    assert dispatched.metadata["paused_reason"] == "awaiting_remote_delegation"
    child_id = str(dispatched.metadata["run_id"])
    task_id = str(dispatched.metadata["task_id"])

    # The peer's task ticks; the first poll reports in-flight progress.
    with override_transport(httpx.MockTransport(agent.handler)):
        state = _poll_status(agent, task_id)
        assert state == "working"
        progress = await node.run(
            _inputs(),
            _ctx(
                ctx.run_id,
                ctx.node_run_id,
                {
                    "status": state,
                    "task_id": task_id,
                    "_pause": {"run_id": child_id, "metadata": dict(dispatched.metadata)},
                },
            ),
        )
    assert progress.status == "paused", "progress re-parks; it never settles"
    assert progress.metadata[PROGRESS_HISTORY_KEY][0]["raw_state"] == "working"

    # The engine completes; the terminal answer settles the same child, and
    # the discovered card's remote version rides the settlement evidence.
    with override_transport(httpx.MockTransport(agent.handler)):
        assert _poll_status(agent, task_id) == "completed"
        settled = await node.run(
            _inputs(),
            _ctx(
                ctx.run_id,
                ctx.node_run_id,
                {
                    "status": "completed",
                    "task_id": task_id,
                    "result": "X is documented",
                    "remote_agent_version": projection.provenance.remote_version,
                    "_pause": {"run_id": child_id, "metadata": dict(progress.metadata)},
                },
            ),
        )
    assert settled.status == "completed"
    assert settled.output is not None and settled.output.status == "completed"

    child = await store.get_run(child_id)
    assert child is not None and child.status is RunStatus.COMPLETED
    assert child.result == "X is documented"

    node_runs = await store.list_node_runs(child_id)
    assert len(node_runs) == 1, "one delegation, one child NodeRun — no duplicate identity"
    attempts = await store.list_attempts(node_runs[0].node_run_id)
    terminal = [a for a in attempts if a.status.value == "completed"]
    assert len(terminal) == 1
    evidence = terminal[0].result
    assert evidence["remote_agent_version"] == "2.4.1", (
        "the version discovered from the card survives into canonical evidence"
    )
    assert evidence["a2a_peer_url"] == projection.descriptor.endpoint_url
    assert evidence["peer_name"] == projection.descriptor.agent_id


# --------------------------------------------------------------------------
# 2. Authority stays attenuated across both halves
# --------------------------------------------------------------------------


async def test_authority_stays_attenuated_from_discovery_through_invocation() -> None:
    """A broadening refresh is refused without policy approval; a scope claim
    beyond the peer ceiling is refused before any bytes; a refused delegation
    files no child Run."""
    policy = OperatorPolicy(capabilities=frozenset({"tool:web_search"}))
    registry = _registry(policy=policy)
    record = registry.register(json.dumps(_card()), source_url=_CARD_URL)
    registry.report_availability(record.descriptor.agent_id, available=True)
    projection = registry.project(record.descriptor.agent_id)
    assert projection.card.tools == ("web_search",)

    # Refresh broadening the declared surface, policy unconsulted → refused,
    # and the effective projection does not move.
    broadened = _card(tools=["web_search", "crawl", "shell_exec"])
    with pytest.raises(AuthorityEscalationRefused):
        registry.refresh_descriptor(record.descriptor.agent_id, json.dumps(broadened))
    still = registry.project(record.descriptor.agent_id)
    assert still.card.tools == ("web_search",)
    assert still.provenance.payload_sha256 == projection.provenance.payload_sha256

    store, project = await _spine()
    agent = _ExternalResearchAgent(["working", "completed"])
    # The operator's trust ceiling for this peer stops at web.read.
    peers = GuestPeerManager()
    peers.register_peer(
        PeerTrust(
            peer_url=projection.descriptor.endpoint_url,
            peer_name=projection.descriptor.agent_id,
            allowed_agents=("planner",),
            allowed_scopes=("web.read",),
            supports_idempotency=True,
        )
    )
    gated = AgentDelegateRemoteNode(
        guest_peers=peers,
        run_store=store,
        effect_context=await _governed_effects(project.project_id),
    )

    parent = await store.create_run(
        _graph(project.project_id), actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
    ctx = _ctx(parent.run_id, node_run.node_run_id)

    with override_transport(httpx.MockTransport(agent.handler)):
        result = await gated.run(_inputs(delegated_scopes=("web.read", "shell.exec")), ctx)

    assert result.status == "completed"
    assert result.output is not None
    assert result.output.status == "rejected"
    assert "shell.exec" in (result.output.error or "")
    assert agent.creates == 0, "a refused authority reaches no peer"
    children = [run for run in store._runs.values() if run.parent_run_id == parent.run_id]  # type: ignore[attr-defined]
    assert children == [], "a refused delegation files no child Run"
