"""`infra.approval_gated_action` — the reconstructible durable approval wait (#2405).

Self-repair approval admission (#1898 seam) parks one governed infra effect on
a durable waiting-human NodeRun. Until now the node implementation was a
process-local class wired through admission-time closures: a resumed Run could
not rebuild the physical effect from durable facts, so an approved Run was
queued forever and never dispatched (answered-but-never-resumed).

The node is now a registered kind reconstructed from durable, non-secret facts:

- the request (`action`, `params`, `effect_key`) rides the node inputs;
- the Binding *reference* (`binding_id` + its authorization scope) rides the
  Graph metadata, and is re-resolved through the live Container-owned
  Binding authority before any physical dispatch — a revoked or replaced
  Binding fails the node closed rather than falling back;
- the provider is resolved through the Container-owned capability registry
  authority, never a serialized Python object or credential;
- approval evidence is re-checked by the same governed Invocation service
  (`_require_approval_policy`), which finds the settled DurableApproval by
  run + effect identity before the host call.

Nothing here is a second execution authority: dispatch still crosses
`invoke_capability_effect` → `GovernedInvocationExecutionService`, and
waiting/resuming stay the canonical HITL / ApprovalStore doors.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from maistro.capabilities.approval_store import approval_request_digest
from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.governed_invocation import (
    GovernedInvocationExecutionService,
    InvocationPolicyContext,
)
from maistro.capabilities.slots.infra import (
    ActionResult,
    ActionTier,
    InfraAction,
    tier_for,
)
from maistro.policy.types import Decision, PolicyVerdict

from . import register_node
from .base import BaseNode, NodeContext, ReplaySemantics
from .capability_effect import invoke_capability_effect

#: Graph-metadata key carrying the Binding reference a restart re-resolves.
BINDING_REFERENCE_KEY = "binding_reference"


class InfraApprovalActionIn(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    effect_key: str
    # Non-secret Binding *reference* persisted with the Run: recovery
    # re-resolves it through the live Binding authority before dispatch.
    binding_reference: dict[str, Any] | None = None


class InfraApprovalActionOut(BaseModel):
    ok: bool
    detail: str = ""
    blocked_pending_approval: bool = False


async def execute_approved_infra_action(
    provider: InfraAction, approved_action: str, approved_params: dict[str, Any]
) -> ActionResult:
    """Run the approved host call through the provider's pure executor seam.

    HostHealthAction is a pure executor here (#2405): ``approved=True`` means
    the governed seam already verified DurableApproval, so the provider never
    re-enters an in-process inbox wait. Providers that have not taken the
    ``approved=`` kwarg yet keep their legacy two-arg contract.
    """
    act = provider.act
    try:
        return await act(approved_action, approved_params, approved=True)
    except TypeError:
        return await act(approved_action, approved_params)


async def _require_approval_policy(
    _binding: Binding,
    _request: Any,
    context: InvocationPolicyContext,
) -> PolicyVerdict:
    """Narrow policy for the approval-gated infra action (#2405).

    REQUIRE_APPROVAL without a second Invocation authority — the governed
    service shares Binding/store/ApprovalStore with the process context, and
    re-evaluates with ``approved=True`` only over settled approval evidence.
    """
    if context.approved:
        return PolicyVerdict(Decision.ALLOW, reason="approved", rule="self-repair-hitl")
    return PolicyVerdict(
        Decision.REQUIRE_APPROVAL,
        reason="self-repair action requires human approval",
        rule="self-repair-hitl",
    )


def _binding_reference_fields(reference: Mapping[str, Any]) -> dict[str, str]:
    """The non-secret Binding-identity fields a resume re-resolves against."""
    return {
        "binding_id": str(reference.get("binding_id") or ""),
        "workspace_id": str(reference.get("workspace_id") or ""),
        "project_id": str(reference.get("project_id") or ""),
        "node_id": str(reference.get("node_id") or ""),
        "capability": str(reference.get("capability") or ""),
    }


@register_node  # noqa: V102 — instantiated by kind dispatch and by admission
class InfraApprovalActionNode(BaseNode[InfraApprovalActionIn, InfraApprovalActionOut]):
    """Governed infra_action that parks on human approval before the host call.

    Two construction modes, one execution path:

    - **Admission** (``admit_self_repair_approval``) injects the narrowed
      Invocation service, the resolved Binding and the Container-resolved
      provider lookup — exactly the collaborators the admitting process holds.
    - **Recovery** (``compose_node``) receives the Container-owned
      ``effect_context`` and ``capability_registry`` authorities plus the
      durable Binding *reference*, and re-resolves everything live. Missing
      authorities fail composition closed (``NodeCompositionError``); a
      revoked Binding fails the first dispatch closed (``LookupError``).
    """

    kind: ClassVar[str] = "infra.approval_gated_action"
    kind_category: ClassVar = "sync.tool"
    input_schema: ClassVar[type[BaseModel]] = InfraApprovalActionIn
    output_schema: ClassVar[type[BaseModel]] = InfraApprovalActionOut
    external_io: ClassVar[bool] = True
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.EFFECT_KEY

    #: Authorities `compose_node` supplies for restart/recovery construction.
    required_authorities: ClassVar[Mapping[str, str]] = {
        "effect_context": "effect_context",
        "capability_registry": "capability_registry",
    }

    def __init__(
        self,
        *,
        effect_context: CapabilityEffectContext | None = None,
        capability_registry: Any = None,
        binding_id: str = "",
        binding: Binding | None = None,
        binding_reference: Mapping[str, Any] | None = None,
        service: GovernedInvocationExecutionService | None = None,
        resolve_provider: Callable[[Binding], Awaitable[InfraAction]] | None = None,
        execute_approved: Callable[[InfraAction, str, dict[str, Any]], Awaitable[ActionResult]]
        | None = None,
    ) -> None:
        self._effect_context = effect_context
        self._registry = capability_registry
        self._binding = binding
        self._binding_id = binding_id or (binding.binding_id if binding else "")
        self._binding_reference = dict(binding_reference) if binding_reference else None
        self._service = service
        self._resolve_provider = resolve_provider
        self._execute_approved = execute_approved

    # --- collaborator resolution (injected or re-derived from authorities) ---

    def _effective_context(self) -> CapabilityEffectContext:
        if self._effect_context is None:
            raise LookupError(
                "infra.approval_gated_action has no effect_context authority; "
                "refusing ungoverned dispatch"
            )
        return self._effect_context

    def _effective_service(self) -> GovernedInvocationExecutionService:
        if self._service is not None:
            return self._service
        return self._effective_context().with_policy_evaluator(_require_approval_policy).invocations

    async def _effective_binding(self) -> Binding:
        if self._binding is not None:
            return self._binding
        reference = _binding_reference_fields(self._binding_reference or {})
        binding_id = self._binding_id or reference["binding_id"]
        if not binding_id:
            raise LookupError(
                "infra.approval_gated_action has no durable Binding reference; refusing dispatch"
            )
        context = self._effective_context()
        authorized = await context.bindings.resolve(
            binding_id,
            workspace_id=reference["workspace_id"],
            project_id=reference["project_id"],
            node_id=reference["node_id"],
            capability=reference["capability"],
        )
        if authorized.binding_id != binding_id:
            raise LookupError(f"invalid durable self_repair binding {binding_id!r}")
        return authorized

    async def _default_resolve_provider(self, candidate: Binding) -> InfraAction:
        registry = self._registry
        if registry is None:
            raise LookupError(
                "infra.approval_gated_action has no capability_registry authority; "
                "refusing to resolve a provider from nothing"
            )
        provider = await registry.resolve("infra_action")
        if not isinstance(provider, InfraAction):
            raise LookupError("infra_action unavailable")
        return provider

    @staticmethod
    async def _default_execute_approved(
        provider: InfraAction, approved_action: str, approved_params: dict[str, Any]
    ) -> ActionResult:
        return await execute_approved_infra_action(provider, approved_action, approved_params)

    async def _execute(
        self, inputs: InfraApprovalActionIn, ctx: NodeContext
    ) -> InfraApprovalActionOut:
        request: dict[str, Any] = {
            "action": inputs.action,
            "params": dict(inputs.params),
        }
        # Durable facts first: an injected admission Binding wins; otherwise
        # the reference persisted with the Run is re-resolved live (a revoked
        # or replaced Binding fails the dispatch closed).
        if self._binding_reference is None and inputs.binding_reference:
            self._binding_reference = dict(inputs.binding_reference)

        service = self._effective_service()
        binding = await self._effective_binding()

        async def resolver(candidate: Binding) -> InfraAction:
            lookup = self._resolve_provider or self._default_resolve_provider
            return await lookup(candidate)

        async def executor(provider: ResolvedCapabilityProvider, payload: Any) -> dict[str, Any]:
            if not isinstance(provider, InfraAction):
                raise TypeError("infra approval Invocation resolved a non-infra provider")
            body = dict(payload) if isinstance(payload, Mapping) else {}
            run_approved = self._execute_approved or self._default_execute_approved
            result = await run_approved(
                provider,
                str(body.get("action") or ""),
                dict(body.get("params") or {}),
            )
            return {
                "ok": result.ok,
                "detail": result.detail,
                "blocked_pending_approval": result.blocked_pending_approval,
            }

        # ``effect_scope`` is the stable effect key, so approval identity (and
        # effect lookup) survive the crash-window re-entry that rebuilds
        # checkpoint 1 under a fresh NodeRun id for the same Run (#2405).
        invocation = await invoke_capability_effect(
            lambda: service.invoke(
                binding=binding,
                run_id=ctx.run_id,
                node_run_id=ctx.node_run_id,
                attempt_id=ctx.attempt_id,
                effect_key=inputs.effect_key,
                effect_scope=inputs.effect_key,
                request=request,
                resolver=resolver,
                executor=executor,
            ),
            effect_key=inputs.effect_key,
            continuation_metadata={
                "action": inputs.action,
                "params": dict(inputs.params),
                "requester": "self_repair",
            },
            request_digest=approval_request_digest(request),
        )

        result = invocation.result if isinstance(invocation.result, Mapping) else {}
        return InfraApprovalActionOut(
            ok=bool(result.get("ok")),
            detail=str(result.get("detail") or ""),
            blocked_pending_approval=bool(result.get("blocked_pending_approval")),
        )


def binding_reference_of(binding: Binding) -> dict[str, Any]:
    """The non-secret Binding reference persisted with the approval Graph."""
    return {
        "binding_id": binding.binding_id,
        "workspace_id": binding.workspace_id,
        "project_id": binding.project_id,
        "node_id": binding.node_id,
        "capability": binding.capability,
    }


def requires_durable_approval(action: str, params: Mapping[str, Any]) -> bool:
    """Whether this infra action's tier parks on human approval at all."""
    return tier_for(action, dict(params)) is not ActionTier.READ


__all__ = [
    "BINDING_REFERENCE_KEY",
    "InfraApprovalActionIn",
    "InfraApprovalActionNode",
    "InfraApprovalActionOut",
    "binding_reference_of",
    "execute_approved_infra_action",
    "requires_durable_approval",
]
