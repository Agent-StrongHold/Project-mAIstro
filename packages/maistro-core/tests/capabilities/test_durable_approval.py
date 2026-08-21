from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiosqlite
import pytest

from maistro.capabilities.approval_store import (
    ApprovalStatus,
    DurableApproval,
    InMemoryApprovalStore,
    SqliteApprovalStore,
    approval_request_digest,
    redact_approval_value,
)
from maistro.capabilities.binding import Binding
from maistro.capabilities.governed_invocation import (
    GovernedInvocationExecutionService,
    InvocationApprovalPending,
    InvocationDenied,
    InvocationPolicyContext,
)
from maistro.capabilities.invocation import InMemoryInvocationStore, InvocationExecutionService
from maistro.capabilities.slots.approval import ApprovalRequest
from maistro.events.envelope import InMemoryEventStore
from maistro.policy.engine import SequencePolicyEngine
from maistro.policy.rules import AfterCountRule
from maistro.policy.types import Action, Decision, PolicyVerdict


@dataclass(frozen=True)
class _Provider:
    name: str = "provider-a"
    slot: str = "external_write"
    trust_tier: str = "trusted"


def _binding() -> Binding:
    return Binding(
        binding_id="binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="external_write",
        policy_refs=("human-review",),
    )


async def _resolver(_binding: Binding) -> _Provider:
    return _Provider()


async def _approval_policy(
    _binding: Binding,
    _request: Any,
    context: InvocationPolicyContext,
) -> PolicyVerdict:
    if context.approved:
        return PolicyVerdict(Decision.ALLOW, reason="human approval applied", rule="human-review")
    return PolicyVerdict(
        Decision.REQUIRE_APPROVAL,
        reason="human approval required",
        rule="human-review",
    )


async def _allow_policy(
    _binding: Binding,
    _request: Any,
    _context: InvocationPolicyContext,
) -> PolicyVerdict:
    return PolicyVerdict(Decision.ALLOW, reason="allowed", rule="allow")


async def _must_not_execute(_provider: _Provider, _request: Any) -> None:
    raise AssertionError("approval-gated effect must not reach provider")


def _durable_approval(*, request_id: str | None = None) -> DurableApproval:
    request = ApprovalRequest(
        **({"request_id": request_id} if request_id is not None else {}),
        action="invoke:external_write",
        params={"request": {"value": 1}},
        tier="policy",
        requester="node-run-1",
    )
    return DurableApproval(
        request=request,
        workspace_id="ws-1",
        project_id="project-1",
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        binding_id="binding-1",
        effect_key="write:1",
        request_digest=approval_request_digest({"value": 1}),
    )


@pytest.mark.asyncio
async def test_approved_effect_resumes_on_later_attempt_without_second_request() -> None:
    approvals = InMemoryApprovalStore()
    events = InMemoryEventStore()
    calls = 0

    async def execute(_provider: _Provider, request: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"committed": request}

    service = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=events,
        policy_evaluator=_approval_policy,
        approval_store=approvals,
    )

    with pytest.raises(InvocationApprovalPending) as pending:
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="ticket:create:1",
            request={"title": "one"},
            resolver=_resolver,
            executor=execute,
        )
    assert calls == 0

    original = await approvals.get(pending.value.request_id)
    assert original is not None
    assert original.status is ApprovalStatus.PENDING
    await approvals.resolve(original.request.request_id, approved=True, actor="alice")

    invocation = await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-2",
        effect_key="ticket:create:1",
        request={"title": "one"},
        resolver=_resolver,
        executor=execute,
    )

    assert calls == 1
    assert invocation.attempt_id == "attempt-2"
    same = await approvals.find_effect(
        run_id="run-1",
        node_run_id="node-run-1",
        binding_id="binding-1",
        effect_key="ticket:create:1",
    )
    assert same is not None
    assert same.request.request_id == original.request.request_id
    assert same.status is ApprovalStatus.APPROVED
    stream = await events.list_stream("workspace:ws-1")
    assert "capability.invocation.approval_satisfied" in [event.type for event in stream]


