"""Conformance suite: external Agent lifecycle normalization (M9-D3, #960).

Drives the remote-lifecycle normalization against an *external-style Agent
implementation* — a stateful A2A-protocol peer speaking the same wire protocol
`GuestPeerManager` already uses for outbound delegation (`POST
/a2a/tasks/create` with idempotent admission, `GET
/a2a/tasks/by-idempotency-key/{key}` for receipt reconciliation) plus the task
status resource an A2A peer exposes — over real httpx transport semantics.

Each conformance case pins one #960 acceptance criterion end to end:

- remote protocol `completed` cannot override canonical Run terminal truth;
- cancellation remains truthful when remote acknowledgement is missing;
- ambiguous/lost responses do not trigger unsafe automatic side-effect replay;
- retries are governed by canonical Invocation/effect semantics;
- progress survives network reconnect without inventing duplicate
  NodeRun/Attempt identity.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from maistro.a2a.guest_peers import GuestPeerManager, PeerTrust
from maistro.a2a.normalize import (
    PROGRESS_HISTORY_KEY,
    CanonicalDelegationTruth,
    RemoteRetryDecision,
    RemoteState,
    decide_retry,
    decide_settlement,
    normalize_remote_state,
)
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
from maistro.runs.service import RunExecutionService
from maistro.runtime import PythonExecutionRuntime
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

_WORKSPACE = "workspace-1"


async def _governed_effects(project_id: str) -> Any:
    """The governed admission wiring for a cross-instance dispatch (issue #959).

    A dispatch is admitted only through an operator-declared `agent_delegation`
    Binding in the dispatching Workspace/Project scope, so conformance drives
    the external protocol through the same governed seam production uses. This
    mirrors the delegation governance suite's canonical fixture
    (`tests/graph/nodes/_delegation_governance.py`), which is importable only
    inside that test package under importlib import mode.
    """
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    await effects.bindings.put(
        Binding(
            binding_id="binding-hub",
            workspace_id=_WORKSPACE,
            project_id=project_id,
            capability=AGENT_DELEGATION_CAPABILITY,
        )
    )
    return effects


class _ExternalStyleA2AAgent:
    """An external-style A2A Agent implementation.

    Its engine walks every accepted task through a scripted sequence of A2A
    task states, advancing one step per status poll, exactly as a poll-driven
    external agent would. The implementation is deliberately its own thing —
    its own state names, its own transport, its own idempotent admission —
    so conformance shows MAIstro normalizes *that* implementation's lifecycle,
    not a local stub shaped like the answer key.
    """

    #: Every task state this external implementation can ever emit. The
    #: vocabulary conformance case iterates exactly this set.
    VOCABULARY: frozenset[str] = frozenset(
        {
            "submitted",
            "working",
            "input-required",
            "completed",
            "failed",
            "canceled",
            "rejected",
            "unknown",
        }
    )

    def __init__(self, script: list[str]) -> None:
        self.script = script
        self.creates = 0
        self.reconciles = 0
        self.status_polls = 0
        self.partitioned = False
        self._by_key: dict[str, str] = {}
        self._tasks: dict[str, dict[str, str]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/a2a/tasks/create":
            return self._create(request)
        if request.method == "GET" and path.startswith("/a2a/tasks/by-idempotency-key/"):
            return self._reconcile(path.rsplit("/", 1)[-1])
        if request.method == "GET" and path.startswith("/a2a/tasks/"):
            return self._status(path.rsplit("/", 1)[-1])
        return httpx.Response(404, json={"detail": "not found"})

    def _create(self, request: httpx.Request) -> httpx.Response:
        self.creates += 1
        payload = json.loads(request.content)
        key = str(payload.get("idempotency_key") or request.headers.get("idempotency-key") or "")
        existing = self._by_key.get(key)
        if existing is not None:
            # Idempotent admission: the same logical delegation is never a
            # second task, however many times the key is presented.
            return self._admitted(existing)
        if not key:
            return httpx.Response(422, json={"detail": "idempotency key required"})
        task_id = f"ext-task-{self.creates}"
        self._by_key[key] = task_id
        self._tasks[task_id] = {"status": self.script[0]}
        return self._admitted(task_id)

    def _admitted(self, task_id: str) -> httpx.Response:
        return httpx.Response(
            202,
            json={"task_id": task_id, "run_id": task_id, "status": "submitted"},
        )

    def _reconcile(self, key: str) -> httpx.Response:
        self.reconciles += 1
        task_id = self._by_key.get(key)
        if task_id is None:
            return httpx.Response(404, json={"detail": "unknown idempotency key"})
        return httpx.Response(200, json={"task_id": task_id})

    def _status(self, task_id: str) -> httpx.Response:
        if self.partitioned:
            raise httpx.ConnectError("peer unreachable (injected network partition)")
        self.status_polls += 1
        task = self._tasks.get(task_id)
        if task is None:
            return httpx.Response(404, json={"detail": "unknown task"})
        state = task["status"]
        if state in self.script and self.script.index(state) < len(self.script) - 1:
            # The external engine ticks on each poll.
            task["status"] = self.script[self.script.index(state) + 1]
        return httpx.Response(200, json={"task_id": task_id, "status": state})

    def state_of(self, task_id: str) -> str:
        return self._tasks[task_id]["status"]


def _agent(script: list[str]) -> _ExternalStyleA2AAgent:
    return _ExternalStyleA2AAgent(script)


# --------------------------------------------------------------------------
# Fixtures: the canonical spine and a dispatched delegation
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
        # A governed dispatch records its Invocation on the dispatching
        # Attempt (#959), so the context carries one like production does.
        attempt_id="attempt-1",
        metadata=metadata,
    )


def _peers() -> GuestPeerManager:
    peers = GuestPeerManager()
    peers.register_peer(
        PeerTrust(
            peer_url="http://external-agent.test",
            peer_name="ext",
            allowed_agents=("planner",),
            supports_idempotency=True,
        )
    )
    return peers


async def _dispatch(
    store: InMemoryRunStore, project: Any, agent: _ExternalStyleA2AAgent
) -> tuple[AgentDelegateRemoteNode, NodeContext, str, str]:
    """Dispatch one cross-instance delegation and return the live pieces."""
    parent = await store.create_run(
        _graph(project.project_id), actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
    ctx = _ctx(parent.run_id, node_run.node_run_id)
    node = AgentDelegateRemoteNode(
        guest_peers=_peers(),
        run_store=store,
        effect_context=await _governed_effects(project.project_id),
    )
    with override_transport(httpx.MockTransport(agent.handler)):
        result = await node.run(
            {
                "from_agent": "planner",
                "task": "research X",
                "peer_name": "ext",
                "binding_id": "binding-hub",
            },
            ctx,
        )
    assert result.status == "paused"
    assert result.metadata["paused_reason"] == "awaiting_remote_delegation"
    return node, ctx, str(result.metadata["run_id"]), str(result.metadata["task_id"])


def _stamped_pause(run_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """The server-authored pause entry an answer carries back to the node."""
    return {"run_id": run_id, "metadata": dict(metadata)}


def _poll_status(agent: _ExternalStyleA2AAgent, task_id: str) -> str:
    """Poll the external agent's task status resource — the read a settlement
    coordinator performs before submitting an answer to the waiting node.
    The poll also drives the peer's own lifecycle engine one tick."""
    transport = httpx.MockTransport(agent.handler)
    with httpx.Client(transport=transport) as client:
        response = client.get(f"http://external-agent.test/a2a/tasks/{task_id}")
    assert response.status_code == 200
    return str(response.json()["status"])


async def _child_node_run(store: InMemoryRunStore, child_id: str) -> Any:
    node_runs = await store.list_node_runs(child_id)
    assert len(node_runs) == 1, "a delegation child has exactly one NodeRun"
    return node_runs[0]


# --------------------------------------------------------------------------
# Conformance: the external implementation's vocabulary
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("submitted", RemoteState(progress=True)),
        ("working", RemoteState(progress=True)),
        ("input-required", RemoteState(progress=True)),
        ("completed", RemoteState(outcome="completed")),
        ("failed", RemoteState(outcome="failed")),
        ("canceled", RemoteState(outcome="failed", cancelled=True)),
        ("rejected", RemoteState(outcome="rejected")),
        # The peer saying "unknown" about its own task normalizes to unknown:
        # the protocol's own admission of not-knowing is ambiguity, and the
        # mapping refuses to launder it into an outcome.
        ("unknown", RemoteState()),
    ],
)
def test_every_state_the_external_implementation_emits_is_mapped(
    raw: str, expected: RemoteState
) -> None:
    assert normalize_remote_state(raw) == expected


