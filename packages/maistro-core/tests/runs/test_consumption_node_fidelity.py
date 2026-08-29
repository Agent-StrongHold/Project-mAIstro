"""The consumer gives a node what every other execution path gives it (#545).

Four ways the scheduled invocation differed from the durable graph executor's.
Each is a defect a scheduled template hits and a graph-executed one does not,
which is what makes them worth holding separately: the node kinds involved all
pass eligibility, because they *are* registered, and then behave differently
depending only on who executed them.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.container import Container, create_container
from maistro.graph import Graph, Node
from maistro.graph.nodes import BaseNode, NodeContext, register_node
from maistro.graph.nodes.base import NodeResult
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.sources import ADMISSION_SOURCE, SCHEDULE_INPUTS_KEY, SCHEDULE_SOURCE
from maistro.types.config import AgentConfig

#: SPEC-082926-d90e declares `contracts: [behavioral]`, and ADR-032 says a
#: document claiming a contract kind names a test carrying that marker. It named
#: these two files and neither carried one, so the claim had no evidence (#345).
pytestmark = [pytest.mark.contract("behavioral")]


RESUME_AT = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)


class _ConfiguredIn(BaseModel):
    #: No default: a node configured only through `parameters` fails validation
    #: outright when they are dropped, which is the reported symptom.
    endpoint: str
    greeting: str = "hello"


class _ConfiguredOut(BaseModel):
    text: str


class _ConfiguredNode(BaseNode[_ConfiguredIn, _ConfiguredOut]):
    kind: ClassVar[str] = "test.fidelity.configured"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _ConfiguredIn
    output_schema: ClassVar[type[BaseModel]] = _ConfiguredOut
    seen: ClassVar[dict[str, Any]] = {}

    async def _execute(self, inputs: _ConfiguredIn, ctx: NodeContext) -> _ConfiguredOut:
        type(self).seen = inputs.model_dump()
        return _ConfiguredOut(text=inputs.endpoint)


class _IdentityNode(BaseNode[_ConfiguredIn, _ConfiguredOut]):
    """Records the context it was actually handed."""

    kind: ClassVar[str] = "test.fidelity.identity"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _ConfiguredIn
    output_schema: ClassVar[type[BaseModel]] = _ConfiguredOut
    context: ClassVar[NodeContext | None] = None

    async def _execute(self, inputs: _ConfiguredIn, ctx: NodeContext) -> _ConfiguredOut:
        type(self).context = ctx
        return _ConfiguredOut(text="done")


class _PausingNode(BaseNode[_ConfiguredIn, _ConfiguredOut]):
    """A HITL node: succeeds, and pauses waiting for a person."""

    kind: ClassVar[str] = "test.fidelity.pausing"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _ConfiguredIn
    output_schema: ClassVar[type[BaseModel]] = _ConfiguredOut
    paused_reason: ClassVar[str] = "awaiting_human_answer"

    async def run(self, inputs: Any, ctx: Any) -> NodeResult:
        return NodeResult(
            success=True,
            status="paused",
            output=None,
            resume_at=RESUME_AT,
            metadata={"paused_reason": type(self).paused_reason, "prompt": "approve?"},
        )


for _cls in (_ConfiguredNode, _IdentityNode, _PausingNode):
    with contextlib.suppress(ValueError):
        register_node(_cls)


async def _container() -> Container:
    return await create_container(AgentConfig(router_api_key="test-key"))


async def _admit(
    container: Container,
    *,
    kind: str,
    parameters: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> str:
    workspace = "fidelity-ws"
    root = await container.project_scope_store.create_root(workspace)
    graph = Graph(
        workspace_id=workspace,
        project_id=root.project_id,
        name="scheduled work",
        nodes=[
            Node(
                node_id="n1",
                node_type=kind,
                parameters=dict(parameters or {}),
                inputs=dict(inputs or {}),
            )
        ],
    )
    provenance: dict[str, Any] = {ADMISSION_SOURCE: SCHEDULE_SOURCE}
    if overrides is not None:
        provenance[SCHEDULE_INPUTS_KEY] = overrides
    run = await container.run_store.create_run(
        graph, provenance=provenance, initial_status=RunStatus.QUEUED
    )
    return run.run_id


@pytest.mark.ac("SPEC-082926-d90e/AC-1")
async def test_a_node_configured_through_parameters_receives_them() -> None:
    """Direct-work admission stores configuration in `parameters`."""
    _ConfiguredNode.seen = {}
    container = await _container()
    run_id = await _admit(
        container, kind=_ConfiguredNode.kind, parameters={"endpoint": "https://example.test"}
    )

    assert await container.execute_admitted_runs() == 1

    assert _ConfiguredNode.seen["endpoint"] == "https://example.test"
    run = await container.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.COMPLETED


@pytest.mark.ac("SPEC-082926-d90e/AC-1")
async def test_inputs_win_over_parameters_and_the_schedule_wins_over_both() -> None:
    """Precedence matches the graph executor's `{**parameters, **inputs}`."""
    _ConfiguredNode.seen = {}
    container = await _container()
    await _admit(
        container,
        kind=_ConfiguredNode.kind,
        parameters={"endpoint": "from-parameters", "greeting": "from-parameters"},
        inputs={"greeting": "from-inputs"},
        overrides={"greeting": "from-schedule"},
    )

    assert await container.execute_admitted_runs() == 1

    assert _ConfiguredNode.seen == {
        "endpoint": "from-parameters",
        "greeting": "from-schedule",
    }


