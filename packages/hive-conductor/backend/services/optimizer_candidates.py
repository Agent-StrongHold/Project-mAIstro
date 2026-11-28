"""Optimizer-proposal application through the canonical candidate/promotion contract (#861).

An accepted optimizer proposal used to mutate the live DAG record in place
(`services/optimizer._apply_topology_mutation` wrote LLM-authored verdict
fields straight into ``stores.dags``), and `run_optimizer(apply_auto=True)`
reported ``auto_applied: N`` — with audit entries — while mutating nothing at
all. Both are replaced here by one rule:

**An optimizer-proposed change is a candidate version in the canonical
GraphTemplate authority, applied only through the audited promotion contract.**

This module is deliberately a *consumer*, not a lifecycle owner. The candidate
semantics (``lifecycle="candidate"``, refusal to serve a non-active version by
default), the promotion gate (``PromotionApproval`` naming a real approver and
reason) and the attempt→promoting→committed→active audit ordering all belong to
``maistro.graph.templates`` (ADR-082926-65bf, SPEC-081226-bb3a AC-11). What
this module adds is the projection the optimizer needs:

1. ``snapshot_hash`` — the exact-content binding. A proposal records the hash
   of the DAG snapshot it was computed against; application refuses (outcome
   ``stale``) anything whose source hash no longer matches, so a proposal can
   never land on a different DAG state than the one it was authored against.
2. ``commit_candidate`` — projects the mutated snapshot through the one
   reviewed projection (``template_adapter.snapshot_to_template``), registers it
   as a ``candidate`` version (the store refuses redefinition, so historical
   versions stay immutable), promotes it through ``promote_audited`` with the
   accepting human as the approver, and only then syncs the editable
   descriptor surface to the promoted content.
3. Truthful outcomes. Every application returns exactly one of:
   ``applied`` (candidate registered + promoted + descriptor synced, with the
   resulting active version), ``no_op`` (the candidate content is identical to
   the source — nothing changed, nothing is claimed), ``stale`` (source
   binding no longer holds), or ``failed`` (a step raised; the detail names
   it). ``escalated`` is recorded by the caller for execution-tier requests,
   which are requests only and are never applied here.

#2501 adds the *auto*-promotion gate in front of ``commit_candidate``:
   ``promote_evaluated_candidate`` runs the optimizer-authored candidate
   through the canonical promotion contract (``maistro.governance.promotion``,
   ADR-100126-a9c4 — the #116 authority) before any store transition, so an
   auto-promotion stands on completed, cited evaluation evidence, a real
   approver outside the authoring path, and a base that is still current. The
   human accept path keeps its own authority: the accepting user is the
   approver of record (#861) and no machine evidence is required of them.

Promotions for one DAG are serialized in-process: compare-and-swap only holds
   if the compare and the swap are not interleaved by another promotion of the
   same subject (two concurrent passes over one source version must yield one
   winner and one explicit loser, never two promotions of one version).

The template store resolves to the engine container's ``template_store`` when
the canonical bridge is wired, and to a process-local
``InMemoryGraphTemplateStore`` otherwise — the same store family either way, so
the promotion semantics are identical in both modes rather than a weaker local
copy of them.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from maistro.governance.promotion import (
    CandidateChange,
    EvaluationEvidence,
    IncompleteEvidence,
    PromotionApproval,
    PromotionContract,
    PromotionLedger,
    PromotionRecord,
    PromotionRefused,
    PromotionScope,
    ProtectedConstituentEdit,
    StaleCandidate,
    UnchangedCandidate,
)

logger = logging.getLogger(__name__)

# Application outcomes. Distinct on purpose: a caller reading a proposal's
# apply record must be able to tell "nothing was supposed to happen" from
# "something was supposed to happen and did not" (…#861).
APPLIED = "applied"
NO_OP = "no_op"
STALE = "stale"
FAILED = "failed"
ESCALATED = "escalated"
MANUAL = "manual"  # decision recorded; the change is authored by a human in the editor
UNSUPPORTED = "unsupported"  # the proposal names no concrete mutation to commit
#: A concrete candidate is staged and waits for its independent evaluation
#: before anything may be promoted (#2501). Not an application.
STAGED = "staged"
#: The proposal's independent evaluation did not complete (skipped, unavailable,
#: failed, or without Run lineage). Nothing was promoted (#2501).
UNEVALUATED = "unevaluated"
#: The evaluation completed and the candidate did not strictly improve on the
#: incumbent; the promotion policy refused it. Nothing was promoted (#2501).
NOT_IMPROVING = "not_improving"

#: The approval policy an auto-promotion is recorded under (SPEC-100126-a9c4
#: R4: a record must say what policy allowed it): the candidate completed
#: independent evaluation with cited Run lineage, judged by the same evaluator
#: version as the incumbent, and scored strictly higher.
AUTO_PROMOTION_POLICY_ID = "optimizer-auto-promotion/strict-improvement"

#: The provenance path that authors an optimizer candidate. The contract's
#: self-approval fence reads it: this path can never be the authority that
#: approves its own candidate.
CANDIDATE_AUTHOR = "optimizer"

#: Proposal kinds whose effect changes the authorization/execution posture of a
#: node. Optimizer proposals of these kinds are REQUESTS: recording one never
#: mutates the DAG and never writes an approval field — the delegated/elevated
#: authority owns the decision (#845/#60). The historical behavior stamped
#: ``tier_approved_by: "admin"`` at apply time, which self-certified an
#: approval nobody had given.
ESCALATION_KINDS = frozenset({"upgrade_execution_tier"})


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    """Content hash of a DAG snapshot — the exact-source binding for proposals.

    Canonical-JSON sha256, the same discipline ``maistro.graph.definitions``
    uses for template content hashes: a proposal binds to *content*, not to a
    mutable record identity, so "the DAG changed after this proposal was
    created" is a comparison the store can actually make.
    """
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


_fallback_store: Any = None
_override_store: Any = None


def set_template_store(store: Any) -> None:
    """Wire the canonical template store explicitly (tests, engine bridge)."""
    global _override_store
    _override_store = store


def _engine_template_store() -> Any | None:
    """The wired Container template store, or None when the bridge is absent."""
    try:
        from services.engine import get_engine

        container = getattr(getattr(get_engine(), "_agent_port", None), "container", None)
        return getattr(container, "template_store", None)
    except Exception:  # pragma: no cover - engine unavailable in isolation
        return None


def template_store() -> Any:
    """The canonical GraphTemplateStore proposals are promoted through.

    Resolution order: an explicitly wired store, the engine Container's store,
    then a process-local ``InMemoryGraphTemplateStore``. The fallback is the
    same store family the durable twins implement, not a weaker local
    lifecycle: candidate/promoted semantics live in
    ``maistro.graph.templates`` either way.
    """
    global _fallback_store
    if _override_store is not None:
        return _override_store
    wired = _engine_template_store()
    if wired is not None:
        return wired
    if _fallback_store is None:
        from maistro.graph.templates import InMemoryGraphTemplateStore

        _fallback_store = InMemoryGraphTemplateStore()
    return _fallback_store


async def active_template_version(dag_id: str) -> int | None:
    """The DAG's current active template version, or None when unregistered.

    Proposals record this beside the content hash so a proposal binds the
    *exact* Graph id/version it was computed against, not just "whatever the
    DAG looks like right now".
    """
    store = template_store()
    try:
        versions = await store.versions(dag_id)
    except Exception:  # pragma: no cover - store backends do not raise here
        return None
    if not versions:
        return None
    # versions() lists every registered version; the active one is the latest
    # promoted. Walk backwards so a later candidate (never served by default)
    # does not masquerade as the active version.
    for version in sorted(versions, reverse=True):
        lifecycle = await store.lifecycle_of(dag_id, version)
        if lifecycle == "active":
            return version
    return None


class _CanonicalPromotionAudit:
    """Adapter: the canonical promotion audit contract over Hive's audit log.

    ``promote_audited`` asks for attempt/committed entries through
    ``TemplatePromotionAudit``; this writes them as ordinary audit_log entries
    so the promotion trail lands where every other Hive decision already is.
    """

    def __init__(self, *, actor: str, proposal_id: str, dag_id: str) -> None:
        self._actor = actor
        self._proposal_id = proposal_id
        self._dag_id = dag_id

    async def record(self, event: str, template_id: str, version: int) -> None:
        from routes.audit import log_audit

        log_audit(
            action=event,
            actor=self._actor,
            target=template_id,
            detail={
                "proposal_id": self._proposal_id,
                "dag_id": self._dag_id,
                "template_version": version,
            },
        )


def _workspace_id_for(
    dag_id: str, snapshot: dict[str, Any], *, authorized_workspace_id: str = ""
) -> str:
    """The Workspace the candidate template is registered under.

    Resolution order: the Workspace the triggering request was authorized
    against (the scope that owns the DAG — #861 review: registration lands in
    the authorizing tenant, not the configured default), then the configured
    default, then the snapshot's own value, then a stable synthetic id. The
    configured default and the snapshot fallback match what the scheduler
    uses when priming a descriptor into the template store, so both writers
    land in the same Workspace and the store's workspace check never sees two
    owners for one template id.
    """
    authorized = str(authorized_workspace_id or "").strip()
    if authorized:
        return authorized
    configured = ""
    try:
        from config import get_settings

        configured = str(getattr(get_settings(), "hive_default_workspace_id", "") or "")
    except Exception:  # pragma: no cover - settings always load in practice
        configured = ""
    return configured or str(snapshot.get("workspace_id", "") or "") or f"hive:dag:{dag_id}"


def _register_candidate(
    candidate_snapshot: dict[str, Any],
    *,
    dag_id: str,
    version: int,
    workspace_id: str = "",
) -> tuple[Any, str, Any]:
    """Project the candidate snapshot to a canonical GraphTemplate version.

    Returns (store, content_hash, template). ``snapshot_to_template`` is the
    single reviewed projection — the optimizer hand-rolls none of it — and the
    lifecycle is asked-for candidacy, not the model's default.
    """
    from maistro.graph.template_adapter import snapshot_to_template

    store = template_store()
    # Candidacy must be explicit: ``snapshot_to_template`` returns a
    # default-active template, and putting that up as-is would register an
    # active version with no promotion behind it.
    template = snapshot_to_template(
        copy.deepcopy(candidate_snapshot),
        workspace_id=_workspace_id_for(
            dag_id, candidate_snapshot, authorized_workspace_id=workspace_id
        ),
        template_id=dag_id,
        version=version,
    ).model_copy(update={"lifecycle": "candidate"})
    return store, template.content_hash, template


async def _compensate_moved_base(
    store: Any,
    dag_id: str,
    *,
    version: int,
    prior_active: int | None,
    source_hash: str,
) -> tuple[bool, str]:
    """Compare-and-swap #2 for ``commit_candidate``.

    The descriptor is only synced when it still holds the content the
    candidate was computed against. If it moved during the promotion awaits,
    the promotion is compensated — the just-activated version is demoted and
    the prior active version restored — and the conflict is reported; the
    concurrent edit is never overwritten.

    Returns ``(moved, detail)``. ``moved`` is False when the source binding
    still holds and the caller may sync the descriptor; True when it did not,
    with ``detail`` naming either the successful compensation or its failure.
    """
    import stores

    if dag_id in stores.dags and snapshot_hash(stores.dags[dag_id]) == source_hash:
        return False, ""
    try:
        await store.set_lifecycle(dag_id, version, "candidate")
        if prior_active is not None:
            await store.set_lifecycle(dag_id, prior_active, "active")
        detail = (
            f"DAG changed during apply; candidate version {version} rolled back, "
            "descriptor left untouched"
        )
    except Exception as exc:
        detail = (
            f"DAG changed during apply and rollback of version {version} failed: "
            f"{type(exc).__name__}: {exc}; descriptor left untouched"
        )
    return True, detail


# Per-subject promotion serialization (#2501). One lock per DAG id, held only
# while some promotion is acquiring, holding, or waiting on it.
_promotion_locks: dict[str, asyncio.Lock] = {}
_promotion_holders: dict[str, int] = {}


@contextlib.asynccontextmanager
async def _serial_promotion(dag_id: str) -> AsyncIterator[None]:
    """Make compare-and-swap atomic against other promotions of the same DAG.

    Held from the CAS-1 read through the descriptor sync, so two passes that
    approved the same source version cannot both pass CAS-1 and mint or
    promote one version twice. Refcounted: the entry lives only while a
    promotion holds or awaits it, so no lock outlives the loop that made it.
    """
    lock = _promotion_locks.setdefault(dag_id, asyncio.Lock())
    _promotion_holders[dag_id] = _promotion_holders.get(dag_id, 0) + 1
    try:
        async with lock:
            yield
    finally:
        remaining = _promotion_holders[dag_id] - 1
        _promotion_holders[dag_id] = remaining
        if remaining <= 0:
            _promotion_locks.pop(dag_id, None)
            _promotion_holders.pop(dag_id, None)


@contextlib.asynccontextmanager
async def decision_serialization(dag_id: str) -> AsyncIterator[None]:
    """Serialize a human decision against in-flight promotions (#2501 review).

    Same per-DAG lock as ``commit_candidate``: a reject endpoint and an
    auto-promotion cannot interleave, so a rejection either lands before the
    commit's decision fence reads it (the promotion is refused) or after the
    commit returned — it can never slip between the fence and the store
    transition.
    """
    async with _serial_promotion(dag_id):
        yield


async def commit_candidate(
    dag_id: str,
    candidate_snapshot: dict[str, Any],
    *,
    actor: str,
    proposal_id: str,
    source_hash: str,
    reason: str = "",
    workspace_id: str = "",
    approval: PromotionApproval | None = None,
    version: int | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply one optimizer-proposed change as candidate + audited promotion.

    Returns the apply record: ``{"outcome", "candidate_hash",
    "resulting_version", "detail"}``. ``applied`` is reported only after the
    promotion has committed and the editable descriptor surface has been
    synced to the promoted content — never before, and never for a mutation
    that changed nothing. ``workspace_id`` is the Workspace the triggering
    request was authorized against; the candidate version registers there,
    not in the configured default (#861 review).

    ``approval`` (the policy decision of record), ``version`` (the version an
    approval already minted — the commit refuses if the registration moved
    past it) and ``evidence`` (the lineage the approval stood on) come from
    the auto-promotion gate (#2501); the human accept path supplies none and
    the accepting user is the approver, as before (#861).
    """
    async with _serial_promotion(dag_id):
        return await _commit_candidate(
            dag_id,
            candidate_snapshot,
            actor=actor,
            proposal_id=proposal_id,
            source_hash=source_hash,
            reason=reason,
            workspace_id=workspace_id,
            approval=approval,
            version=version,
            evidence=evidence,
        )


async def _commit_candidate(
    dag_id: str,
    candidate_snapshot: dict[str, Any],
    *,
    actor: str,
    proposal_id: str,
    source_hash: str,
    reason: str,
    workspace_id: str,
    approval: PromotionApproval | None,
    version: int | None,
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """``commit_candidate`` under the per-DAG promotion lock: the refusals."""
    import stores

    candidate_hash = snapshot_hash(candidate_snapshot)
    record: dict[str, Any] = {
        "proposal_id": proposal_id,
        "dag_id": dag_id,
        "candidate_hash": candidate_hash,
        "resulting_version": None,
        "outcome": FAILED,
        "detail": "",
    }
    if approval is not None:
        record["policy_id"] = approval.policy_id
    if evidence:
        record["evidence"] = dict(evidence)

    # A human rejection recorded on the stored row outranks the pass (#2501
    # review): checked here, under the promotion lock, so a rejection that
    # lands while the commit is in flight either precedes this fence or follows
    # the commit — it can never interleave with it. A stale refusal would be
    # the wrong answer here: the base did not move; the proposal was withdrawn.
    # Read through services.optimizer's storage seam (#2469), late-bound like
    # optimizer_scope's lookups: the projection is a retiring surface whose
    # ledger entry may not gain a new importer, and the seam returns the live
    # row, so the fence sees the decision as of this instant under the lock.
    from services.optimizer import DECISION_REJECTED, stored_proposal

    stored = stored_proposal(proposal_id)
    if stored is not None and stored.get("decision") == DECISION_REJECTED:
        record["outcome"] = UNEVALUATED
        record["detail"] = (
            f"proposal was rejected by {stored.get('decided_by') or 'a human'} "
            "while its evaluation was pending; honoring the recorded decision"
        )
        _audit_apply(actor, record, severity="warning")
        return record

    if candidate_hash == source_hash:
        # The mutation produced byte-identical content. Reporting this as
        # applied is precisely the fake success #861 removes: nothing changed,
        # so nothing is claimed.
        record["outcome"] = NO_OP
        record["detail"] = "candidate content is identical to the source snapshot"
        _audit_apply(actor, record, severity="info")
        return record

    store = template_store()
    try:
        existing = await store.versions(dag_id)
    except Exception as exc:
        record["detail"] = f"template store unreadable: {type(exc).__name__}: {exc}"
        _audit_apply(actor, record, severity="warning")
        return record
    next_version = max(existing, default=0) + 1
    prior_active = await active_template_version(dag_id)

    # An approval that already minted a version binds the commit to it: if the
    # registration moved past that number while the candidate was being
    # approved, the approval is no longer about the next version.
    if version is not None and version != next_version:
        return _stale(
            actor,
            record,
            prior_active,
            f"another promotion registered version {next_version - 1} while proposal "
            f"{proposal_id} was being approved; that approval minted version {version}, "
            "which is no longer the next version; refusing",
        )

    # Compare-and-swap #1: the source binding was checked synchronously by the
    # caller (_bound_source), but awaits since then may have let a user edit
    # or another promotion land. Refuse before touching the store rather than
    # promoting onto a moved base.
    if dag_id not in stores.dags or snapshot_hash(stores.dags[dag_id]) != source_hash:
        return _stale(
            actor,
            record,
            prior_active,
            "DAG changed while the proposal was being applied; refusing to re-target",
        )

    return await _register_and_promote(
        store,
        dag_id,
        candidate_snapshot,
        record,
        actor=actor,
        proposal_id=proposal_id,
        source_hash=source_hash,
        reason=reason,
        workspace_id=workspace_id,
        approval=approval,
        version=version if version is not None else next_version,
        prior_active=prior_active,
    )


def _stale(
    actor: str, record: dict[str, Any], competing_version: int | None, detail: str
) -> dict[str, Any]:
    """Record a compare-and-swap refusal, naming the version that won the base.

    The competing version is the immutable CAS evidence a losing concurrent
    pass reads (#2501): it says which promotion moved the base underneath it.
    """
    record["outcome"] = STALE
    record["detail"] = detail
    record["competing_version"] = competing_version
    _audit_apply(actor, record, severity="warning")
    return record


async def _register_and_promote(
    store: Any,
    dag_id: str,
    candidate_snapshot: dict[str, Any],
    record: dict[str, Any],
    *,
    actor: str,
    proposal_id: str,
    source_hash: str,
    reason: str,
    workspace_id: str,
    approval: PromotionApproval | None,
    version: int,
    prior_active: int | None,
) -> dict[str, Any]:
    """``commit_candidate`` under the per-DAG promotion lock: the transition.

    Register the candidate, promote it through the audited contract, verify
    the base once more (CAS-2), and only then sync the editable descriptor.
    """
    import stores

    # Late-bound like the historical import: tests and the engine bridge
    # substitute the canonical module's transition in place.
    from maistro.graph.templates import promote_audited

    try:
        _, _, template = _register_candidate(
            candidate_snapshot, dag_id=dag_id, version=version, workspace_id=workspace_id
        )
    except Exception as exc:
        record["detail"] = f"candidate projection refused: {type(exc).__name__}: {exc}"
        _audit_apply(actor, record, severity="warning")
        return record
    record["candidate_hash"] = template.content_hash

    decided = approval or PromotionApproval(
        approver=actor,
        reason=reason.strip() or f"optimizer proposal {proposal_id} accepted by {actor}",
    )
    audit = _CanonicalPromotionAudit(actor=actor, proposal_id=proposal_id, dag_id=dag_id)
    try:
        await store.put(template)
    except Exception as exc:
        record["detail"] = f"candidate registration failed: {type(exc).__name__}: {exc}"
        _audit_apply(actor, record, severity="warning")
        return record

    try:
        await promote_audited(store, dag_id, version, audit=audit, approval=decided)
    except BaseException as exc:
        # promote_audited compensates its own lifecycle transition; the active
        # version is unchanged and the failure is reported, not swallowed.
        record["detail"] = f"promotion failed: {type(exc).__name__}: {exc}"
        _audit_apply(actor, record, severity="warning")
        return record

    # Compare-and-swap #2: the descriptor may only be synced when it still
    # holds the content the candidate was computed against. If it moved
    # during the promotion awaits, the promotion is compensated and the
    # conflict reported; the concurrent edit is never overwritten.
    moved, detail = await _compensate_moved_base(
        store, dag_id, version=version, prior_active=prior_active, source_hash=source_hash
    )
    if moved:
        return _stale(actor, record, prior_active, detail)

    # Promotion committed and the source still matches. The descriptor the UI
    # reads is a projection of the now-active canonical version — synced
    # after, never before, so the editable surface never runs ahead of the
    # authority.
    try:
        stores.dags[dag_id] = copy.deepcopy(candidate_snapshot)
    except Exception as exc:
        record["detail"] = (
            f"template version {version} is active but the descriptor sync failed: "
            f"{type(exc).__name__}: {exc}"
        )
        _audit_apply(actor, record, severity="warning")
        return record

    record["outcome"] = APPLIED
    record["resulting_version"] = version
    record["detail"] = f"candidate promoted to active version {version}"
    _audit_apply(actor, record, severity="info")
    return record


# --- The auto-promotion gate (#2501) ---------------------------------------
#
# ``commit_candidate`` is the template family's sanctioned transition. The
# *auto* path must earn the right to call it: ``promote_evaluated_candidate``
# runs the candidate through the canonical promotion contract first.

#: The evaluator the validation gate uses, as ``EvaluationEvidence`` names it.
EVALUATOR_NAME = "benchmark_eval"

#: Protected constituents per scope for the optimizer's contract. Explicit
#: for every scope (the constructor refuses an unclassified family). Empty for
#: `template` on purpose, and that is a written decision, not an omission: the
#: evaluator that judges a DAG template is not part of the template, and the
#: one authorization-changing kind the optimizer sees (`upgrade_execution_tier`)
#: is recorded as a request for the delegated authority before it can ever
#: become a candidate, so no candidate reaches this contract carrying one.
PROTECTED_REFS: dict[PromotionScope, frozenset[str]] = {
    scope: frozenset() for scope in PromotionScope
}

_contract: PromotionContract | None = None


def set_promotion_contract(contract: PromotionContract | None) -> None:
    """Wire the canonical promotion contract explicitly (tests, engine bridge)."""
    global _contract
    _contract = contract


def promotion_contract() -> PromotionContract:
    """The contract auto-promotions are gated through (ADR-100126-a9c4).

    Process-local until a store adopts the ledger (the spec records template
    ledger adoption as follow-up); every promotion it records is also written
    to the audit log, so the trail survives the process.
    """
    global _contract
    if _contract is None:
        _contract = PromotionContract(PROTECTED_REFS, PromotionLedger())
    return _contract


def _evidence_of(validation: dict[str, Any]) -> tuple[tuple[str, ...], str]:
    """The Run ids and evaluator version a completed evaluation cites."""
    baseline = validation.get("baseline") or {}
    candidate = validation.get("candidate") or {}
    cited = (
        candidate.get("evaluation_run_id"),
        baseline.get("evaluation_run_id"),
        candidate.get("run_id"),
        baseline.get("run_id"),
    )
    run_ids = tuple(dict.fromkeys(str(value) for value in cited if value))
    return run_ids, str(candidate.get("evaluator_version") or "")


async def _base_version(contract: PromotionContract, dag_id: str, descriptor_hash: str) -> int:
    """The version number the candidate is promoted on top of.

    The registration head, unless the descriptor no longer holds the content
    that version was recorded with — a human edited the editable surface past
    the promoted content. Then the candidate's prior is unversioned content
    (0), not a version whose recorded history it would contradict; the number
    minted is still one past the head, because a head the ledger recorded is
    the ledger's own latest.
    """
    store = template_store()
    head = max(await store.versions(dag_id), default=0)
    recorded = contract.ledger.trace(PromotionScope.TEMPLATE, dag_id, head)
    if head and recorded is not None and recorded.record.content_hash != descriptor_hash:
        return 0
    return head


async def promote_evaluated_candidate(
    dag_id: str,
    candidate_snapshot: dict[str, Any],
    *,
    proposal: dict[str, Any],
    actor: str,
    workspace_id: str = "",
    validation: dict[str, Any],
) -> dict[str, Any]:
    """Phases 3 and 4 for one optimizer-authored candidate (#2501).

    Phase 3 — approval. The candidate is gated by the canonical contract
    before any store transition: evidence must cite evaluation Runs and the
    evaluator's version, the deciding authority must not be the authoring
    path, the base must still be current by content, and the content must be
    a change. Each refusal is a truthful non-applied outcome.

    Phase 4 — promotion. Only an approved candidate reaches
    ``commit_candidate``. The contract's record is appended to its ledger only
    after the store transition committed, so the ledger never describes a
    version that never activated.
    """
    import stores

    proposal_id = str(proposal.get("id", "") or "")
    source_hash = str(proposal.get("source_dag_hash") or "")
    record: dict[str, Any] = {
        "proposal_id": proposal_id,
        "dag_id": dag_id,
        "resulting_version": None,
        "outcome": FAILED,
        "detail": "",
        "policy_id": AUTO_PROMOTION_POLICY_ID,
    }

    run_ids, evaluator_version = _evidence_of(validation)
    baseline = validation.get("baseline") or {}
    if evaluator_version != str(baseline.get("evaluator_version") or ""):
        record["outcome"] = UNEVALUATED
        record["detail"] = (
            "baseline and candidate were judged by different evaluator versions "
            f"({baseline.get('evaluator_version') or 'none'} vs {evaluator_version or 'none'})"
        )
        _audit_apply(actor, record, severity="warning")
        return record

    try:
        competing_version = await active_template_version(dag_id)
    except Exception as exc:
        record["detail"] = f"template store unreadable: {type(exc).__name__}: {exc}"
        _audit_apply(actor, record, severity="warning")
        return record
    current = stores.dags.get(dag_id)
    current_hash = snapshot_hash(current) if current else ""
    contract = promotion_contract()
    base_version = await _base_version(contract, dag_id, current_hash)

    try:
        change = CandidateChange(
            scope=PromotionScope.TEMPLATE,
            subject=dag_id,
            base_version=base_version,
            base_content_hash=source_hash,
            proposed_content_hash=snapshot_hash(candidate_snapshot),
            changed_refs=(str(proposal.get("field_path") or ""),),
            author=CANDIDATE_AUTHOR,
            evidence=EvaluationEvidence(
                evaluation_run_ids=run_ids,
                evaluator_versions={EVALUATOR_NAME: evaluator_version},
            ),
        )
        approval = PromotionApproval(
            approver=actor,
            reason=(
                f"{str(proposal.get('rationale') or '').strip() or 'optimizer proposal'} "
                f"[{proposal_id}] independent validation: candidate "
                f"{validation.get('variant_b_score')} vs incumbent "
                f"{validation.get('baseline_score')} ({evaluator_version}); Runs "
                f"{', '.join(run_ids)}"
            ),
            policy_id=AUTO_PROMOTION_POLICY_ID,
        )
    except ValueError as exc:
        record["detail"] = f"approval could not be stated: {exc}"
        _audit_apply(actor, record, severity="warning")
        return record

    minted = _gate(
        contract,
        change,
        approval,
        actor,
        record,
        base_version=base_version,
        current_hash=current_hash,
        competing_version=competing_version,
    )
    if minted is None:
        return record

    committed = await commit_candidate(
        dag_id,
        candidate_snapshot,
        actor=actor,
        proposal_id=proposal_id,
        source_hash=source_hash,
        reason=approval.reason,
        workspace_id=workspace_id,
        approval=approval,
        version=minted.new_version,
        evidence={
            "evaluation_run_ids": list(run_ids),
            "evaluator_version": evaluator_version,
            "baseline_score": validation.get("baseline_score"),
            "variant_b_score": validation.get("variant_b_score"),
        },
    )
    if committed.get("outcome") == APPLIED:
        contract.ledger.append(minted)
        committed["promotion_record_id"] = minted.record_id
    elif committed.get("outcome") == STALE and "competing_version" not in committed:
        committed["competing_version"] = competing_version
    return committed


def _gate(
    contract: PromotionContract,
    change: CandidateChange,
    approval: PromotionApproval,
    actor: str,
    record: dict[str, Any],
    *,
    base_version: int,
    current_hash: str,
    competing_version: int | None,
) -> PromotionRecord | None:
    """Phase 3: run the canonical fences; return the minted record or a refusal in place.

    Each fence maps to the truthful non-applied outcome: incomplete evidence is
    `unevaluated`, a moved base is `stale` (naming the competing version), a
    protected-constituent edit is `unsupported`, identical content is `no_op`,
    and anything else — self-approval included — is `failed`, by rule.
    """
    try:
        return contract.evaluate(
            change,
            approval,
            current_version=base_version,
            current_content_hash=current_hash,
        )
    except IncompleteEvidence as exc:
        _refused(actor, record, UNEVALUATED, f"evidence incomplete: {exc}")
    except StaleCandidate:
        _refused(
            actor,
            record,
            STALE,
            "DAG changed while the candidate was being approved; refusing to re-target",
            competing_version=competing_version,
        )
    except (ProtectedConstituentEdit, UnchangedCandidate, PromotionRefused) as exc:
        outcome = FAILED
        if isinstance(exc, ProtectedConstituentEdit):
            outcome = UNSUPPORTED
        elif isinstance(exc, UnchangedCandidate):
            outcome = NO_OP
        _refused(actor, record, outcome, f"promotion refused: {exc}")
    return None


def _refused(
    actor: str,
    record: dict[str, Any],
    outcome: str,
    detail: str,
    *,
    competing_version: int | None = None,
) -> dict[str, Any]:
    record["outcome"] = outcome
    record["detail"] = detail
    record["competing_version"] = competing_version
    _audit_apply(actor, record, severity="warning")
    return record


def _audit_apply(actor: str, record: dict[str, Any], *, severity: str) -> None:
    from routes.audit import log_audit

    log_audit(
        action="optimizer_apply",
        actor=actor,
        target=record.get("dag_id", ""),
        detail=dict(record),
        severity=severity,  # type: ignore[arg-type]
    )


def record_escalation(
    proposal: dict[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    """Record an execution-tier proposal as a REQUEST — nothing more.

    The proposal is not applied and no approval field is written anywhere; the
    audit entry is the request record the delegated/elevated authority
    (#845/#60) decides on. Returns the escalation record.
    """
    from routes.audit import log_audit

    tp = proposal.get("topology_proposal") or {}
    record = {
        "proposal_id": proposal.get("id", ""),
        "dag_id": proposal.get("dag_id", ""),
        "kind": tp.get("kind", ""),
        "target_node_id": tp.get("target_node_id", ""),
        "requested_value": tp.get("to_value", ""),
        "requested_by": actor,
        "requested_at": datetime.now(UTC).isoformat(),
        "outcome": ESCALATED,
        "detail": (
            "execution-tier/authorization change is a request only; "
            "the delegated authority decides the effective tier"
        ),
    }
    log_audit(
        action="optimizer_escalation_request",
        actor=actor,
        target=record["dag_id"],
        detail=record,
        severity="warning",
    )
    return record
