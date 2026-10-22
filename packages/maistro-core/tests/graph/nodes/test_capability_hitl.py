from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import pytest
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
from maistro.graph.execution_state import GraphExecutionState
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


# --- #1898: optional continuation through the canonical approval pause ------


class _ContinuationNode(BaseNode[_Input, _Output]):
    """The same governed effect as ``_CapabilityNode``, with the #1898
    continuation arguments configurable per test plus spies for policy hooks
    and physical provider calls."""

    kind: ClassVar[str] = "test.capability_effect_continuation"
    kind_category: ClassVar = "sync.tool"
    input_schema: ClassVar[type[BaseModel]] = _Input
    output_schema: ClassVar[type[BaseModel]] = _Output
    external_io: ClassVar[bool] = True

    def __init__(
        self,
        service: GovernedInvocationExecutionService,
        binding: Binding,
        *,
        continuation_metadata: Mapping[str, Any] | None = None,
        resume_at: datetime | None = None,
        request_digest_of: Callable[[dict[str, Any]], str] | None = None,
        on_policy: Callable[[Any], None] | None = None,
        provider_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        self._service = service
        self._binding = binding
        self._continuation = continuation_metadata
        self._resume_at = resume_at
        self._digest_of = request_digest_of
        self._on_policy = on_policy
        self._provider_calls = provider_calls

    async def _execute(self, inputs: _Input, ctx: NodeContext) -> _Output:
        request: dict[str, Any] = {"value": inputs.value}

        async def resolver(_binding: Binding) -> _Provider:
            return _Provider()

        async def execute(_provider: _Provider, req: Any) -> dict[str, Any]:
            if self._provider_calls is not None:
                self._provider_calls.append(dict(req))
            return {"committed": req}

        invocation = await invoke_capability_effect(
            lambda: self._service.invoke(
                binding=self._binding,
                run_id=ctx.run_id,
                node_run_id=ctx.node_run_id,
                attempt_id=ctx.attempt_id,
                effect_key="write:1",
                request=request,
                resolver=resolver,
                executor=execute,
            ),
            effect_key="write:1",
            continuation_metadata=self._continuation,
            resume_at=self._resume_at,
            request_digest=self._digest_of(request) if self._digest_of else None,
        )
        assert isinstance(invocation.result, dict)
        committed = invocation.result["committed"]
        assert isinstance(committed, dict)
        return _Output(value=int(committed["value"]))


def _continuation_binding() -> Binding:
    return Binding(
        binding_id="binding-cont",
        workspace_id="ws-cont",
        project_id="project-cont",
        node_id="node-cont",
        capability="external_write",
        policy_refs=("human-review",),
    )


def _continuation_service(
    approvals: InMemoryApprovalStore,
    events: InMemoryEventStore,
    *,
    on_policy: Callable[[Any], None] | None = None,
) -> GovernedInvocationExecutionService:
    async def policy(
        _binding: Binding,
        request: Any,
        context: InvocationPolicyContext,
    ) -> PolicyVerdict:
        if on_policy is not None:
            on_policy(request)
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


def _continuation_ctx(attempt_id: str) -> NodeContext:
    return NodeContext(
        run_id="run-cont",
        node_run_id="node-run-cont",
        attempt_id=attempt_id,
        dag_id="graph-cont",
        node_id="node-cont",
    )


async def _spy_operation(calls: list[int]) -> Callable[[], Awaitable[str]]:
    async def operation() -> str:
        calls.append(1)
        return "ran"

    return operation


async def test_successful_operation_return_value_propagates() -> None:
    calls: list[int] = []
    result = await invoke_capability_effect(await _spy_operation(calls), effect_key="write:1")
    assert result == "ran"
    assert calls == [1]


async def test_unrelated_operation_errors_propagate_without_parking() -> None:
    async def operation() -> str:
        raise RuntimeError("provider exploded")

    with pytest.raises(RuntimeError, match="provider exploded"):
        await invoke_capability_effect(operation, effect_key="write:1")


async def test_omitted_continuation_preserves_default_pause_shape() -> None:
    approvals = InMemoryApprovalStore()
    events = InMemoryEventStore()
    node = _ContinuationNode(_continuation_service(approvals, events), _continuation_binding())

    first = await node.run(_Input(value=7), _continuation_ctx("attempt-1"))
    assert first.status == "paused"
    assert first.metadata["paused_reason"] == "awaiting_human_approval"
    # Exactly the pre-#1898 two pause keys plus the reason; no resume time.
    assert set(first.metadata) == {"paused_reason", "approval_request_id", "effect_key"}
    assert first.metadata["effect_key"] == "write:1"
    assert first.resume_at is None

    await approvals.resolve(
        str(first.metadata["approval_request_id"]), approved=True, actor="alice"
    )
    resumed = await node.run(_Input(value=7), _continuation_ctx("attempt-2"))
    assert resumed.status == "completed"
    assert resumed.output is not None and resumed.output.value == 7


async def test_pending_approval_retains_continuation_receipt_and_deadline() -> None:
    approvals = InMemoryApprovalStore()
    events = InMemoryEventStore()
    deadline = datetime(2030, 3, 4, 5, 6, 7, tzinfo=ZoneInfo("Asia/Kolkata"))
    provider_calls: list[dict[str, Any]] = []
    node = _ContinuationNode(
        _continuation_service(approvals, events),
        _continuation_binding(),
        continuation_metadata={
            "question": "Ship write:1?",
            "observation": {"ordinal": 3, "tags": ["a", "b"]},
        },
        resume_at=deadline,
        request_digest_of=approval_request_digest,
        provider_calls=provider_calls,
    )

    first = await node.run(_Input(value=7), _continuation_ctx("attempt-1"))
    assert first.status == "paused"
    assert set(first.metadata) == {
        "paused_reason",
        "approval_request_id",
        "effect_key",
        "request_digest",
        "question",
        "observation",
    }
    approval = await approvals.find_effect(
        run_id="run-cont",
        node_run_id="node-run-cont",
        binding_id="binding-cont",
        effect_key="write:1",
    )
    assert approval is not None
    # Exact receipt: the canonical approval_request_id and the caller's digest
    # of the exact immutable request passed to governed invoke.
    assert first.metadata["approval_request_id"] == approval.request.request_id
    assert first.metadata["request_digest"] == approval.request_digest
    assert first.metadata["request_digest"] == approval_request_digest({"value": 7})
    assert first.metadata["observation"] == {"ordinal": 3, "tags": ["a", "b"]}
    # Fixed deadline: preserved verbatim, never normalized or re-derived.
    assert first.resume_at == deadline
    assert first.resume_at is not None and first.resume_at.utcoffset() == deadline.utcoffset()
    assert provider_calls == []
    stream = await events.list_stream("workspace:ws-cont")
    assert [e.type for e in stream].count("capability.invocation.approval_required") == 1

    await approvals.resolve(
        str(first.metadata["approval_request_id"]), approved=True, actor="alice"
    )
    resumed = await node.run(_Input(value=7), _continuation_ctx("attempt-2"))
    assert resumed.status == "completed"
    assert resumed.output is not None and resumed.output.value == 7
    # One physical provider call across both Attempts; no new approval request.
    assert provider_calls == [{"value": 7}]
    stream = await events.list_stream("workspace:ws-cont")
    types = [e.type for e in stream]
    assert types.count("capability.invocation.approval_required") == 1
    assert "capability.invocation.approval_satisfied" in types


async def test_continuation_metadata_is_copied_before_the_operation_runs() -> None:
    approvals = InMemoryApprovalStore()
    events = InMemoryEventStore()
    nested: dict[str, Any] = {"tags": ["a"], "counts": {"one": 1}}
    continuation: dict[str, Any] = {"question": "Proceed?", "nested": nested}

    def mutate_after_entry(_request: Any) -> None:
        # Runs inside governed invoke, i.e. after helper entry.
        nested["tags"].append("MUTATED")
        nested["counts"]["one"] = 999
        continuation["injected"] = "later"

    node = _ContinuationNode(
        _continuation_service(approvals, events, on_policy=mutate_after_entry),
        _continuation_binding(),
        continuation_metadata=continuation,
    )

    first = await node.run(_Input(value=7), _continuation_ctx("attempt-1"))
    assert first.status == "paused"
    assert first.metadata["nested"] == {"tags": ["a"], "counts": {"one": 1}}
    assert "injected" not in first.metadata


async def test_frozen_graph_json_continuation_is_copied_without_deepcopy() -> None:
    approvals = InMemoryApprovalStore()
    events = InMemoryEventStore()
    state = GraphExecutionState.model_validate(
        {
            "run_id": "run-cont",
            "metadata": {"question": {"text": "Proceed?", "tags": ["a", "b"]}},
        }
    )
    frozen = state.metadata
    # The fixture is genuinely frozen Graph JSON: naive deepcopy cannot handle
    # it, which is why the helper must thaw before copying.
    with pytest.raises(TypeError):
        copy.deepcopy(frozen)

    node = _ContinuationNode(
        _continuation_service(approvals, events),
        _continuation_binding(),
        continuation_metadata=frozen,
    )
    first = await node.run(_Input(value=7), _continuation_ctx("attempt-1"))
    assert first.status == "paused"
    assert first.metadata["question"] == {"text": "Proceed?", "tags": ["a", "b"]}


_RESERVED_CONTINUATION_KEYS = [
    "approval_request_id",
    "effect_key",
    "paused_reason",
    "request_digest",
    "resume_at",
    "replay_effect_key",
]


@pytest.mark.parametrize("reserved_key", _RESERVED_CONTINUATION_KEYS)
async def test_reserved_continuation_key_fails_before_operation(reserved_key: str) -> None:
    calls: list[int] = []
    with pytest.raises(ValueError, match=reserved_key):
        await invoke_capability_effect(
            await _spy_operation(calls),
            effect_key="write:1",
            continuation_metadata={reserved_key: "caller-value"},
        )
    assert calls == []


@pytest.mark.parametrize(
    "bad_digest",
    ["z" * 64, "a" * 63, "a" * 65, "A" * 64, "", 64],
)
async def test_invalid_request_digest_fails_before_operation(bad_digest: Any) -> None:
    calls: list[int] = []
    with pytest.raises(ValueError, match="request_digest"):
        await invoke_capability_effect(
            await _spy_operation(calls),
            effect_key="write:1",
            request_digest=bad_digest,
        )
    assert calls == []


class _OffsetlessTZ(tzinfo):
    """A tzinfo object alone is not an aware datetime."""

    def utcoffset(self, _dt: datetime | None) -> None:
        return None

    def tzname(self, _dt: datetime | None) -> None:
        return None

    def dst(self, _dt: datetime | None) -> None:
        return None


@pytest.mark.parametrize(
    "bad_resume_at",
    [
        "2030-01-01T00:00:00+00:00",
        datetime(2030, 1, 1),
        datetime(2030, 1, 1, tzinfo=_OffsetlessTZ()),
    ],
)
async def test_naive_or_invalid_resume_at_fails_before_operation(bad_resume_at: Any) -> None:
    calls: list[int] = []
    with pytest.raises(ValueError, match="resume_at"):
        await invoke_capability_effect(
            await _spy_operation(calls),
            effect_key="write:1",
            resume_at=bad_resume_at,
        )
    assert calls == []


async def test_changed_request_digest_is_refused_by_governed_authority() -> None:
    approvals = InMemoryApprovalStore()
    events = InMemoryEventStore()
    provider_calls: list[dict[str, Any]] = []
    node = _ContinuationNode(
        _continuation_service(approvals, events),
        _continuation_binding(),
        request_digest_of=approval_request_digest,
        provider_calls=provider_calls,
    )

    first = await node.run(_Input(value=7), _continuation_ctx("attempt-1"))
    assert first.status == "paused"
    await approvals.resolve(
        str(first.metadata["approval_request_id"]), approved=True, actor="alice"
    )

    # Same key and NodeRun, different request: the stored approval does not
    # match, and the governed authority refuses. The helper must not convert
    # that refusal into a completion.
    second = await node.run(_Input(value=8), _continuation_ctx("attempt-2"))
    assert second.status == "failed"
    assert second.error_code == "InvocationDenied"
    assert provider_calls == []


async def test_denied_approval_is_refused_by_governed_authority() -> None:
    approvals = InMemoryApprovalStore()
    events = InMemoryEventStore()
    provider_calls: list[dict[str, Any]] = []
    node = _ContinuationNode(
        _continuation_service(approvals, events),
        _continuation_binding(),
        provider_calls=provider_calls,
    )

    first = await node.run(_Input(value=7), _continuation_ctx("attempt-1"))
    assert first.status == "paused"
    await approvals.resolve(
        str(first.metadata["approval_request_id"]), approved=False, actor="mallory"
    )

    second = await node.run(_Input(value=7), _continuation_ctx("attempt-2"))
    assert second.status == "failed"
    assert second.error_code == "InvocationDenied"
    assert provider_calls == []