@pytest.mark.asyncio
async def test_approved_effect_is_committed_to_stateful_policy_before_execution() -> None:
    approvals = InMemoryApprovalStore()
    events = InMemoryEventStore()
    engine = SequencePolicyEngine([AfterCountRule("external_write", threshold=0)])

    async def policy(
        _binding: Binding,
        _request: Any,
        context: InvocationPolicyContext,
    ) -> PolicyVerdict:
        return engine.charge(
            "run-1",
            Action(kind="external_write", cost=2.5),
            approved=context.approved,
        )

    service = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=events,
        policy_evaluator=policy,
        approval_store=approvals,
    )

    with pytest.raises(InvocationApprovalPending) as pending:
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="write:stateful-policy",
            request={"value": 1},
            resolver=_resolver,
            executor=_must_not_execute,
        )
    assert engine.snapshot("run-1").count == 0

    await approvals.resolve(pending.value.request_id, approved=True, actor="alice")

    async def execute(_provider: _Provider, request: Any) -> dict[str, Any]:
        return {"committed": request}

    await service.invoke(
        binding=_binding(),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-2",
        effect_key="write:stateful-policy",
        request={"value": 1},
        resolver=_resolver,
        executor=execute,
    )

    snapshot = engine.snapshot("run-1")
    assert snapshot.count == 1
    assert snapshot.cost == 2.5
    stream = await events.list_stream("workspace:ws-1")
    approved_decisions = [
        event
        for event in stream
        if event.type == "capability.invocation.policy_decision"
        and event.payload.get("approved") is True
    ]
    assert len(approved_decisions) == 1
    assert approved_decisions[0].payload["decision"] == "allow"


@pytest.mark.asyncio
async def test_denied_effect_stays_denied_on_later_attempt() -> None:
    approvals = InMemoryApprovalStore()
    service = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=InMemoryEventStore(),
        policy_evaluator=_approval_policy,
        approval_store=approvals,
    )

    with pytest.raises(InvocationApprovalPending) as pending:
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="payment:capture:1",
            request={"amount": 10},
            resolver=_resolver,
            executor=_must_not_execute,
        )
    await approvals.resolve(pending.value.request_id, approved=False, actor="bob")

    with pytest.raises(InvocationDenied, match="was denied"):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-2",
            effect_key="payment:capture:1",
            request={"amount": 10},
            resolver=_resolver,
            executor=_must_not_execute,
        )


@pytest.mark.asyncio
async def test_denied_effect_cannot_be_bypassed_by_later_allow() -> None:
    approvals = InMemoryApprovalStore()
    requiring = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=InMemoryEventStore(),
        policy_evaluator=_approval_policy,
        approval_store=approvals,
    )

    with pytest.raises(InvocationApprovalPending) as pending:
        await requiring.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="payment:capture:policy-change",
            request={"amount": 10},
            resolver=_resolver,
            executor=_must_not_execute,
        )
    await approvals.resolve(pending.value.request_id, approved=False, actor="bob")

    allowing = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=InMemoryEventStore(),
        policy_evaluator=_allow_policy,
        approval_store=approvals,
    )
    with pytest.raises(InvocationDenied, match="was denied"):
        await allowing.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-2",
            effect_key="payment:capture:policy-change",
            request={"amount": 10},
            resolver=_resolver,
            executor=_must_not_execute,
        )


@pytest.mark.asyncio
async def test_changed_request_cannot_reuse_approved_effect() -> None:
    approvals = InMemoryApprovalStore()
    service = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=InMemoryEventStore(),
        policy_evaluator=_approval_policy,
        approval_store=approvals,
    )

    with pytest.raises(InvocationApprovalPending) as pending:
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="payment:capture:digest",
            request={"amount": 10},
            resolver=_resolver,
            executor=_must_not_execute,
        )
    await approvals.resolve(pending.value.request_id, approved=True, actor="alice")

    with pytest.raises(InvocationDenied, match="does not match the current request"):
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-2",
            effect_key="payment:capture:digest",
            request={"amount": 11},
            resolver=_resolver,
            executor=_must_not_execute,
        )


