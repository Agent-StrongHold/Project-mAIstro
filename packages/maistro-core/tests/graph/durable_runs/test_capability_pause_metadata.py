"""Durable Graph integration: canonical approval pauses park ``PAUSED`` (#1898).

The capability-effect pause adapter is a Graph-only continuation capability.
This module proves the *real durable executor* behavior, not just the
``NodeResult`` shape:

- a node pausing on ``InvocationApprovalPending`` parks the canonical Run on
  ``RunStatus.PAUSED`` (a human pause), never ``WAITING``;
- the persisted pause metadata carries the exact approval receipt, the caller's
  request digest, the required effect key, and the node's continuation, and the
  record keeps the fixed deadline verbatim;
- two Attempts of the same NodeRun with the approval resolved between them make
  one physical provider call and create no new approval request;
- a denied approval is refused by the governed authority and fails the run.

The approval here is resolved directly on the ``ApprovalStore``; production
HITL-to-DurableApproval linkage is the separately owned #55 integration and is
deliberately not exercised or claimed by this module.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import BaseModel

from maistro.capabilities.approval_store import (
    InMemoryApprovalStore,
    approval_request_digest,
)
from maistro.capabilities.binding import Binding
from maistro.capabilities.governed_invocation import (
    GovernedInvocationExecutionService,
    InvocationPolicyContext,
)
from maistro.capabilities.invocation import InMemoryInvocationStore, InvocationExecutionService
from maistro.events.envelope import InMemoryEventStore
from maistro.graph.durable_runs import InMemoryDurableRunStore, RunStatus
from maistro.graph.execution_state import thaw_json_value
from maistro.graph.nodes import BaseNode, NodeContext, register_node
from maistro.graph.nodes.capability_effect import invoke_capability_effect
from maistro.policy.types import Decision, PolicyVerdict

from .._canonical_helpers import hitl_authorization
from .._canonical_helpers import resume_legacy_dag_fixture as resume_durable_dag
from .._canonical_helpers import run_legacy_dag_fixture as run_durable_dag

#: A fixed aware deadline supplied by the node. The pause must preserve it
#: verbatim -- no normalization, no deadline re-derived from "now".
PAUSE_DEADLINE = datetime(2030, 5, 1, 12, 30, tzinfo=UTC)

_CONTINUATION: dict[str, Any] = {
    "question": {"text": "Proceed with write:durable?", "tags": ["external_write"]},
}


class _PauseProvider:
    name = "provider-a"
    slot = "external_write"
    trust_tier = "trusted"


class _DurablePauseIn(BaseModel):
    value: int


class _DurablePauseOut(BaseModel):
    value: int


class _DurablePauseNode(BaseNode[_DurablePauseIn, _DurablePauseOut]):
    """Governed external effect that keeps a fixed continuation across the
    canonical approval pause."""

    kind: ClassVar[str] = "test.durable_capability_pause"
    kind_category: ClassVar = "sync.tool"
    input_schema: ClassVar[type[BaseModel]] = _DurablePauseIn
    output_schema: ClassVar[type[BaseModel]] = _DurablePauseOut
    external_io: ClassVar[bool] = True

    def __init__(
        self,
        service: GovernedInvocationExecutionService,
        binding: Binding,
        *,
        provider_calls: list[dict[str, Any]],
    ) -> None:
        self._service = service
        self._binding = binding
        self._provider_calls = provider_calls

    async def _execute(self, inputs: _DurablePauseIn, ctx: NodeContext) -> _DurablePauseOut:
        request: dict[str, Any] = {"value": inputs.value}

        async def resolver(_binding: Binding) -> _PauseProvider:
            return _PauseProvider()

        async def execute(_provider: _PauseProvider, req: Any) -> dict[str, Any]:
            self._provider_calls.append(dict(req))
            return {"committed": req}

        invocation = await invoke_capability_effect(
            lambda: self._service.invoke(
                binding=self._binding,
                run_id=ctx.run_id,
                node_run_id=ctx.node_run_id,
                attempt_id=ctx.attempt_id,
                effect_key="write:durable",
                request=request,
                resolver=resolver,
                executor=execute,
            ),
            effect_key="write:durable",
            continuation_metadata=_CONTINUATION,
            resume_at=PAUSE_DEADLINE,
            request_digest=approval_request_digest(request),
        )
        assert isinstance(invocation.result, dict)
        committed = invocation.result["committed"]
        assert isinstance(committed, dict)
        return _DurablePauseOut(value=int(committed["value"]))


with contextlib.suppress(ValueError):
    # Tests rerun in the same process; collision is fine.
    register_node(_DurablePauseNode)


def _binding() -> Binding:
    return Binding(
        binding_id="binding-1898",
        workspace_id="ws-1898",
        project_id="project-1898",
        node_id="effect",
        capability="external_write",
        policy_refs=("human-review",),
    )


def _service(
    approvals: InMemoryApprovalStore,
    events: InMemoryEventStore,
) -> GovernedInvocationExecutionService:
    async def policy(
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

    return GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=events,
        policy_evaluator=policy,
        approval_store=approvals,
    )


def _dag() -> dict[str, Any]:
    return {
        "id": "capability-pause-dag",
        "nodes": [
            {"id": "effect", "kind": "test.durable_capability_pause", "inputs": {"value": 7}}
        ],
        "edges": [],
        "entry_node": "effect",
    }


def _node(
    service: GovernedInvocationExecutionService,
    provider_calls: list[dict[str, Any]],
) -> _DurablePauseNode:
    return _DurablePauseNode(service, _binding(), provider_calls=provider_calls)


def _resolver(node: _DurablePauseNode):
    def resolve(_node_id: str, _dag: dict[str, Any]) -> BaseNode[Any, Any]:
        return node

    return resolve


async def _park(
    store: InMemoryDurableRunStore,
    approvals: InMemoryApprovalStore,
    events: InMemoryEventStore,
    provider_calls: list[dict[str, Any]],
):
    """Run the durable graph once and park it on the canonical approval pause."""
    node = _node(_service(approvals, events), provider_calls)
    record = await run_durable_dag(
        _dag(),
        store=store,
        node_resolver=_resolver(node),
        inputs={"value": 7},
    )
    return record, node


async def test_capability_pause_parks_run_paused_with_continuation_and_receipt() -> None:
    store = InMemoryDurableRunStore()
    approvals = InMemoryApprovalStore()
    events = InMemoryEventStore()
    provider_calls: list[dict[str, Any]] = []

    record, _node = await _park(store, approvals, events, provider_calls)

    # The real durable Graph path parks PAUSED -- a human pause -- not WAITING.
    assert record.run.status is RunStatus.PAUSED
    assert record.run.status is not RunStatus.WAITING
    assert record.status is RunStatus.PAUSED
    by_id = {nr.node_id: nr for nr in record.node_runs}
    assert by_id["effect"].status is RunStatus.PAUSED

    pause = thaw_json_value(record.graph_state.metadata)["pause"]
    assert pause["kind"] == "hitl"
    metadata = pause["metadata"]
    assert metadata["paused_reason"] == "awaiting_human_approval"
    assert metadata["effect_key"] == "write:durable"
    assert metadata["request_digest"] == approval_request_digest({"value": 7})
    assert metadata["question"] == {
        "text": "Proceed with write:durable?",
        "tags": ["external_write"],
    }

    # The pause receipt is the canonical approval request the governed service
    # created for this exact NodeRun and effect.
    approval = await approvals.find_effect(
        run_id=record.run.run_id,
        node_run_id=by_id["effect"].node_run_id,
        binding_id="binding-1898",
        effect_key="write:durable",
    )
    assert approval is not None
    assert metadata["approval_request_id"] == approval.request.request_id

    # Fixed deadline: persisted verbatim in the pause entry. The record's
    # timer waker stays unarmed -- approval pauses are RESUME_ON_ANSWER, and
    # this leaf deliberately does not activate timer re-entry.
    assert pause["resume_at"] == PAUSE_DEADLINE.isoformat()
    assert record.resume_at is None

    # No physical provider call happened on the parked Attempt.
    assert provider_calls == []


async def test_capability_pause_resumes_with_one_provider_call_and_no_new_request() -> None:
    store = InMemoryDurableRunStore()
    approvals = InMemoryApprovalStore()
    events = InMemoryEventStore()
    provider_calls: list[dict[str, Any]] = []

    record, node = await _park(store, approvals, events, provider_calls)
    request_id = thaw_json_value(record.graph_state.metadata)["pause"]["metadata"][
        "approval_request_id"
    ]

    await approvals.resolve(str(request_id), approved=True, actor="alice")
    # Un-park the paused NodeRun the durable way: HITL input consumes the pause.
    await store.submit_hitl_answer(
        record.run.run_id, "effect", {"answer": "approved"}, authorization=hitl_authorization()
    )
    resumed = await resume_durable_dag(
        record.run.run_id,
        store=store,
        node_resolver=_resolver(node),
    )

    assert resumed.status is RunStatus.COMPLETED
    by_id = {nr.node_id: nr for nr in resumed.node_runs}
    assert by_id["effect"].status is RunStatus.COMPLETED
    assert by_id["effect"].result == {"value": 7}

    # Two Attempts of the same NodeRun: one physical provider call for the
    # exact approved request, and no new approval request.
    assert provider_calls == [{"value": 7}]
    stream = await events.list_stream("workspace:ws-1898")
    types = [event.type for event in stream]
    assert types.count("capability.invocation.approval_required") == 1
    assert "capability.invocation.approval_satisfied" in types


async def test_denied_capability_pause_fails_the_run_without_provider_call() -> None:
    store = InMemoryDurableRunStore()
    approvals = InMemoryApprovalStore()
    events = InMemoryEventStore()
    provider_calls: list[dict[str, Any]] = []

    record, node = await _park(store, approvals, events, provider_calls)
    request_id = thaw_json_value(record.graph_state.metadata)["pause"]["metadata"][
        "approval_request_id"
    ]

    await approvals.resolve(str(request_id), approved=False, actor="mallory")
    await store.submit_hitl_answer(
        record.run.run_id, "effect", {"answer": "denied"}, authorization=hitl_authorization()
    )
    resumed = await resume_durable_dag(
        record.run.run_id,
        store=store,
        node_resolver=_resolver(node),
    )

    # The governed authority refuses the denied approval; the helper never
    # converts it into a completion, and the provider is never called.
    assert resumed.status is RunStatus.FAILED
    assert provider_calls == []
    stream = await events.list_stream("workspace:ws-1898")
    assert [event.type for event in stream].count("capability.invocation.approval_required") == 1
