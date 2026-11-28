"""Admit approval-gated infra effects as durable waiting-human NodeRuns (#2405).

Self-repair approval admission parks one governed infra effect on a durable
one-node Graph so the wait survives restart and appears in ``/v1/hitl``
discovery. The node itself is the registered, restart-reconstructible
``infra.approval_gated_action`` kind; this module owns *admission*:

- the canonical Run is claimed under the incident's stable occurrence claim
  (``self_repair_incident``), so a restart or a second replica racing the
  same unresolved incident reconciles to one Run instead of minting a
  second approval (``DuplicateOccurrence`` losers reuse the winner);
- a crash between ``create_run`` and the durable continuation's first
  checkpoint is recovered by re-entering ``run_durable_graph`` against the
  claimed Run — the launch snapshot in Run provenance rebuilds checkpoint 1
  exactly as admitted;
- an incident whose previous claim has terminally settled chains to the
  next episode token, so genuinely new incidents still admit while the
  unique claim still decides any race.

Answering and resuming remain the HITL / ApprovalStore doors (#55 owns
HITL→store resolve linkage); recovery of an answered Run is the owned
``self_repair`` recovery category over the canonical Graph seams.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.self_repair_incident import (
    CHAIN_LIMIT_ERROR,
    INCIDENT_RESOURCE_KEY,
    MAX_EPISODE_CHAIN,
    SELF_REPAIR_ADMISSION_SOURCE,
    chain_incident_claim,
    episode_effect_key,
    incident_claim,
    incident_episode_token,
    incident_run_effect_key,
)
from maistro.capabilities.slots.infra import ActionResult, InfraAction
from maistro.graph.definitions import Graph, Node
from maistro.graph.durable_runs import (
    DurableRunRecord,
    DurableRunStore,
    RunStatus,
    durable_graph_launch_provenance,
    run_durable_graph,
)
from maistro.graph.nodes.base import BaseNode
from maistro.graph.nodes.infra_approval_action import (
    BINDING_REFERENCE_KEY,
    InfraApprovalActionIn,
    InfraApprovalActionNode,
    _require_approval_policy,
    binding_reference_of,
    execute_approved_infra_action,
    requires_durable_approval,
)
from maistro.runs.model import TERMINAL_RUN_STATUSES
from maistro.runs.store import DuplicateOccurrence, RunIntegrityError, RunStore

#: Stable node id for the single-effect self-repair approval Graph.
SELF_REPAIR_APPROVAL_NODE_ID = "self_repair_action"

#: Backwards-compatible aliases: the node implementation moved to the
#: registered kind so recovery can reconstruct it from durable facts.
_InfraApprovalNode = InfraApprovalActionNode
_InfraActionIn = InfraApprovalActionIn


def _approval_graph(
    *,
    workspace_id: str,
    project_id: str,
    action: str,
    params: Mapping[str, Any],
    effect_key: str,
    binding: Binding,
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
        metadata={
            "entry_node": SELF_REPAIR_APPROVAL_NODE_ID,
            "admission_source": SELF_REPAIR_ADMISSION_SOURCE,
            # Non-secret Binding reference: recovery re-resolves it live
            # through the Container-owned Binding authority instead of
            # trusting a serialized object (revocation fails closed).
            BINDING_REFERENCE_KEY: binding_reference_of(binding),
        },
    )


def _ensure_claim_matches_effect(
    *, claim: dict[str, str], expected_effect_key: str, existing: Any
) -> None:
    """Refuse a live claim held for a different effect.

    The claim namespace scopes one incident *generation*, so a different
    ``effect_key`` under the same claim would alias unrelated work — never
    reconcile, fail closed instead. ``expected_effect_key`` is the candidate
    generation's key: episode 0's base key, or the generation moved with the
    chained token (``episode_effect_key``).
    """
    claimed_key = str(existing.provenance.get("effect_key") or "")
    if expected_effect_key and claimed_key and expected_effect_key != claimed_key:
        raise RunIntegrityError(
            f"incident claim {claim} is held by Run {existing.run_id!r} "
            "for a different effect; refusing to alias unrelated work"
        )


async def _resolve_incident_claim(
    *,
    run_store: RunStore,
    graph_for: Callable[[str], Graph],
    inputs_for: Callable[[str], dict[str, Any]],
    base_provenance: dict[str, Any],
    base_effect_key: str,
    base_token: str,
    claim: dict[str, str],
    actor: str,
) -> tuple[str, bool, str]:
    """Atomically claim the incident episode; reuse a live claim's Run.

    Returns ``(run_id, created, effect_key)``. ``created=False`` means the
    canonical Run already carries this episode's live claim — the caller must
    reconcile to it (reuse the parked durable wait if it exists, or re-enter
    ``run_durable_graph`` under the same Run id when the crash between
    ``create_run`` and the first checkpoint left only the canonical Run).

    The effect key moves with the generation (``episode_effect_key``): one
    logical effect is one Run forever (migration 034), and a settled
    incident's next admission is a new logical operation. The claim's token
    already chains; the key follows it so a post-settlement episode does not
    collide with the settled Run's row on ``ix_canonical_runs_effect``.

    A terminal claim is superseded by chaining the episode token, so a
    genuinely new incident after settlement admits while the claim stays
    race-safe. ``DuplicateOccurrence`` losers re-probe instead of inserting a
    second Run; check-then-insert alone is never the authority.
    """
    current_claim = dict(claim)
    for _ in range(MAX_EPISODE_CHAIN):
        token = str(current_claim.get("schedule_fire_id") or "")
        effect_key = episode_effect_key(base_effect_key, token, base_token=base_token)
        existing = await run_store.find_occurrence_run(current_claim)
        if existing is None:
            try:
                admitted = await run_store.create_run(
                    graph_for(effect_key),
                    initial_status=RunStatus.QUEUED,
                    actor_principal_id=actor,
                    provenance={
                        **base_provenance,
                        "effect_key": effect_key,
                        **durable_graph_launch_provenance(inputs=inputs_for(effect_key)),
                        **current_claim,
                    },
                )
                return admitted.run_id, True, effect_key
            except DuplicateOccurrence:
                # The claim's winner committed between the probe and the
                # insert; resolve it and reconcile instead of retrying blind.
                existing = await run_store.find_occurrence_run(current_claim)
                if existing is None:
                    raise RunIntegrityError(
                        "self-repair incident claim was lost after DuplicateOccurrence"
                    ) from None
        _ensure_claim_matches_effect(
            claim=current_claim,
            expected_effect_key=effect_key,
            existing=existing,
        )
        if existing.status not in TERMINAL_RUN_STATUSES:
            claimed_key = str(existing.provenance.get("effect_key") or "")
            return existing.run_id, False, claimed_key or effect_key
        current_claim = chain_incident_claim(current_claim, existing.run_id)
    raise RuntimeError(CHAIN_LIMIT_ERROR)


async def _claim_incident_run(
    *,
    store: DurableRunStore,
    run_store: RunStore,
    graph_for: Callable[[str], Graph],
    inputs_for: Callable[[str], dict[str, Any]],
    base_provenance: dict[str, Any],
    base_effect_key: str,
    base_token: str,
    claim: dict[str, str],
    actor: str,
) -> tuple[str | None, DurableRunRecord | None, str]:
    """Claim the incident episode, or reconcile to the live claim's wait.

    Returns ``(run_id, existing_wait, effect_key)``. A non-None
    ``existing_wait`` is the durable record the episode's live claim already
    parked: the caller returns it untouched. ``existing_wait`` is None both
    for a freshly claimed Run and for the crash between ``create_run`` and
    the first checkpoint — the caller launches (or re-enters)
    ``run_durable_graph`` under ``run_id`` either way; the admitted launch
    snapshot in Run provenance rebuilds checkpoint 1, and ``effect_key`` is
    the resolved generation's key the launched graph and inputs must carry.
    """
    run_id, created, effect_key = await _resolve_incident_claim(
        run_store=run_store,
        graph_for=graph_for,
        inputs_for=inputs_for,
        base_provenance=base_provenance,
        base_effect_key=base_effect_key,
        base_token=base_token,
        claim=claim,
        actor=actor,
    )
    if created:
        return run_id, None, effect_key
    return run_id, await store.get(run_id), effect_key


def _admission_node(
    *,
    effect_context: CapabilityEffectContext,
    binding: Binding,
    resolve_provider: Callable[[Binding], Awaitable[InfraAction]],
) -> InfraApprovalActionNode:
    """The admission-constructed approval node: same class recovery composes.

    The admitting process injects the narrowed Invocation service, the
    resolved Binding and the Container-resolved provider lookup — exactly the
    collaborators it holds. Recovery rebuilds the same kind from durable
    facts plus live authorities; the execution path is shared.
    """

    async def execute_approved(
        provider: InfraAction, approved_action: str, approved_params: dict[str, Any]
    ) -> ActionResult:
        # The governed seam already verified DurableApproval. HostHealthAction
        # is a pure executor here (#2405): pass approved=True so it never
        # re-enters an in-process inbox wait.
        return await execute_approved_infra_action(provider, approved_action, approved_params)

    return InfraApprovalActionNode(
        service=effect_context.with_policy_evaluator(_require_approval_policy).invocations,
        binding=binding,
        resolve_provider=resolve_provider,
        execute_approved=execute_approved,
    )


def _require_admission_scope(workspace_id: str, project_id: str) -> None:
    """The canonical authorization scope a durable approval wait needs."""
    if not workspace_id.strip() or not project_id.strip():
        raise ValueError("workspace_id and project_id are required for durable HITL scope")


async def _claim_or_reuse_wait(
    *,
    store: DurableRunStore,
    run_store: Any,
    graph_for: Callable[[str], Graph],
    inputs_for: Callable[[str], dict[str, Any]],
    base_provenance: dict[str, Any],
    base_effect_key: str,
    base_token: str,
    claim: dict[str, str],
    actor: str,
) -> tuple[str | None, DurableRunRecord | None, str]:
    """Claim the incident episode when a canonical Run store exists.

    Returns ``(run_id, existing_wait, effect_key)``; the first two ``None``
    when no ``run_store`` is configured (single-process admission claims
    nothing) and the key is the caller's episode-0 base. A non-None
    ``existing_wait`` is the durable record the episode's live claim already
    parked — the caller returns it untouched instead of re-executing it.
    """
    if run_store is None:
        return None, None, base_effect_key
    return await _claim_incident_run(
        store=store,
        run_store=run_store,
        graph_for=graph_for,
        inputs_for=inputs_for,
        base_provenance=base_provenance,
        base_effect_key=base_effect_key,
        base_token=base_token,
        claim=claim,
        actor=actor,
    )


async def _launch_admitted_wait(
    *,
    store: DurableRunStore,
    run_store: Any,
    resolver: Callable[[str, Graph], BaseNode[Any, Any]],
    graph_for: Callable[[str], Graph],
    inputs_for: Callable[[str], dict[str, Any]],
    base_provenance: dict[str, Any],
    actor: str,
    run_id: str | None,
    resolved_effect_key: str,
) -> DurableRunRecord:
    """Launch (or re-enter) the claimed Run's durable Graph.

    The generation is resolved (episode 0, or the token chained past terminal
    settlements): the launched graph and inputs carry the generation's effect
    key, matching the launch snapshot the claim stamped so a crash-window
    re-entry validates.

    Two replicas can re-enter the same claimed Run while the winner of the
    claim is still publishing its first checkpoint — the crash window is a
    race, not just a restart. The continuation store's uniqueness is the
    fence: the loser's ``create`` refuses, and the loser converges to the
    winner's parked wait instead of crashing admission or minting anything
    (#2405 two-replica evidence). At most one physical effect dispatches,
    because the refusal precedes any node execution.
    """
    inputs = inputs_for(resolved_effect_key)
    graph = graph_for(resolved_effect_key)
    provenance = {**base_provenance, "effect_key": resolved_effect_key}
    if run_store is not None:
        provenance = {**provenance, **durable_graph_launch_provenance(inputs=inputs)}
    try:
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
    except ValueError as exc:
        if not str(exc).startswith("run_id collision:"):
            raise
        converged = await store.get(run_id) if run_id is not None else None
        if converged is None:
            # No wait appeared: the claim's winner died before publishing.
            # Surface the truth — the next hydration cycle reconciles the
            # stranded canonical Run — rather than guessing at a replacer.
            raise
        return converged
    if record.run.status is not RunStatus.PAUSED:
        raise RuntimeError(
            f"self-repair approval admission expected PAUSED, got {record.run.status.value}"
        )
    return record


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
    resource: str | None = None,
) -> DurableRunRecord:
    """Park one self-repair action on a durable waiting-human NodeRun.

    ``workspace_id`` / ``project_id`` are the canonical authorization scope for
    the admitted Run (HITL discovery and settlement). They must be a real
    Workspace + Project the operator can authorize — not the synthetic
    effect-Binding ids used only for ``infra_action`` resolution.

    When ``run_store`` is set, a canonical Run is claimed under the incident's
    stable occurrence claim before the durable Graph starts: concurrent or
    restarted admissions of the same unresolved incident converge on one Run
    instead of minting duplicate approvals. ``resource`` names the affected
    infrastructure resource and is stamped onto Run provenance so restart
    hydration can reconcile pending waits without process-local state.

    Raises ``ValueError`` when the action does not require approval (caller
    should auto-run those). Returns the durable record; status is ``PAUSED``.
    """
    if not requires_durable_approval(action, params):
        raise ValueError(f"action {action!r} does not require durable approval")
    _require_admission_scope(workspace_id, project_id)

    if effect_context.approval_store is None:
        raise RuntimeError("CapabilityEffectContext has no ApprovalStore for durable HITL")

    node = _admission_node(
        effect_context=effect_context,
        binding=binding,
        resolve_provider=resolve_provider,
    )

    def resolver(node_id: str, _graph: Graph) -> BaseNode[Any, Any]:
        if node_id != SELF_REPAIR_APPROVAL_NODE_ID:
            raise KeyError(node_id)
        return node

    def inputs_for(resolved_effect_key: str) -> dict[str, Any]:
        return {
            "action": action,
            "params": dict(params),
            "effect_key": resolved_effect_key,
            # The durable Binding reference the reconstructible kind re-resolves
            # on resume (non-secret; revocation fails closed at the live store).
            "binding_reference": binding_reference_of(binding),
        }

    def graph_for(resolved_effect_key: str) -> Graph:
        return _approval_graph(
            workspace_id=workspace_id,
            project_id=project_id,
            action=action,
            params=params,
            effect_key=resolved_effect_key,
            binding=binding,
        )

    base_provenance: dict[str, Any] = {
        "admission_source": SELF_REPAIR_ADMISSION_SOURCE,
        "executor": "durable_graph",
        "action": action,
    }
    base_resource = resource or effect_key
    if resource:
        base_provenance[INCIDENT_RESOURCE_KEY] = resource
    actor = actor_principal_id or "self-repair"
    # The Run-store effect identity is scope-digested (see
    # ``incident_run_effect_key``): migration 034's unique index on
    # ``provenance.effect_key`` is global across Workspaces, and the provider
    # key is deliberately workspace-independent.
    base_effect_key = incident_run_effect_key(workspace_id, project_id, effect_key)

    run_id, existing_wait, resolved_effect_key = await _claim_or_reuse_wait(
        store=store,
        run_store=run_store,
        graph_for=graph_for,
        inputs_for=inputs_for,
        base_provenance=base_provenance,
        base_effect_key=base_effect_key,
        base_token=incident_episode_token(base_resource, action, params),
        claim=incident_claim(
            workspace_id=workspace_id,
            project_id=project_id,
            resource=base_resource,
            action=action,
            params=params,
        ),
        actor=actor,
    )
    if existing_wait is not None:
        # Another admission (this process before a restart, or another
        # replica) already holds the episode's live claim and its durable
        # wait exists — PAUSED awaiting a human, or QUEUED with an answer
        # being recovered. A second admission must not re-execute it or
        # mint a second DurableApproval.
        return existing_wait

    return await _launch_admitted_wait(
        store=store,
        run_store=run_store,
        resolver=resolver,
        graph_for=graph_for,
        inputs_for=inputs_for,
        base_provenance=base_provenance,
        actor=actor,
        run_id=run_id,
        resolved_effect_key=resolved_effect_key,
    )


__all__ = [
    "SELF_REPAIR_APPROVAL_NODE_ID",
    "_require_approval_policy",
    "admit_self_repair_approval",
]