def test_the_external_vocabulary_is_the_mapped_vocabulary() -> None:
    """Vocabulary conformance: if the external implementation ever grows a
    state, this fails until MAIstro maps it — the mapping can never silently
    fall behind the protocol it consumes."""
    unmapped = [
        raw
        for raw in sorted(_ExternalStyleA2AAgent.VOCABULARY)
        if normalize_remote_state(raw).is_unknown and raw != "unknown"
    ]
    assert unmapped == []


# --------------------------------------------------------------------------
# Conformance: progress → completion over the real protocol
# --------------------------------------------------------------------------


async def test_progress_then_completion_settles_one_child_one_node_run() -> None:
    store, project = await _spine()
    agent = _agent(["working", "completed"])
    node, ctx, child_id, task_id = await _dispatch(store, project, agent)

    # First poll: the external engine reports `working` — in-flight progress,
    # read from the peer over the wire and submitted as the answer.
    with override_transport(httpx.MockTransport(agent.handler)):
        state = _poll_status(agent, task_id)
        assert state == "working"
        progress = await node.run(
            {"from_agent": "planner", "task": "research X", "peer_name": "ext"},
            _ctx(
                ctx.run_id,
                ctx.node_run_id,
                {
                    "status": state,
                    "task_id": task_id,
                    "_pause": _stamped_pause(child_id, {}),
                },
            ),
        )
    assert progress.status == "paused", "progress re-parks; it never settles"
    child = await store.get_run(child_id)
    assert child is not None and child.status is RunStatus.WAITING
    node_run = await _child_node_run(store, child_id)
    attempts = await store.list_attempts(node_run.node_run_id)
    assert len(attempts) == 1, "a progress report must not mint a second Attempt"
    assert progress.metadata[PROGRESS_HISTORY_KEY][0]["raw_state"] == "working"
    assert progress.metadata[PROGRESS_HISTORY_KEY][0]["sequence"] == 1

    # Reconnect: a fresh replica resumes the same checkpoint and re-observes
    # the same state before the peer advances — flagged, not re-counted.
    stamped = dict(progress.metadata)
    stamped.pop("paused_reason", None)
    with override_transport(httpx.MockTransport(agent.handler)):
        reconnected = await node.run(
            {"from_agent": "planner", "task": "research X", "peer_name": "ext"},
            _ctx(
                ctx.run_id,
                ctx.node_run_id,
                {
                    "status": "working",
                    "task_id": task_id,
                    "_pause": _stamped_pause(child_id, stamped),
                },
            ),
        )
    assert reconnected.status == "paused"
    history = reconnected.metadata[PROGRESS_HISTORY_KEY]
    assert history[-1]["duplicate"] is True
    node_run = await _child_node_run(store, child_id)
    assert len(await store.list_attempts(node_run.node_run_id)) == 1

    # The external engine completes; the terminal answer settles the SAME
    # NodeRun — one settled child, no duplicate identity anywhere.
    with override_transport(httpx.MockTransport(agent.handler)):
        assert _poll_status(agent, task_id) == "completed"
        settled = await node.run(
            {"from_agent": "planner", "task": "research X", "peer_name": "ext"},
            _ctx(
                ctx.run_id,
                ctx.node_run_id,
                {
                    "status": "completed",
                    "task_id": task_id,
                    "result": "X is documented",
                    "_pause": _stamped_pause(child_id, dict(reconnected.metadata)),
                },
            ),
        )
    assert settled.status == "completed"
    assert settled.output is not None
    assert settled.output.status == "completed"
    child = await store.get_run(child_id)
    assert child is not None and child.status is RunStatus.COMPLETED
    assert child.result == "X is documented"
    node_run = await _child_node_run(store, child_id)
    attempts = await store.list_attempts(node_run.node_run_id)
    assert len(attempts) == 2, "the settlement Attempt lands on the original NodeRun"
    assert attempts[-1].status.value == "completed"


