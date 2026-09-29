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

The template store resolves to the engine container's ``template_store`` when
the canonical bridge is wired, and to a process-local
``InMemoryGraphTemplateStore`` otherwise — the same store family either way, so
the promotion semantics are identical in both modes rather than a weaker local
copy of them.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

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


def _workspace_id_for(dag_id: str, snapshot: dict[str, Any]) -> str:
    """The Workspace the candidate template is registered under.

    Same resolution the scheduler uses when priming a descriptor into the
    template store, so both writers land in the same Workspace and the store's
    workspace check never sees two owners for one template id.
    """
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
        workspace_id=_workspace_id_for(dag_id, candidate_snapshot),
        template_id=dag_id,
        version=version,
    ).model_copy(update={"lifecycle": "candidate"})
    return store, template.content_hash, template


async def commit_candidate(
    dag_id: str,
    candidate_snapshot: dict[str, Any],
    *,
    actor: str,
    proposal_id: str,
    source_hash: str,
    reason: str = "",
) -> dict[str, Any]:
    """Apply one optimizer-proposed change as candidate + audited promotion.

    Returns the apply record: ``{"outcome", "candidate_hash",
    "resulting_version", "detail"}``. ``applied`` is reported only after the
    promotion has committed and the editable descriptor surface has been
    synced to the promoted content — never before, and never for a mutation
    that changed nothing.
    """
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
    version = max(existing, default=0) + 1
    prior_active = await active_template_version(dag_id)

    # Compare-and-swap #1: the source binding was checked synchronously by the
    # caller (_bound_source), but awaits since then may have let a user edit
    # or another promotion land. Refuse before touching the store rather than
    # promoting onto a moved base.
    if dag_id not in stores.dags or snapshot_hash(stores.dags[dag_id]) != source_hash:
        record["outcome"] = STALE
        record["detail"] = "DAG changed while the proposal was being applied; refusing to re-target"
        _audit_apply(actor, record, severity="warning")
        return record

    try:
        _, _, template = _register_candidate(candidate_snapshot, dag_id=dag_id, version=version)
    except Exception as exc:
        record["detail"] = f"candidate projection refused: {type(exc).__name__}: {exc}"
        _audit_apply(actor, record, severity="warning")
        return record
    record["candidate_hash"] = template.content_hash

    from maistro.graph.templates import PromotionApproval, promote_audited

    approval = PromotionApproval(
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
        await promote_audited(store, dag_id, version, audit=audit, approval=approval)
    except BaseException as exc:
        # promote_audited compensates its own lifecycle transition; the active
        # version is unchanged and the failure is reported, not swallowed.
        record["detail"] = f"promotion failed: {type(exc).__name__}: {exc}"
        _audit_apply(actor, record, severity="warning")
        return record

    # Compare-and-swap #2: the descriptor is only synced when it still holds
    # the content the candidate was computed against. If it moved during the
    # promotion awaits, the promotion is compensated — the just-activated
    # version is demoted and the prior active version restored — and the
    # conflict is reported; the concurrent edit is never overwritten.
    if dag_id not in stores.dags or snapshot_hash(stores.dags[dag_id]) != source_hash:
        try:
            await store.set_lifecycle(dag_id, version, "candidate")
            if prior_active is not None:
                await store.set_lifecycle(dag_id, prior_active, "active")
        except Exception as exc:
            record["detail"] = (
                f"DAG changed during apply and rollback of version {version} failed: "
                f"{type(exc).__name__}: {exc}; descriptor left untouched"
            )
            _audit_apply(actor, record, severity="warning")
            return record
        record["outcome"] = STALE
        record["detail"] = (
            f"DAG changed during apply; candidate version {version} rolled back, "
            "descriptor left untouched"
        )
        _audit_apply(actor, record, severity="warning")
        return record

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