@pytest.mark.ac("SPEC-082926-d90e/AC-2")
async def test_the_consumer_builds_nodes_through_the_wired_resolver() -> None:
    """The kinds with injected dependencies are built by the resolver, not bare.

    Asserted on the seam rather than on a delegation's side effects: what the
    defect changed is *which constructor runs*, and a node built bare is
    indistinguishable from one built wired until it tries to use a dependency
    it was never given.
    """
    container = await _container()
    seen: list[str] = []
    real = container.a2a_delegator

    from maistro.container import build_node_resolver

    resolver = build_node_resolver(
        harness_adapters=container.harness_adapters,
        usage_log=container.usage_log,
        a2a_delegator=real,
        guest_peers=container.guest_peers,
        run_store=container.run_store,
    )
    graph = Graph(
        workspace_id="w",
        project_id="p",
        name="g",
        nodes=[Node(node_id="n1", node_type="agent.delegate_remote")],
    )
    node = resolver("n1", graph)
    seen.append(type(node).__name__)

    assert seen == ["AgentDelegateRemoteNode"]
    # The wired one carries the RunStore; the bare registry constructor does not.
    assert getattr(node, "_run_store", None) is container.run_store


@pytest.mark.ac("SPEC-082926-d90e/AC-3")
async def test_a_paused_human_node_reaches_paused_with_its_prompt_intact() -> None:
    """A HITL pause is not a failure, and what it waits for survives."""
    _PausingNode.paused_reason = "awaiting_human_answer"
    container = await _container()
    run_id = await _admit(
        container, kind=_PausingNode.kind, parameters={"endpoint": "https://example.test"}
    )

    assert await container.execute_admitted_runs() == 1

    (node_run,) = await container.run_store.list_node_runs(run_id)
    assert node_run.status is RunStatus.PAUSED

    (attempt,) = await container.run_store.list_attempts(node_run.node_run_id)
    assert attempt.status is AttemptStatus.YIELDED
    assert attempt.error is None
    assert attempt.result["resume_at"] == RESUME_AT.isoformat()
    assert attempt.result["metadata"]["prompt"] == "approve?"


@pytest.mark.ac("SPEC-082926-d90e/AC-3")
async def test_a_non_human_pause_parks_waiting_rather_than_paused() -> None:
    """WAITING and PAUSED differ by who is owed the next action."""
    _PausingNode.paused_reason = "awaiting_timer"
    container = await _container()
    run_id = await _admit(
        container, kind=_PausingNode.kind, parameters={"endpoint": "https://example.test"}
    )

    assert await container.execute_admitted_runs() == 1

    (node_run,) = await container.run_store.list_node_runs(run_id)
    assert node_run.status is RunStatus.WAITING
    (attempt,) = await container.run_store.list_attempts(node_run.node_run_id)
    assert attempt.status is AttemptStatus.YIELDED


@pytest.mark.ac("SPEC-082926-d90e/AC-4")
async def test_the_node_sees_its_own_node_run_and_attempt_ids() -> None:
    """Built before execution, the context could only carry empty ids."""
    _IdentityNode.context = None
    container = await _container()
    run_id = await _admit(
        container, kind=_IdentityNode.kind, parameters={"endpoint": "https://example.test"}
    )

    assert await container.execute_admitted_runs() == 1

    (node_run,) = await container.run_store.list_node_runs(run_id)
    (attempt,) = await container.run_store.list_attempts(node_run.node_run_id)
    ctx = _IdentityNode.context
    assert ctx is not None
    assert ctx.node_run_id == node_run.node_run_id
    assert ctx.attempt_id == attempt.attempt_id
    assert ctx.run_id == run_id