async def test_remote_completed_after_local_cancellation_is_refused() -> None:
    """The core truth rule, end to end: the child Run is cancelled locally;
    the external agent (which never acknowledged) later completes its task;
    the late `completed` neither reopens the child nor advances the parent on
    the remote's word."""
    store, project = await _spine()
    agent = _agent(["working", "completed"])
    node, ctx, child_id, task_id = await _dispatch(store, project, agent)

    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
    cancelled = await service.cancel_run(child_id)
    assert cancelled.status is RunStatus.CANCELLED

    with override_transport(httpx.MockTransport(agent.handler)):
        assert _poll_status(agent, task_id) == "working"  # the peer never knew
        assert _poll_status(agent, task_id) == "completed"  # ...and later completes
        result = await node.run(
            {"from_agent": "planner", "task": "research X", "peer_name": "ext"},
            _ctx(
                ctx.run_id,
                ctx.node_run_id,
                {
                    "status": "completed",
                    "task_id": task_id,
                    "result": "the peer says so",
                    "_pause": _stamped_pause(child_id, {}),
                },
            ),
        )
    assert result.status == "completed", "the refusal is an outcome, not a crash"
    assert result.output is not None
    assert result.output.status == "failed", "the parent is never told 'completed'"
    assert "already 'cancelled'" in (result.output.error or "")
    child = await store.get_run(child_id)
    assert child is not None
    assert child.status is RunStatus.CANCELLED, "canonical terminal truth holds"
    assert child.result is None, "the refused remote result never lands on the child"
    node_run = await _child_node_run(store, child_id)
    attempts = await store.list_attempts(node_run.node_run_id)
    assert len(attempts) == 1, "no settlement Attempt is written for a refused answer"


