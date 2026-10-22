"""GovernedInvocationExecutionService composition-root surface (#846).

Covers the governed wrapper's delegated lifecycle (discovery, provider-backed
reconciliation), policy narrowing, and the durable-approval branches a live
operator hits: a re-encountered pending approval must re-deny without a
provider call, and a granted approval must never be able to force a policy
DENY into an allow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.capabilities.approval_store import (
    ApprovalStatus,
    InMemoryApprovalStore,
)
from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.governed_invocation import (
    GovernedInvocationExecutionService,
    InvocationApprovalPending,
    InvocationDenied,
)
from maistro.capabilities.invocation import (
    InMemoryInvocationStore,
    InvocationExecutionService,
    InvocationReconciliationEvidence,
    InvocationStatus,
    ReconciliationDisposition,
)
from maistro.events.envelope import InMemoryEventStore
from maistro.policy.types import Decision, PolicyVerdict


@dataclass(frozen=True)
class _Provider:
    name: str = "provider-a"
    slot: str = "external_write"
    trust_tier: str = "trusted"


def _binding() -> Binding:
    return Binding(
        binding_id="binding-gov-1",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="external_write",
    )


async def _resolver(_binding: Binding) -> _Provider:
    return _Provider()


async def _allow(_binding: Binding, _request: Any, _context: Any) -> PolicyVerdict:
    return PolicyVerdict(Decision.ALLOW, reason="allowed", rule="test.allow")


class _CrashOnCompletedSave(InMemoryInvocationStore):
    """Simulates process death between the provider commit and the save."""

    def __init__(self) -> None:
        super().__init__()
        self.crashing = True

    async def save(self, invocation: Any) -> Any:
        if self.crashing and invocation.status is InvocationStatus.COMPLETED:
            raise _ProcessDeath("process died after the provider committed")
        return await super().save(invocation)


class _ProcessDeath(BaseException):
    pass


def _governed(
    policy: Any = _allow,
    *,
    store: InMemoryInvocationStore | None = None,
    approvals: InMemoryApprovalStore | None = None,
) -> GovernedInvocationExecutionService:
    return GovernedInvocationExecutionService(
        invocation_service=InvocationExecutionService(
            store=store if store is not None else InMemoryInvocationStore()
        ),
        event_store=InMemoryEventStore(),
        policy_evaluator=policy,
        approval_store=approvals,
    )


# --- policy narrowing -------------------------------------------------------


async def test_with_policy_evaluator_narrows_only_the_policy() -> None:
    base = _governed()
    calls: list[Any] = []

    async def execute(_provider: ResolvedCapabilityProvider, request: Any) -> dict[str, Any]:
        calls.append(request)
        return {"committed": request}

    async def deny(_binding: Binding, _request: Any, _context: Any) -> PolicyVerdict:
        return PolicyVerdict(Decision.DENY, reason="narrowed", rule="test.narrow")

    narrowed = base.with_policy_evaluator(deny)

    invocation = await base.invoke(
        binding=_binding(),
        run_id="run-n",
        node_run_id="node-n",
        attempt_id="a1",
        effect_key="write:n",
        request={"v": 1},
        resolver=_resolver,
        executor=execute,
    )
    assert invocation.status is InvocationStatus.COMPLETED

    with pytest.raises(InvocationDenied):
        await narrowed.invoke(
            binding=_binding(),
            run_id="run-n",
            node_run_id="node-n",
            attempt_id="a2",
            effect_key="write:n2",
            request={"v": 2},
            resolver=_resolver,
            executor=execute,
        )
    # The narrowed view shares lifecycle authorities but cannot admit effects.
    assert [c["v"] for c in calls] == [1]


# --- delegated discovery + provider-backed reconciliation -------------------


async def test_governed_root_discovers_and_reconciles_with_provider() -> None:
    store = _CrashOnCompletedSave()
    governed = _governed(store=store)

    async def execute(_provider: ResolvedCapabilityProvider, request: Any) -> dict[str, Any]:
        return {"committed": request}

    with pytest.raises(_ProcessDeath):
        await governed.invoke(
            binding=_binding(),
            run_id="run-r",
            node_run_id="node-r",
            attempt_id="a1",
            effect_key="write:r",
            request={"id": "remote-r"},
            resolver=_resolver,
            executor=execute,
        )

    stale = await governed.discover_ambiguous(stale_before=datetime.now(UTC) + timedelta(seconds=1))
    assert len(stale) == 1
    assert stale[0].effect_key == "write:r"

    @dataclass(frozen=True)
    class _Adapter:
        async def reconcile(self, _invocation: Any) -> InvocationReconciliationEvidence:
            return InvocationReconciliationEvidence(
                disposition=ReconciliationDisposition.APPLIED,
                source="provider-a",
                actor="provider-a",
                reason="remote receipt matched",
                evidence={"receipt": "r1"},
                result={"remote_id": "remote-r"},
            )

    store.crashing = False  # the process is "back": the settled save must succeed
    settled = await governed.reconcile_with_provider(
        stale[0].invocation_id,
        _Adapter(),
        stale_before=datetime.now(UTC),  # the RUNNING row is provably not in-flight anymore
    )
    assert settled.status is InvocationStatus.COMPLETED
    assert settled.reconciliation_history[-1].source == "provider-a"
    # The reconciliation is announced on the governed event stream.
    events = await governed._events.list_stream("workspace:ws-1")
    assert any(e.type == "capability.invocation.completed" for e in events)
    assert settled.status is InvocationStatus.COMPLETED
    assert settled.reconciliation_history[-1].source == "provider-a"
    # The reconciliation is announced on the governed event stream.
    events = await governed._events.list_stream("workspace:ws-1")
    assert any(e.type == "capability.invocation.completed" for e in events)


async def test_governed_reconcile_to_unknown_emits_no_new_terminal_event() -> None:
    store = InMemoryInvocationStore()
    governed = _governed(store=store)

    async def ambiguous(_provider: ResolvedCapabilityProvider, _request: Any) -> None:
        raise ConnectionError("transport lost")

    with pytest.raises(ConnectionError):
        await governed.invoke(
            binding=_binding(),
            run_id="run-u",
            node_run_id="node-u",
            attempt_id="a1",
            effect_key="write:u",
            request={"id": "remote-u"},
            resolver=_resolver,
            executor=ambiguous,
        )
    events = await governed._events.list_stream("workspace:ws-1")
    before = len(events)

    @dataclass(frozen=True)
    class _Indeterminate:
        async def reconcile(self, _invocation: Any) -> InvocationReconciliationEvidence:
            return InvocationReconciliationEvidence(
                disposition=ReconciliationDisposition.INDETERMINATE,
                source="provider-a",
                actor="provider-a",
                reason="provider cannot say whether the write landed",
            )

    history = await store.list_effect(
        run_id="run-u", node_run_id="node-u", binding_id="binding-gov-1", effect_key="write:u"
    )
    unknown = history[0]
    settled = await governed.reconcile_with_provider(unknown.invocation_id, _Indeterminate())
    assert settled.status is InvocationStatus.UNKNOWN

    events_after = await governed._events.list_stream("workspace:ws-1")
    assert len(events_after) == before  # UNKNOWN settles silently: nothing new to announce


# --- durable approval branches ----------------------------------------------


async def _approval_policy(_binding: Binding, _request: Any, context: Any) -> PolicyVerdict:
    if context.approved:
        return PolicyVerdict(Decision.ALLOW, reason="human approval applied", rule="t.approve")
    return PolicyVerdict(
        Decision.REQUIRE_APPROVAL, reason="human approval required", rule="t.approve"
    )


async def test_reencountered_pending_approval_repends_without_provider_call() -> None:
    approvals = InMemoryApprovalStore()
    governed = _governed(_approval_policy, approvals=approvals)
    calls: list[Any] = []

    async def execute(_provider: ResolvedCapabilityProvider, request: Any) -> dict[str, Any]:
        calls.append(request)
        return {"committed": request}

    kwargs: dict[str, Any] = {
        "binding": _binding(),
        "run_id": "run-p",
        "node_run_id": "node-p",
        "attempt_id": "a1",
        "effect_key": "ticket:create:1",
        "request": {"title": "one"},
        "resolver": _resolver,
        "executor": execute,
    }
    with pytest.raises(InvocationApprovalPending) as first:
        await governed.invoke(**kwargs)
    with pytest.raises(InvocationApprovalPending) as second:
        await governed.invoke(**kwargs)

    # Same durable request, no duplicate request manufacturing, no effect.
    assert first.value.request_id == second.value.request_id
    assert calls == []
    stored = await approvals.get(first.value.request_id)
    assert stored is not None and stored.status is ApprovalStatus.PENDING
    events = await governed._events.list_stream("workspace:ws-1")
    assert sum(1 for e in events if e.type == "capability.invocation.approval_required") >= 2


async def test_granted_approval_cannot_force_a_policy_deny() -> None:
    calls: list[Any] = []

    async def execute(_provider: ResolvedCapabilityProvider, request: Any) -> dict[str, Any]:
        calls.append(request)
        return {"committed": request}

    async def suspicious_policy(_binding: Binding, _request: Any, context: Any) -> PolicyVerdict:
        if context.approved:
            return PolicyVerdict(
                Decision.DENY, reason="approval cannot mint scope", rule="t.suspicious"
            )
        return PolicyVerdict(
            Decision.REQUIRE_APPROVAL, reason="human approval", rule="t.suspicious"
        )

    approvals = InMemoryApprovalStore()
    governed = _governed(suspicious_policy, approvals=approvals)
    kwargs: dict[str, Any] = {
        "binding": _binding(),
        "run_id": "run-d",
        "node_run_id": "node-d",
        "attempt_id": "a1",
        "effect_key": "write:d",
        "request": {"id": "remote-d"},
        "resolver": _resolver,
        "executor": execute,
    }
    with pytest.raises(InvocationApprovalPending) as pending:
        await governed.invoke(**kwargs)
    await approvals.resolve(pending.value.request_id, approved=True, actor="alice")

    with pytest.raises(InvocationDenied) as denied:
        await governed.invoke(**kwargs)

    # The service refuses at the approved-resume seam: the policy's DENY stands
    # even though a human granted the approval.
    assert "approval cannot mint scope" in str(denied.value)
    assert calls == []  # the approval never reached the provider
