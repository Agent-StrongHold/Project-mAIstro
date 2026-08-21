from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel

from maistro.capabilities.approval_store import InMemoryApprovalStore
from maistro.capabilities.binding import Binding
from maistro.capabilities.governed_invocation import (
    GovernedInvocationExecutionService,
    InvocationPolicyContext,
)
from maistro.capabilities.invocation import InMemoryInvocationStore, InvocationExecutionService
from maistro.events.envelope import InMemoryEventStore
from maistro.graph.nodes.base import BaseNode, NodeContext
from maistro.graph.nodes.capability_effect import invoke_capability_effect
from maistro.policy.types import Decision, PolicyVerdict


@dataclass(frozen=True)
class _Provider:
    name: str = "provider-a"
    slot: str = "external_write"
    trust_tier: str = "trusted"


class _Input(BaseModel):
    value: int


class _Output(BaseModel):
    value: int


async def _resolver(_binding: Binding) -> _Provider:
    return _Provider()


async def _policy(
    _binding: Binding,
    _request: Any,
    context: InvocationPolicyContext,
) -> PolicyVerdict:
    if context.approved:
        return PolicyVerdict(Decision.ALLOW, reason="approved", rule="human-review")
    return PolicyVerdict(
        Decision.REQUIRE_APPROVAL,
        reason="review required",
        rule="human-review",
    )


class _CapabilityNode(BaseNode[_Input, _Output]):
    kind: ClassVar[str] = "test.capability_effect"
    kind_category: ClassVar = "sync.tool"
    input_schema: ClassVar[type[BaseModel]] = _Input
    output_schema: ClassVar[type[BaseModel]] = _Output
    external_io: ClassVar[bool] = True

    def __init__(
        self,
        service: GovernedInvocationExecutionService,
        binding: Binding,
    ) -> None:
        self._service = service
        self._binding = binding

    async def _execute(self, inputs: _Input, ctx: NodeContext) -> _Output:
        async def execute(_provider: _Provider, request: Any) -> dict[str, Any]:
            return {"committed": request}

        invocation = await invoke_capability_effect(
            lambda: self._service.invoke(
                binding=self._binding,
                run_id=ctx.run_id,
                node_run_id=ctx.node_run_id,
                attempt_id=ctx.attempt_id,
                effect_key="write:1",
                request={"value": inputs.value},
                resolver=_resolver,
                executor=execute,
            ),
            effect_key="write:1",
        )
        assert isinstance(invocation.result, dict)
        committed = invocation.result["committed"]
        assert isinstance(committed, dict)
        return _Output(value=int(committed["value"]))


async def test_approval_required_pauses_then_resumes_same_node_effect() -> None:
    approvals = InMemoryApprovalStore()
    events = InMemoryEventStore()
    service = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=events,
        policy_evaluator=_policy,
        approval_store=approvals,
    )
    binding = Binding(
        binding_id="binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="external_write",
        policy_refs=("human-review",),
    )
    node = _CapabilityNode(service, binding)

    first = await node.run(
        _Input(value=7),
        NodeContext(
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            dag_id="graph-1",
            node_id="node-1",
        ),
    )
    assert first.status == "paused"
    assert first.metadata["paused_reason"] == "awaiting_human_approval"
    request_id = first.metadata["approval_request_id"]
    assert request_id

    await approvals.resolve(str(request_id), approved=True, actor="alice")

    resumed = await node.run(
        _Input(value=7),
        NodeContext(
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-2",
            dag_id="graph-1",
            node_id="node-1",
        ),
    )
    assert resumed.status == "completed"
    assert isinstance(resumed.output, _Output)
    assert resumed.output.value == 7

    stream = await events.list_stream("workspace:ws-1")
    assert "capability.invocation.approval_required" in [event.type for event in stream]
    assert "capability.invocation.approval_satisfied" in [event.type for event in stream]
    completed = [event for event in stream if event.type == "capability.invocation.completed"]
    assert len(completed) == 1
    assert completed[0].attempt_id == "attempt-2"
