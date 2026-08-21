"""Policy enforcement and causal audit events around canonical capability Invocations."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from maistro.capabilities.approval_store import (
    ApprovalStatus,
    ApprovalStore,
    DurableApproval,
    approval_request_digest,
    redact_approval_value,
)
from maistro.capabilities.binding import Binding
from maistro.capabilities.invocation import (
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
    ProviderExecutor,
    ProviderResolver,
)
from maistro.capabilities.slots.approval import ApprovalRequest
from maistro.events.envelope import EventEnvelope, EventStore
from maistro.policy.types import Decision, PolicyVerdict


@dataclass(frozen=True)
class InvocationPolicyContext:
    """Canonical execution identity available to capability policy evaluation.

    ``approved`` is false for the ordinary prospective evaluation. When a
    durable human approval already exists for the exact logical effect payload,
    the evaluator is called once more with ``approved=True`` before provider
    dispatch. Stateful evaluators such as ``SequencePolicyEngine.charge`` must
    use that flag so the approved action is committed to cumulative policy state.
    """

    run_id: str
    node_run_id: str
    attempt_id: str
    effect_key: str
    approved: bool = False


PolicyEvaluator = Callable[[Binding, Any, InvocationPolicyContext], Awaitable[PolicyVerdict]]


class InvocationDenied(PermissionError):
    """Policy explicitly denied a capability Invocation."""


class InvocationApprovalRequired(PermissionError):
    """Policy requires human approval before an Invocation may proceed."""


class InvocationApprovalPending(InvocationApprovalRequired):
    """A durable approval request exists and execution may release its worker."""

    def __init__(self, request_id: str, message: str) -> None:
        self.request_id = request_id
        super().__init__(message)


class GovernedInvocationExecutionService:
    """Apply policy once, record the decision, then cross the Invocation boundary.

    Physical provider-call lifecycle and effect idempotency remain delegated to
    :class:`InvocationExecutionService`. When an ApprovalStore is supplied,
    REQUIRE_APPROVAL is keyed to the logical effect so a later Attempt reuses
    the same durable human decision rather than manufacturing another request.
    """

    def __init__(
        self,
        *,
        invocation_service: InvocationExecutionService,
        event_store: EventStore,
        policy_evaluator: PolicyEvaluator,
        approval_store: ApprovalStore | None = None,
    ) -> None:
        self._invocations = invocation_service
        self._events = event_store
        self._policy = policy_evaluator
        self._approvals = approval_store

    async def latest_effect(
        self,
        *,
        binding: Binding,
        run_id: str,
        node_run_id: str,
        effect_key: str,
    ) -> Invocation | None:
        """Expose canonical effect history without bypassing governed execution."""

        return await self._invocations.latest_effect(
            binding=binding,
            run_id=run_id,
            node_run_id=node_run_id,
            effect_key=effect_key,
        )

    async def invoke(
        self,
        *,
        binding: Binding,
        run_id: str,
        node_run_id: str,
        attempt_id: str,
        effect_key: str,
        request: Any,
        resolver: ProviderResolver,
        executor: ProviderExecutor,
    ) -> Invocation:
        context = InvocationPolicyContext(
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            effect_key=effect_key,
        )
        verdict = await self._policy(binding, request, context)
        policy_event = await self._append_policy_event(
            binding=binding,
            context=context,
            verdict=verdict,
        )

        if verdict.decision is Decision.DENY:
            raise InvocationDenied(verdict.reason or "capability invocation denied by policy")

        existing_approval = await self._find_approval(
            binding=binding,
            run_id=run_id,
            node_run_id=node_run_id,
            effect_key=effect_key,
        )
        if existing_approval is not None or verdict.decision is Decision.REQUIRE_APPROVAL:
            policy_event = await self._enforce_approval(
                binding=binding,
                run_id=run_id,
                node_run_id=node_run_id,
                attempt_id=attempt_id,
                effect_key=effect_key,
                request=request,
                verdict=verdict,
                policy_event=policy_event,
                existing=existing_approval,
            )

        try:
            invocation = await self._invocations.invoke(
                binding=binding,
                run_id=run_id,
                node_run_id=node_run_id,
                attempt_id=attempt_id,
                effect_key=effect_key,
                request=request,
                resolver=resolver,
                executor=executor,
            )
        except asyncio.CancelledError:
            await self._append_latest_terminal_event(
                binding=binding,
                run_id=run_id,
                node_run_id=node_run_id,
                effect_key=effect_key,
                causation_id=policy_event.event_id,
            )
            raise
        except Exception:
            await self._append_latest_terminal_event(
                binding=binding,
                run_id=run_id,
                node_run_id=node_run_id,
                effect_key=effect_key,
                causation_id=policy_event.event_id,
            )
            raise

        await self._append_terminal_event(
            invocation,
            binding=binding,
            causation_id=policy_event.event_id,
        )
        return invocation

    async def _append_policy_event(
        self,
        *,
        binding: Binding,
        context: InvocationPolicyContext,
        verdict: PolicyVerdict,
        # "" and not None: EventEnvelope.causation_id is a plain `str` field on a
        # dataclass, so it does not validate, and the event store's column is
        # `causation_id TEXT NOT NULL DEFAULT ''`. Defaulting to None let the
        # first policy event of every invocation (the uncaused one, from the
        # `invoke` entry path) carry a None straight through construction and
        # into an INSERT that would violate NOT NULL. In-memory stores never
        # noticed; a SQL-backed one would fail on the common path.
        causation_id: str = "",
    ) -> EventEnvelope:
        return await self._events.append(
            EventEnvelope(
                type="capability.invocation.policy_decision",
                workspace_id=binding.workspace_id,
                project_id=binding.project_id,
                run_id=context.run_id,
                node_run_id=context.node_run_id,
                attempt_id=context.attempt_id,
                correlation_id=context.run_id,
                causation_id=causation_id,
                source="maistro.capabilities",
                payload={
                    "binding_id": binding.binding_id,
                    "capability": binding.capability,
                    "effect_key": context.effect_key,
                    "approved": context.approved,
                    "decision": verdict.decision.value,
                    "reason": verdict.reason,
                    "rule": verdict.rule,
                },
            )
        )

    async def _find_approval(
        self,
        *,
        binding: Binding,
        run_id: str,
        node_run_id: str,
        effect_key: str,
    ) -> DurableApproval | None:
        if self._approvals is None:
            return None
        return await self._approvals.find_effect(
            run_id=run_id,
            node_run_id=node_run_id,
            binding_id=binding.binding_id,
            effect_key=effect_key,
        )

    async def _enforce_approval(
        self,
        *,
        binding: Binding,
        run_id: str,
        node_run_id: str,
        attempt_id: str,
        effect_key: str,
        request: Any,
        verdict: PolicyVerdict,
        policy_event: EventEnvelope,
        existing: DurableApproval | None = None,
    ) -> EventEnvelope:
        if self._approvals is None:
            raise InvocationApprovalRequired(
                verdict.reason or "capability invocation requires approval"
            )

        request_digest = approval_request_digest(request)
        if existing is None:
            existing = await self._approvals.find_effect(
                run_id=run_id,
                node_run_id=node_run_id,
                binding_id=binding.binding_id,
                effect_key=effect_key,
            )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise InvocationDenied(
                    f"approval {existing.request.request_id!r} does not match the current request"
                )
            if existing.status is ApprovalStatus.APPROVED:
                return await self._resume_approved_effect(
                    binding=binding,
                    run_id=run_id,
                    node_run_id=node_run_id,
                    attempt_id=attempt_id,
                    effect_key=effect_key,
                    request=request,
                    policy_event=policy_event,
                    approval=existing,
                )
            if existing.status is ApprovalStatus.DENIED:
                raise InvocationDenied(f"approval {existing.request.request_id!r} was denied")
            await self._emit_approval_required(
                approval=existing,
                binding=binding,
                attempt_id=attempt_id,
                verdict=verdict,
                policy_event=policy_event,
            )
            raise InvocationApprovalPending(
                existing.request.request_id,
                verdict.reason or "capability invocation requires approval",
            )

        approval_request = ApprovalRequest(
            action=f"invoke:{binding.capability}",
            params={
                "binding_id": binding.binding_id,
                "effect_key": effect_key,
                "request_digest": request_digest,
                "request": redact_approval_value(request),
            },
            tier="policy",
            requester=node_run_id,
            rationale=verdict.reason,
        )
        approval = await self._approvals.create(
            DurableApproval(
                request=approval_request,
                workspace_id=binding.workspace_id,
                project_id=binding.project_id,
                run_id=run_id,
                node_run_id=node_run_id,
                attempt_id=attempt_id,
                binding_id=binding.binding_id,
                effect_key=effect_key,
                request_digest=request_digest,
            )
        )
        await self._emit_approval_required(
            approval=approval,
            binding=binding,
            attempt_id=attempt_id,
            verdict=verdict,
            policy_event=policy_event,
        )
        raise InvocationApprovalPending(
            approval.request.request_id,
            verdict.reason or "capability invocation requires approval",
        )

    async def _resume_approved_effect(
        self,
        *,
        binding: Binding,
        run_id: str,
        node_run_id: str,
        attempt_id: str,
        effect_key: str,
        request: Any,
        policy_event: EventEnvelope,
        approval: DurableApproval,
    ) -> EventEnvelope:
        """Re-run policy for an already-approved effect and record its satisfaction.

        Policy is asked again with ``approved=True`` rather than trusted from the
        stored decision: an approval authorises this exact request, it does not
        exempt it from a policy that has since started denying it.
        """
        approved_context = InvocationPolicyContext(
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            effect_key=effect_key,
            approved=True,
        )
        approved_verdict = await self._policy(binding, request, approved_context)
        approved_policy_event = await self._append_policy_event(
            binding=binding,
            context=approved_context,
            verdict=approved_verdict,
            causation_id=policy_event.event_id,
        )
        if approved_verdict.decision is not Decision.ALLOW:
            raise InvocationDenied(
                approved_verdict.reason
                or "approved capability invocation was not accepted by policy"
            )
        await self._events.append(
            EventEnvelope(
                type="capability.invocation.approval_satisfied",
                workspace_id=binding.workspace_id,
                project_id=binding.project_id,
                run_id=run_id,
                node_run_id=node_run_id,
                attempt_id=attempt_id,
                correlation_id=run_id,
                causation_id=approved_policy_event.event_id,
                source="maistro.capabilities",
                payload={
                    "request_id": approval.request.request_id,
                    "actor": approval.actor,
                    "binding_id": binding.binding_id,
                    "effect_key": effect_key,
                },
            )
        )
        return approved_policy_event

    async def _emit_approval_required(
        self,
        *,
        approval: DurableApproval,
        binding: Binding,
        attempt_id: str,
        verdict: PolicyVerdict,
        policy_event: EventEnvelope,
    ) -> None:
        await self._events.append(
            EventEnvelope(
                type="capability.invocation.approval_required",
                workspace_id=binding.workspace_id,
                project_id=binding.project_id,
                run_id=approval.run_id,
                node_run_id=approval.node_run_id,
                attempt_id=attempt_id,
                correlation_id=approval.run_id,
                causation_id=policy_event.event_id,
                source="maistro.capabilities",
                payload={
                    "request_id": approval.request.request_id,
                    "binding_id": binding.binding_id,
                    "capability": binding.capability,
                    "effect_key": approval.effect_key,
                    "reason": verdict.reason,
                    "rule": verdict.rule,
                },
            )
        )

    async def _append_latest_terminal_event(
        self,
        *,
        binding: Binding,
        run_id: str,
        node_run_id: str,
        effect_key: str,
        causation_id: str,
    ) -> None:
        invocation = await self.latest_effect(
            binding=binding,
            run_id=run_id,
            node_run_id=node_run_id,
            effect_key=effect_key,
        )
        if invocation is None or invocation.status not in {
            InvocationStatus.COMPLETED,
            InvocationStatus.FAILED,
            InvocationStatus.UNKNOWN,
        }:
            return
        await self._append_terminal_event(
            invocation,
            binding=binding,
            causation_id=causation_id,
        )

    async def _append_terminal_event(
        self,
        invocation: Invocation,
        *,
        binding: Binding,
        causation_id: str,
    ) -> None:
        """Append one idempotent terminal audit fact for a persisted Invocation."""

        await self._events.append(
            EventEnvelope(
                event_id=(
                    f"capability-invocation-{invocation.invocation_id}-{invocation.status.value}"
                ),
                type=f"capability.invocation.{invocation.status.value}",
                workspace_id=binding.workspace_id,
                project_id=binding.project_id,
                run_id=invocation.run_id,
                node_run_id=invocation.node_run_id,
                attempt_id=invocation.attempt_id,
                invocation_id=invocation.invocation_id,
                correlation_id=invocation.run_id,
                causation_id=causation_id,
                source="maistro.capabilities",
                payload={
                    "binding_id": invocation.binding.binding_id,
                    "capability": invocation.binding.capability,
                    "effect_key": invocation.effect_key,
                    "provider_name": invocation.binding.provider_name,
                    "status": invocation.status.value,
                    "error": invocation.error,
                },
            )
        )


__all__ = [
    "GovernedInvocationExecutionService",
    "InvocationApprovalPending",
    "InvocationApprovalRequired",
    "InvocationDenied",
    "InvocationPolicyContext",
    "PolicyEvaluator",
]