@pytest.mark.asyncio
async def test_persisted_approval_snapshot_redacts_secrets_and_keeps_digest() -> None:
    approvals = InMemoryApprovalStore()
    service = GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(store=InMemoryInvocationStore()),
        event_store=InMemoryEventStore(),
        policy_evaluator=_approval_policy,
        approval_store=approvals,
    )
    request = {
        "amount": 10,
        "headers": {"Authorization": "Bearer abc"},
        "credentials": {"api_key": "secret-value"},
    }

    with pytest.raises(InvocationApprovalPending) as pending:
        await service.invoke(
            binding=_binding(),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key="payment:capture:redacted",
            request=request,
            resolver=_resolver,
            executor=_must_not_execute,
        )

    persisted = await approvals.get(pending.value.request_id)
    assert persisted is not None
    assert persisted.request_digest == approval_request_digest(request)
    assert persisted.request.params["request"] == {
        "amount": 10,
        "headers": {"Authorization": "[REDACTED]"},
        "credentials": "[REDACTED]",
    }
    assert "secret-value" not in persisted.model_dump_json()
    assert "Bearer abc" not in persisted.model_dump_json()


@pytest.mark.asyncio
async def test_sqlite_approval_survives_reopen_and_resolves_by_effect(tmp_path) -> None:
    path = tmp_path / "approvals.db"
    approval = _durable_approval()
    request_id = approval.request.request_id

    async with aiosqlite.connect(path) as conn:
        store = SqliteApprovalStore(conn)
        await store.ensure_schema()
        await store.create(approval)

    async with aiosqlite.connect(path) as conn:
        reopened = SqliteApprovalStore(conn)
        await reopened.ensure_schema()
        persisted = await reopened.find_effect(
            run_id="run-1",
            node_run_id="node-run-1",
            binding_id="binding-1",
            effect_key="write:1",
        )
        assert persisted is not None
        assert persisted.request.request_id == request_id
        resolved = await reopened.resolve(request_id, approved=True, actor="alice")
        assert resolved.status is ApprovalStatus.APPROVED
        assert resolved.actor == "alice"


def test_approval_request_digest_binds_exact_payload() -> None:
    first = approval_request_digest({"amount": 10, "currency": "USD"})
    reordered = approval_request_digest({"currency": "USD", "amount": 10})
    changed = approval_request_digest({"amount": 11, "currency": "USD"})

    assert first == reordered
    assert first != changed


def test_redact_approval_value_removes_nested_credentials() -> None:
    redacted = redact_approval_value(
        {
            "title": "safe",
            "headers": {"Authorization": "Bearer abc", "x-trace": "ok"},
            "nested": [{"api_key": "secret", "value": 7}],
        }
    )

    assert redacted == {
        "title": "safe",
        "headers": {"Authorization": "[REDACTED]", "x-trace": "ok"},
        "nested": [{"api_key": "[REDACTED]", "value": 7}],
    }


def test_redact_approval_value_preserves_path_but_redacts_pat() -> None:
    assert redact_approval_value({"path": "/tmp/result", "pat": "ghp_secret"}) == {
        "path": "/tmp/result",
        "pat": "[REDACTED]",
    }


@pytest.mark.asyncio
async def test_sqlite_concurrent_resolution_commits_only_one_decision(tmp_path) -> None:
    path = tmp_path / "approvals-race.db"
    approval = _durable_approval(request_id="approval-race")

    async with aiosqlite.connect(path) as setup_conn:
        setup = SqliteApprovalStore(setup_conn)
        await setup.ensure_schema()
        await setup.create(approval)

    async with (
        aiosqlite.connect(path, timeout=5) as first_conn,
        aiosqlite.connect(path, timeout=5) as second_conn,
    ):
        first = SqliteApprovalStore(first_conn)
        second = SqliteApprovalStore(second_conn)
        first_result, second_result = await asyncio.gather(
            first.resolve("approval-race", approved=True, actor="alice"),
            second.resolve("approval-race", approved=False, actor="bob"),
        )

        assert first_result.status == second_result.status
        assert first_result.actor == second_result.actor

        persisted = await first.get("approval-race")
        assert persisted is not None
        assert persisted.status == first_result.status
        assert persisted.actor == first_result.actor