async def test_cancellation_is_truthful_while_the_peer_keeps_working() -> None:
    """The peer never acknowledges — its task is still `working` when the
    child is cancelled. The canonical record is cancelled anyway, and the
    cancellation projection says exactly what is and is not known."""
    from maistro.a2a.normalize import decide_cancellation

    store, project = await _spine()
    agent = _agent(["working", "working"])
    _node, _ctx_unused, child_id, task_id = await _dispatch(store, project, agent)

    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
    cancelled = await service.cancel_run(child_id)
    assert cancelled.status is RunStatus.CANCELLED

    with override_transport(httpx.MockTransport(agent.handler)):
        assert _poll_status(agent, task_id) == "working"  # no acknowledgement, ever
    child = await store.get_run(child_id)
    assert child is not None and child.status is RunStatus.CANCELLED
    projection = decide_cancellation(remote_acknowledged=False)
    assert projection.canonical_status == "cancelled"
    assert projection.remote_acknowledged is False
    decision = decide_settlement(
        "completed", CanonicalDelegationTruth(status=child.status.value, terminal=True)
    )
    assert decision.applies is False


# --------------------------------------------------------------------------
# Conformance: ambiguous / lost responses never replay
# --------------------------------------------------------------------------


async def test_a_lost_response_reconciles_the_receipt_without_a_second_post() -> None:
    """The peer accepted the POST but the response was lost to a partition.
    The node must park on reconciliation, recover the receipt through the
    peer's idempotent reconciliation endpoint, and never submit twice."""
    store, project = await _spine()
    agent = _agent(["working", "working"])

    partitioned_handler = agent.handler

    def losing_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            partitioned_handler(request)  # the peer accepts (and counts it)
            raise httpx.ConnectError("response lost (injected partition)")
        return partitioned_handler(request)

    parent = await store.create_run(
        _graph(project.project_id), actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    node_run = await store.create_node_run(parent.run_id, node_id="delegate-1")
    ctx = _ctx(parent.run_id, node_run.node_run_id)
    node = AgentDelegateRemoteNode(
        guest_peers=_peers(),
        run_store=store,
        effect_context=await _governed_effects(project.project_id),
    )
    inputs = {
        "from_agent": "planner",
        "task": "research X",
        "peer_name": "ext",
        "binding_id": "binding-hub",
    }
    with override_transport(httpx.MockTransport(losing_handler)):
        first = await node.run(inputs, ctx)
    assert first.status == "paused"
    assert first.metadata["paused_reason"] == "awaiting_delegation_reconciliation", (
        "an uncertain acceptance parks on reconciliation; it is never an outcome"
    )

    # The reconnect tick: same inputs, same delegation key, no answer yet.
    with override_transport(httpx.MockTransport(agent.handler)):
        second = await node.run(inputs, ctx)
    assert second.status == "paused"
    assert second.metadata["paused_reason"] == "awaiting_remote_delegation"
    assert second.metadata["task_id"], "the recovered receipt is the pause's task"
    child = await store.get_run(str(second.metadata["run_id"]))
    assert child is not None
    assert child.provenance.get("a2a_task_id") == second.metadata["task_id"]
    assert agent.creates == 1, "exactly one submission ever crossed the transport"
    assert agent.reconciles >= 1, "the receipt was recovered by reconciliation"


async def test_an_ambiguous_response_is_classified_reconcile_only() -> None:
    agent = _agent(["working"])
    agent.partitioned = True
    transport = httpx.MockTransport(agent.handler)
    with (
        override_transport(transport),
        httpx.Client(transport=transport) as client,
        pytest.raises(httpx.ConnectError),
    ):
        client.get("http://external-agent.test/a2a/tasks/ext-task-1")
    decision = decide_retry("unknown", boundary_crossed=True)
    assert decision.decision is RemoteRetryDecision.RECONCILE_ONLY


# --------------------------------------------------------------------------
# Conformance: retries are governed by canonical effect semantics
# --------------------------------------------------------------------------


async def test_explicit_remote_failure_settles_and_is_effect_key_governed() -> None:
    store, project = await _spine()
    agent = _agent(["failed"])
    node, ctx, child_id, task_id = await _dispatch(store, project, agent)

    with override_transport(httpx.MockTransport(agent.handler)):
        assert _poll_status(agent, task_id) == "failed"
        settled = await node.run(
            {"from_agent": "planner", "task": "research X", "peer_name": "ext"},
            _ctx(
                ctx.run_id,
                ctx.node_run_id,
                {
                    "status": "failed",
                    "task_id": task_id,
                    "error": "the peer gave up",
                    "_pause": _stamped_pause(child_id, {}),
                },
            ),
        )
    assert settled.output is not None and settled.output.status == "failed"
    child = await store.get_run(child_id)
    assert child is not None and child.status is RunStatus.FAILED

    decision = decide_retry("failed", boundary_crossed=True)
    assert decision.decision is RemoteRetryDecision.EFFECT_KEY_GOVERNED
    assert "effect-key" in decision.reason


async def test_the_peers_idempotent_admission_never_mints_a_second_task() -> None:
    """The transport half of retry governance: however many times the
    canonical effect key is presented, the external implementation admits one
    task — so an effect-key-governed retry re-adopts, never duplicates."""
    agent = _agent(["working"])
    transport = httpx.MockTransport(agent.handler)
    key = "agent.delegate_remote:r1:n1:digest"
    with override_transport(transport):

        async def submit() -> httpx.Response:
            async with httpx.AsyncClient(transport=transport) as client:
                return await client.post(
                    "http://external-agent.test/a2a/tasks/create",
                    json={
                        "agent_id": "planner",
                        "messages": [{"role": "user", "content": "research X"}],
                        "idempotency_key": key,
                    },
                )

        first = await submit()
        second = await submit()
    assert first.status_code == second.status_code == 202
    assert first.json()["task_id"] == second.json()["task_id"]
    assert agent.creates == 2, "both POSTs arrived; the peer admits one task"
