"""Admit approval-gated infra effects as durable waiting-human NodeRuns (#2405).

``InboxApproval`` waits on an in-process ``asyncio.Event``. That wait dies with
the process and never appears in ``/v1/hitl`` discovery. Self-repair instead
admits a one-node Graph that pauses on ``awaiting_human_approval`` through the
existing governed Invocation + ``invoke_capability_effect`` seam (#1898).

The returned Run is ``PAUSED`` with a persisted ``DurableApproval``. Answering
and resuming remain the HITL / ApprovalStore doors (#55 owns HITL→store
resolve linkage); this module only admits the wait so it survives restart.
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
from maistro.capabilities.slots.infra import ActionResult, ActionTier, InfraAction, tier_for
from maistro.graph.definitions import Graph, Node
from maistro.graph.durable_runs import (
    DurableRunRecord,
    DurableRunStore,
    RunStatus,
    durable_graph_launch_provenance,
    run_durable_graph,
)
from maistro.graph.nodes.base import BaseNode, NodeContext
from maistro.graph.nodes.capability_effect import invoke_capability_effect
from maistro.policy.types import Decision, PolicyVerdict

#: Stable node id for the single-effect self-repair approval Graph.
SELF_REPAIR_APPROVAL_NODE_ID = "self_repair_action"


class _InfraActionIn(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    effect_key: str


class _InfraActionOut(BaseModel):
    ok: bool
    detail: str = ""
    blocked_pending_approval: bool = False


class _InfraApprovalNode(BaseNode[_InfraActionIn, _InfraActionOut]):
    """Governed infra_action that parks on human approval before the host call."""

    kind: ClassVar[str] = "infra.approval_gated_action"
    kind_category: ClassVar = "sync.tool"
    input_schema: ClassVar[type[BaseModel]] = _InfraActionIn
    output_schema: ClassVar[type[BaseModel]] = _InfraActionOut
    external_io: ClassVar[bool] = True

    def __init__(
        self,
        *,
        service: GovernedInvocationExecutionService,
        binding: Binding,
        resolve_provider: Callable[[Binding], Awaitable[InfraAction]],
        execute_approved: Callable[[InfraAction, str, dict[str, Any]], Awaitable[ActionResult]],
    ) -> None:
        self._service = service
        self._binding = binding
        self._resolve_provider = resolve_provider
        self._execute_approved = execute_approved

    async def _execute(self, inputs: _InfraActionIn, ctx: NodeContext) -> _InfraActionOut:
        request: dict[str, Any] = {
            "action": inputs.action,
            "params": dict(inputs.params),
        }

        async def resolver(candidate: Binding) -> InfraAction:
            return await self._resolve_provider(candidate)

        async def executor(provider: ResolvedCapabilityProvider, payload: Any) -> dict[str, Any]:
            if not isinstance(provider, InfraAction):
                raise TypeError("infra approval Invocation resolved a non-infra provider")
            body = dict(payload) if isinstance(payload, Mapping) else {}
            result = await self._execute_approved(
                provider,
                str(body.get("action") or ""),
                dict(body.get("params") or {}),
            )
            return {
                "ok": result.ok,
                "detail": result.detail,
                "blocked_pending_approval": result.blocked_pending_approval,
            }

        invocation = await invoke_capability_effect(
            lambda: self._service.invoke(
                binding=self._binding,
                run_id=ctx.run_id,
                node_run_id=ctx.node_run_id,
                attempt_id=ctx.attempt_id,
                effect_key=inputs.effect_key,
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
        return _InfraActionOut(
            ok=bool(result.get("ok")),
            detail=str(result.get("detail") or ""),
            blocked_pending_approval=bool(result.get("blocked_pending_approval")),
        )


async def _require_approval_policy(
    _binding: Binding,
    _request: Any,
    context: InvocationPolicyContext,
) -> PolicyVerdict:
    if context.approved:
        return PolicyVerdict(Decision.ALLOW, reason="approved", rule="self-repair-hitl")
    return PolicyVerdict(
        Decision.REQUIRE_APPROVAL,
        reason="self-repair action requires human approval",
        rule="self-repair-hitl",
    )


def _approval_graph(
    *,
    workspace_id: str,
    project_id: str,
    action: str,
    params: Mapping[str, Any],
    effect_key: str,
) -> Graph:
    return Graph(
        graph_id=f"self-repair-approval:{effect_key}",
        workspace_id=workspace_id,
        project_id=project_id,
        name=f"self-repair approval ({action})",
        nodes=[
            Node(
                node_id=SELF_REPAIR_APPROVAL_NODE_ID,
                node_type="infra.approval_gated_action",
                inputs={
                    "action": action,
                    "params": dict(params),
                    "effect_key": effect_key,
                },
                parameters={},
                metadata={},
            )
        ],
        edges=[],
        metadata={"entry_node": SELF_REPAIR_APPROVAL_NODE_ID, "admission_source": "self_repair"},
    )


async def admit_self_repair_approval(
    *,
    store: DurableRunStore,
    effect_context: CapabilityEffectContext,
    binding: Binding,
    workspace_id: str,
    project_id: str,
    action: str,
    params: Mapping[str, Any],
    effect_key: str,
    resolve_provider: Callable[[Binding], Awaitable[InfraAction]],
    actor_principal_id: str | None = None,
    run_store: Any | None = None,
) -> DurableRunRecord:
    """Park one self-repair action on a durable waiting-human NodeRun.

    ``workspace_id`` / ``project_id`` are the canonical authorization scope for
    the admitted Run (HITL discovery and settlement). They must be a real
    Workspace + Project the operator can authorize — not the synthetic
    effect-Binding ids used only for ``infra_action`` resolution.

    When ``run_store`` is set, a canonical Run is admitted first (QUEUED, with
    durable launch provenance) and its id is passed to the executor. Calling
    ``run_durable_graph`` with a store and no admitted ``run_id`` raises
    ``RunIntegrityError``.

    Raises ``ValueError`` when the action does not require approval (caller
    should auto-run those). Returns the durable record; status is ``PAUSED``.
    """
    tier = tier_for(action, dict(params))
    if tier is ActionTier.READ:
        raise ValueError(f"action {action!r} does not require durable approval")
    if not workspace_id.strip() or not project_id.strip():
        raise ValueError("workspace_id and project_id are required for durable HITL scope")

    if effect_context.approval_store is None:
        raise RuntimeError("CapabilityEffectContext has no ApprovalStore for durable HITL")

    # Narrow policy to REQUIRE_APPROVAL without inventing a second Invocation
    # authority — shares Binding/store/ApprovalStore with the process context.
    gated = effect_context.with_policy_evaluator(_require_approval_policy)
    service: GovernedInvocationExecutionService = gated.invocations

    async def execute_approved(
        provider: InfraAction, approved_action: str, approved_params: dict[str, Any]
    ) -> ActionResult:
        # The governed seam already verified DurableApproval. HostHealthAction
        # is a pure executor here (#2405): pass approved=True so it never
        # re-enters an in-process inbox wait.
        act = provider.act
        try:
            return await act(approved_action, approved_params, approved=True)
        except TypeError:
            # Providers that have not taken the approved= kwarg yet.
            return await act(approved_action, approved_params)

    node = _InfraApprovalNode(
        service=service,
        binding=binding,
        resolve_provider=resolve_provider,
        execute_approved=execute_approved,
    )
    graph = _approval_graph(
        workspace_id=workspace_id,
        project_id=project_id,
        action=action,
        params=params,
        effect_key=effect_key,
    )

    def resolver(node_id: str, _graph: Graph) -> BaseNode[Any, Any]:
        if node_id != SELF_REPAIR_APPROVAL_NODE_ID:
            raise KeyError(node_id)
        return node

    inputs = {
        "action": action,
        "params": dict(params),
        "effect_key": effect_key,
    }
    provenance = {
        "admission_source": "self_repair",
        "executor": "durable_graph",
        "effect_key": effect_key,
        "action": action,
    }
    actor = actor_principal_id or "self-repair"
    run_id: str | None = None
    if run_store is not None:
        # Admission owns Run identity when the canonical spine is present.
        # Skipping create_run leaves run_durable_graph to raise RunIntegrityError
        # (#2405 Codex P1) — every Hive-wired approval would FAIL closed.
        admitted = await run_store.create_run(
            graph,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=actor,
            provenance={
                **provenance,
                **durable_graph_launch_provenance(inputs=inputs),
            },
        )
        run_id = admitted.run_id

    record = await run_durable_graph(
        graph,
        store=store,
        node_resolver=resolver,
        inputs=inputs,
        actor_principal_id=actor,
        run_id=run_id,
        run_store=run_store,
        provenance=provenance,
    )
    if record.run.status is not RunStatus.PAUSED:
        raise RuntimeError(
            f"self-repair approval admission expected PAUSED, got {record.run.status.value}"
        )
    return record


__all__ = [
    "SELF_REPAIR_APPROVAL_NODE_ID",
    "admit_self_repair_approval",
]
