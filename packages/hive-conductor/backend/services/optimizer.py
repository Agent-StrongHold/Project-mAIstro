"""Phase 6 — Optimizer service: 5-signal weighted aggregator + proposer.

Ingests:

  Signal #1 error_code        weight 3.0
  Signal #2 user_manual_edit  weight 2.5   (highest among non-failure)
  Signal #3 eval_judge_score  weight 1.5
  Signal #4 thumbs            weight 1.0
  Signal #5 latency/tokens    weight 0.5

Reads from:

  - services.node_metrics_store     → per-node latency / tokens / errors
  - services.feedback_service       → thumbs outcomes (via outcome_store)
  - stores.eval_verdicts            → eval-judge verdicts (rationale + proposal)
  - stores.audit_log                → dag_edit entries (user manual overrides)

Emits ranked proposals into stores.optimizer_proposals. Each proposal
has a class:

  AUTO_APPLY — model swap / edge weight tune / retry-count adjustment.
                Applied ONLY through the canonical candidate/promotion
                contract (#861): the proposed change is registered as an
                immutable candidate GraphTemplate version and promoted via
                promote_audited. A proposal without a concrete target value
                cannot be applied and is reported as `unsupported` — never
                as applied. Every application outcome is audited with what
                actually committed.

  PROPOSE    — topology mutations / prompt rewrites. The user reviews +
               approves via POST /v1/optimizer/proposals/{id}/accept.
               Acceptance is a PromotionApproval: the mutation becomes a
               candidate bound to the exact source DAG content hash and is
               promoted through the canonical audited contract (#116,
               ADR-082926-65bf). Verdict/evaluator output never mutates the
               DAG directly — it is evidence; only the promoted candidate
               changes state.

Execution-tier kinds (upgrade_execution_tier) are REQUESTS ONLY: accepting one
records an escalation request for the delegated authority (#845/#60) and never
mutates the DAG or stamps an approval field.

The optimizer never raises on data anomalies; missing / empty stores
produce zero proposals and an empty result. Unmeasured metrics are absent
values (ADR-083026-a91e): missing latency contributes nothing to a score
rather than crashing a None comparison or ranking as ideal.
"""

from __future__ import annotations

import contextlib
import copy
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from services.optimizer_candidates import (
    ESCALATION_KINDS,
    MANUAL,
    STALE,
    UNSUPPORTED,
    commit_candidate,
    record_escalation,
    snapshot_hash,
)

logger = logging.getLogger(__name__)


# Weighted aggregator constants — locked per the 90-day plan.
WEIGHT_ERROR_CODE = 3.0
WEIGHT_USER_EDIT = 2.5
WEIGHT_EVAL_JUDGE = 1.5
WEIGHT_THUMB = 1.0

# SkillOpt-inspired controls
TEXTUAL_LEARNING_RATE = 4  # max edits per optimization pass (add/delete/replace)
MAX_REJECTED_BUFFER = 20  # remember last N rejected edits to avoid repeating
WEIGHT_LATENCY = 0.5

# Proposal classes — gating for auto-apply vs propose-only.
CLASS_AUTO_APPLY = "auto_apply"
CLASS_PROPOSE = "propose"

# Auto-apply kinds.
KIND_MODEL_SWAP = "model_swap"
KIND_EDGE_WEIGHT = "edge_weight_tune"
KIND_RETRY_COUNT = "retry_count_tune"

# Propose-only kinds.
KIND_TOPOLOGY = "topology_mutation"
KIND_PROMPT = "prompt_rewrite"

# Decisions a user can take on a propose-only proposal.
DECISION_ACCEPTED = "accepted"
DECISION_REJECTED = "rejected"
DECISION_PENDING = "pending"

# Latency threshold above which the latency signal contributes.
LATENCY_P95_THRESHOLD_MS = 5_000


@dataclass(frozen=True)
class SignalSnapshot:
    """Aggregated signal weights for one (dag_id, target_node_id) bucket.

    The optimizer sums these into a single `priority_score` for ranking;
    proposals derived from the snapshot inherit the score so the UI can
    sort by impact."""

    dag_id: str
    target_node_id: str = ""
    error_score: float = 0.0
    edit_score: float = 0.0
    eval_score: float = 0.0
    thumb_score: float = 0.0
    latency_score: float = 0.0
    # Free-form context the proposer reads for justification text.
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def priority_score(self) -> float:
        return round(
            self.error_score
            + self.edit_score
            + self.eval_score
            + self.thumb_score
            + self.latency_score,
            3,
        )


def _collect_node_metrics(dag_id: str, window_seconds: int) -> dict[str, dict[str, Any]]:
    """Return {node_id_or_kind: aggregate} from node_metrics_store."""
    from services.node_metrics_store import get_store as _metrics_store

    store = _metrics_store()
    # Roll up by node_id (per-node) so optimizer can target a specific
    # node, but also keep a per-kind view for kind-level decisions.
    #
    # `observations` and `summarize`, not `store._filter` and `_aggregate`:
    # those are private to one implementation, so a different metrics store
    # would break this reader without a type error anywhere (#698).
    obs = store.observations(dag_id=dag_id, window_seconds=window_seconds)
    by_node: dict[str, list[Any]] = {}
    for o in obs:
        by_node.setdefault(o.node_id, []).append(o)
    out: dict[str, dict[str, Any]] = {}
    for node_id, group in by_node.items():
        items = list(group)
        out[node_id] = store.summarize(items)
        out[node_id]["node_kind"] = items[0].node_kind if items else ""
    return out


async def _collect_thumbs(
    dag_id: str, *, org_id: str = "", project_id: str = ""
) -> dict[str, dict[str, Any]]:
    """Return {node_id: {up, down, comments}} from feedback_service's store.

    Async because the thumbs signal is now read from a durable store rather
    than walked off a list in this process. The loop that used to live here
    read `store._outcomes` directly, which only the in-memory store has, so
    the optimizer would have gone quietly blind the moment the Conductor was
    pointed at PostgreSQL or SQLite (#696).
    """
    from services.feedback_service import collect_thumbs

    return await collect_thumbs(dag_id, org_id=org_id, project_id=project_id)


def _collect_eval_verdicts(dag_id: str) -> list[dict[str, Any]]:
    """Return eval-judge verdicts that name exactly this DAG.

    The old fallback — "use all verdicts when none match" — let verdicts
    authored against one DAG surface as proposals for another, and an accepted
    wrong-DAG proposal then mutated whichever DAG was being optimized (#861).
    A verdict that does not name this dag_id is unattributable evidence here:
    it contributes nothing. Missing evidence is absent, not a wildcard.
    """
    import stores

    if not dag_id:
        return []
    return [v for v in stores.eval_verdicts.values() if v.get("dag_id") == dag_id]


def _collect_user_edits(dag_id: str) -> list[dict[str, Any]]:
    """Return dag_edit audit entries for this DAG."""
    import stores

    return [
        e
        for e in stores.audit_log.values()
        if e.get("action") == "dag_edit" and e.get("target") == dag_id
    ]


async def _build_snapshot_for_dag(
    dag_id: str,
    window_seconds: int = 24 * 3600,
    *,
    org_id: str = "",
    project_id: str = "",
) -> dict[str, SignalSnapshot]:
    """Build one SignalSnapshot per node_id that has any signal."""
    metrics = _collect_node_metrics(dag_id, window_seconds)
    thumbs = await _collect_thumbs(dag_id, org_id=org_id, project_id=project_id)
    verdicts = _collect_eval_verdicts(dag_id)
    edits = _collect_user_edits(dag_id)

    # Eval scores are run-level, not node-level → contribute as a
    # baseline against every node in the latest verdict. The proposer
    # uses topology_proposal.target_node_id when available.
    eval_baseline = 0.0
    eval_context: list[dict[str, Any]] = []
    if verdicts:
        verdicts_sorted = sorted(
            verdicts,
            key=lambda v: v.get("scored_at", ""),
            reverse=True,
        )
        # Use the WORST score as baseline — that's what needs improvement
        worst_score = min(float(v.get("score", 100)) for v in verdicts)
        eval_baseline = max(0.0, (100 - worst_score) / 100.0)
        eval_context = verdicts_sorted[:5]

    # User edits aren't per-node either — they're per-field-path. The
    # signal here is "the user is actively touching this DAG", which
    # *raises* the optimizer's caution score (don't auto-apply on
    # edited fields). We surface the edit_score on the dag-level
    # snapshot (target_node_id="") and the proposer respects it via
    # edit_lock.is_locked() at proposal-write time.
    edit_score_total = WEIGHT_USER_EDIT * min(len(edits), 5) / 5.0  # cap at 1*weight

    all_node_ids = set(metrics.keys()) | set(thumbs.keys())
    # If no node-level data, create a DAG-level snapshot from eval verdicts
    if not all_node_ids and (verdicts or edits):
        all_node_ids = {"_dag_level_"}
    snapshots: dict[str, SignalSnapshot] = {}

    for nid in all_node_ids:
        m = metrics.get(nid, {})
        th = thumbs.get(nid, {"up": 0, "down": 0, "comments": []})
        # Signal #1 error_code: fraction of failures x weight
        n = m.get("count", 0)
        failed = m.get("failed", 0)
        err_score = (failed / max(n, 1)) * WEIGHT_ERROR_CODE if n else 0.0
        # Signal #4 thumbs: (down - up) capped at 5 each → weight
        thumb_score = (th["down"] - th["up"]) * WEIGHT_THUMB
        thumb_score = max(0.0, thumb_score)  # only down moves the needle
        # Signal #5 latency: p95 above threshold → weight. An unmeasured p95
        # is `None` (the metrics store reports absent, not zero — ADR-083026-a91e);
        # `None > threshold` used to raise TypeError here, crashing the whole
        # optimizer pass on ordinary missing-latency data. Absent latency
        # contributes nothing: not a crash, and not an ideal score.
        p95 = m.get("latency_ms_p95")
        if p95 is None:
            latency_score = 0.0
        else:
            latency_score = WEIGHT_LATENCY if p95 > LATENCY_P95_THRESHOLD_MS else 0.0
        # eval_judge: baseline contributes to every node in the latest run
        eval_score = eval_baseline * WEIGHT_EVAL_JUDGE

        snapshots[nid] = SignalSnapshot(
            dag_id=dag_id,
            target_node_id=nid,
            error_score=round(err_score, 3),
            edit_score=round(edit_score_total, 3),
            eval_score=round(eval_score, 3),
            thumb_score=round(thumb_score, 3),
            latency_score=round(latency_score, 3),
            context={
                "metrics": m,
                "thumbs": th,
                "eval_verdicts": eval_context,
                "user_edit_count": len(edits),
                # How many observations actually carried a latency measure, so
                # a zero latency_score is readable as "unmeasured", not "fast".
                "latency_ms_measured": m.get("latency_ms_measured", 0),
            },
        )
    return snapshots


def _propose_for_snapshot(
    snapshot: SignalSnapshot,
) -> list[dict[str, Any]]:
    """Translate a SignalSnapshot into 0-3 candidate proposals (raw dicts)."""
    proposals: list[dict[str, Any]] = []

    # AUTO_APPLY candidate #1: model swap on high error_score
    if snapshot.error_score >= 1.5:
        proposals.append(
            {
                "class": CLASS_AUTO_APPLY,
                "kind": KIND_MODEL_SWAP,
                "field_path": f"nodes[{snapshot.target_node_id}].model",
                "rationale": (
                    f"Node {snapshot.target_node_id} is failing — "
                    f"{int(snapshot.context['metrics']['failed'])} of "
                    f"{int(snapshot.context['metrics']['count'])} runs failed. "
                    "Switching to a more capable model often clears tool-call "
                    "schema issues."
                ),
            }
        )

    # AUTO_APPLY candidate #2: retry-count bump on moderate error_score
    elif snapshot.error_score >= 0.5:
        proposals.append(
            {
                "class": CLASS_AUTO_APPLY,
                "kind": KIND_RETRY_COUNT,
                "field_path": f"nodes[{snapshot.target_node_id}].config.max_retries",
                # The one auto-apply kind with a concrete, auditable target:
                # without a value to commit there is nothing to apply, and
                # claiming an application would be the fake-success shape
                # #861 removes.
                "to_value": 3,
                "rationale": (
                    f"Node {snapshot.target_node_id} fails intermittently. "
                    "A retry budget of 3 with exponential backoff would "
                    "absorb most transient errors."
                ),
            }
        )

    # AUTO_APPLY candidate #3: edge weight tune on high latency_score
    if snapshot.latency_score > 0.0:
        proposals.append(
            {
                "class": CLASS_AUTO_APPLY,
                "kind": KIND_EDGE_WEIGHT,
                "field_path": f"nodes[{snapshot.target_node_id}].config.weight",
                "rationale": (
                    f"Node {snapshot.target_node_id} p95 latency "
                    f"{int(snapshot.context['metrics']['latency_ms_p95'])}ms "
                    "is above threshold; reduce downstream edge weight by "
                    "20% to deprioritize this hop."
                ),
            }
        )

    # PROPOSE candidate: surface eval-judge topology_proposal verbatim
    for v in snapshot.context.get("eval_verdicts") or []:
        tp = v.get("topology_proposal")
        if not tp:
            continue
        # Match by target_node_id OR by role name (eval-judge may use either)
        target = tp.get("target_node_id", "")
        # Try matching by role — eval-judge often uses role names
        if (
            target
            and target != snapshot.target_node_id
            and target != "_dag_level_"
            and snapshot.target_node_id != "_dag_level_"
        ):
            continue
        proposals.append(
            {
                "class": CLASS_PROPOSE,
                "kind": KIND_TOPOLOGY,
                "field_path": f"nodes[{target}].{tp.get('kind', '')}",
                "rationale": tp.get("expected_improvement", "")
                or "Eval-judge proposed this topology mutation.",
                "topology_proposal": tp,
                # Provenance of the evidence this proposal surfaces: which
                # evaluator authored the verdict it came from (#861).
                "evaluator_version": v.get("evaluator_version", ""),
            }
        )

    # PROPOSE candidate: prompt rewrite on persistent thumbs-down
    if snapshot.thumb_score >= 2.0:
        comments = snapshot.context["thumbs"]["comments"][:3]
        proposals.append(
            {
                "class": CLASS_PROPOSE,
                "kind": KIND_PROMPT,
                "field_path": f"nodes[{snapshot.target_node_id}].prompt",
                "rationale": (
                    "Users keep thumbing this node down. Recent comments: "
                    + " | ".join(comments[:3])
                    if comments
                    else "Users keep thumbing this node down without comments."
                ),
            }
        )

    return proposals


async def run_optimizer(
    dag_id: str,
    *,
    actor: str = "optimizer",
    window_seconds: int = 24 * 3600,
    apply_auto: bool = False,
    edit_lock_now: datetime | None = None,
    now: datetime | None = None,
    org_id: str = "",
    project_id: str = "",
    workspace_id: str = "",
) -> dict[str, Any]:
    """Run one optimizer pass on the given DAG.

    Returns:
        {
          "dag_id": <id>,
          "proposals": [<proposal>, ...],   # ranked by priority_score desc
          "auto_applied": int,              # only truthfully-committed applies
          "blocked_by_edit_lock": int,
        }

    Every proposal binds the exact source it was computed against
    (`source_dag_hash`, `source_template_version`) plus the evaluator version
    of the verdict evidence it surfaced, so a stale proposal can never be
    applied to a different DAG state (#861). Proposals also carry the
    Workspace the triggering request was authorized against, so candidate
    registration lands in the authorizing tenant (#861 review).

    When `apply_auto=True`, AUTO_APPLY proposals that are NOT edit-locked go
    through the candidate/promotion path in services.optimizer_candidates and
    report a truthful per-proposal `apply_outcome`: `applied` only after the
    candidate version actually promoted, else `no_op` / `unsupported` /
    `stale` / `failed`. `auto_applied` counts real applications only.
    When False (default), every proposal is recorded as PENDING and the
    user reviews via the UI.
    """
    if not dag_id:
        raise ValueError("dag_id is required")

    import stores
    from routes.audit import log_audit

    from services.edit_lock import is_locked
    from services.optimizer_candidates import APPLIED, active_template_version

    snapshots = await _build_snapshot_for_dag(
        dag_id,
        window_seconds=window_seconds,
        org_id=org_id,
        project_id=project_id,
    )
    ranked = sorted(snapshots.values(), key=lambda s: s.priority_score, reverse=True)

    # The exact-source binding every proposal from this pass inherits: the
    # content hash of the DAG snapshot the signals were computed against, and
    # the currently-active canonical template version when one exists (#861).
    source_snapshot = stores.dags.get(dag_id)
    source_hash = snapshot_hash(source_snapshot) if source_snapshot else ""
    source_version = await active_template_version(dag_id)

    out_proposals: list[dict[str, Any]] = []
    auto_applied = 0
    blocked = 0
    created_at = (now or datetime.now(UTC)).isoformat()

    for snap in ranked:
        if snap.priority_score <= 0:
            continue
        for raw in _propose_for_snapshot(snap):
            proposal_id = str(uuid.uuid4())
            decision = DECISION_PENDING
            applied = False
            apply_outcome: str | None = None
            apply_detail = ""
            resulting_version: int | None = None
            candidate_hash_value: str | None = None
            field_path = raw["field_path"]
            blocked_by_lock = is_locked(dag_id, field_path, now=edit_lock_now)
            if raw["class"] == CLASS_AUTO_APPLY and apply_auto and not blocked_by_lock:
                # Application goes through the same candidate/promotion
                # contract a human acceptance does — `applied` means a
                # candidate version actually promoted, nothing less (#861).
                outcome = await _apply_auto_proposal(
                    raw,
                    dag_id=dag_id,
                    source_hash=source_hash,
                    proposal_id=proposal_id,
                    actor=actor,
                    target_node_id=snap.target_node_id,
                    workspace_id=workspace_id,
                )
                apply_outcome = outcome["outcome"]
                apply_detail = outcome["detail"]
                resulting_version = outcome.get("resulting_version")
                candidate_hash_value = outcome.get("candidate_hash")
                if apply_outcome == APPLIED:
                    applied = True
                    auto_applied += 1
                    decision = DECISION_ACCEPTED
                elif apply_outcome == "escalated":
                    decision = DECISION_PENDING  # a request is not a decision
            elif raw["class"] == CLASS_AUTO_APPLY and blocked_by_lock:
                blocked += 1
                decision = DECISION_PENDING  # surface as propose for human
            payload = {
                "id": proposal_id,
                "dag_id": dag_id,
                "target_node_id": snap.target_node_id,
                "class": raw["class"],
                "kind": raw["kind"],
                "field_path": field_path,
                "rationale": raw["rationale"],
                "priority_score": snap.priority_score,
                # The concrete target value for the one auto-apply kind that
                # carries one (retry_count_tune); a human accept of this
                # proposal applies the same committed value (#861).
                "to_value": raw.get("to_value"),
                # Exact-source binding: proposals from a stale snapshot are
                # refused at apply time by content hash, never silently
                # re-targeted at whatever the DAG now holds (#861).
                "source_dag_hash": source_hash,
                "source_template_version": source_version,
                "evaluator_version": raw.get("evaluator_version", ""),
                "workspace_id": workspace_id,
                "blocked_by_edit_lock": blocked_by_lock,
                "applied": applied,
                "apply_outcome": apply_outcome,
                "apply_detail": apply_detail,
                "resulting_version": resulting_version,
                "candidate_hash": candidate_hash_value,
                "decision": decision,
                "created_at": created_at,
                "topology_proposal": raw.get("topology_proposal"),
            }
            stores.optimizer_proposals[proposal_id] = payload
            out_proposals.append(payload)

    log_audit(
        action="optimizer_run",
        actor=actor,
        target=dag_id,
        detail={
            "proposal_count": len(out_proposals),
            "auto_applied": auto_applied,
            "blocked_by_edit_lock": blocked,
            "apply_auto_flag": apply_auto,
            "source_dag_hash": source_hash,
            "source_template_version": source_version,
        },
    )

    return {
        "dag_id": dag_id,
        "proposals": out_proposals,
        "auto_applied": auto_applied,
        "blocked_by_edit_lock": blocked,
    }


async def _apply_auto_proposal(
    raw: dict[str, Any],
    *,
    dag_id: str,
    source_hash: str,
    proposal_id: str,
    actor: str,
    target_node_id: str = "",
    workspace_id: str = "",
) -> dict[str, Any]:
    """Attempt one auto-apply through the candidate/promotion contract.

    Returns the apply record. Kinds that name no concrete value to commit are
    `unsupported` — recorded as evidence, never reported as applied (#861).
    """
    from routes.audit import log_audit

    candidate, outcome, detail = _mutated_snapshot(
        {
            "id": proposal_id,
            "dag_id": dag_id,
            "source_dag_hash": source_hash,
            "kind": raw["kind"],
            "topology_proposal": raw.get("topology_proposal")
            or {
                "kind": raw["kind"],
                "target_node_id": target_node_id,
                "to_value": raw.get("to_value"),
            },
        }
    )
    record: dict[str, Any] = {
        "outcome": outcome,
        "detail": detail,
        "resulting_version": None,
        "candidate_hash": None,
    }
    if outcome != BUILT:
        log_audit(
            action="optimizer_auto_apply",
            actor=actor,
            target=dag_id,
            detail={
                "proposal_id": proposal_id,
                "kind": raw["kind"],
                "outcome": outcome,
                "detail": detail,
            },
        )
        return record
    from services.optimizer_candidates import commit_candidate as _commit

    committed = await _commit(
        dag_id,
        candidate,
        actor=actor,
        proposal_id=proposal_id,
        source_hash=source_hash,
        reason=raw.get("rationale", ""),
        workspace_id=workspace_id,
    )
    return committed


async def record_decision(
    proposal_id: str,
    decision: str,
    *,
    actor: str,
) -> dict[str, Any]:
    """Record an accept/reject on a proposal. The decision itself flows
    back into outcome_store as a Signal #4-equivalent so the next
    optimizer pass treats user-approval as positive reinforcement.

    An accepted topology mutation is NOT written into the DAG record
    directly (#861). It becomes an immutable candidate version of the DAG,
    bound to the exact source content hash the proposal was computed
    against, and is promoted through the canonical audited contract
    (`promote_audited`) with the accepting user named as the approver. The
    payload's `apply_outcome` says what actually happened; `applied` is
    only ever true when a candidate version really promoted.
    """
    if decision not in (DECISION_ACCEPTED, DECISION_REJECTED):
        raise ValueError(
            f"decision must be one of {(DECISION_ACCEPTED, DECISION_REJECTED)}, got {decision!r}"
        )
    import stores
    from routes.audit import log_audit

    payload = stores.optimizer_proposals.get(proposal_id)
    if payload is None:
        raise KeyError(proposal_id)
    payload = dict(payload)
    payload["decision"] = decision
    payload["decided_by"] = actor
    payload["decided_at"] = datetime.now(UTC).isoformat()

    if decision == DECISION_ACCEPTED:
        if payload.get("kind") == KIND_TOPOLOGY:
            payload.update(await _apply_accepted_topology(payload, actor=actor))
        elif payload.get("class") == CLASS_AUTO_APPLY:
            # A human accepted what the optimizer would have auto-applied;
            # same contract, the human is the approver of record.
            raw = {
                "kind": payload.get("kind", ""),
                "rationale": payload.get("rationale", ""),
                "to_value": payload.get("to_value"),
                "topology_proposal": payload.get("topology_proposal"),
            }
            outcome = await _apply_auto_proposal(
                raw,
                dag_id=payload.get("dag_id", ""),
                source_hash=payload.get("source_dag_hash", ""),
                proposal_id=proposal_id,
                actor=actor,
                target_node_id=payload.get("target_node_id", ""),
                workspace_id=payload.get("workspace_id", ""),
            )
            payload["apply_outcome"] = outcome["outcome"]
            payload["apply_detail"] = outcome["detail"]
            payload["resulting_version"] = outcome.get("resulting_version")
            payload["candidate_hash"] = outcome.get("candidate_hash")
            payload["applied"] = outcome["outcome"] == "applied"
        else:
            # A proposal the optimizer cannot author itself (e.g. a prompt
            # rewrite needs the human's words). The DECISION is recorded; the
            # change itself is authored in the editor. Saying nothing here
            # would leave the only apply-ish signal the old fake `applied`.
            payload["apply_outcome"] = MANUAL
            payload["apply_detail"] = "decision recorded; author the change in the DAG editor"

    stores.optimizer_proposals[proposal_id] = payload

    # Track rejected edits so optimizer doesn't re-propose them (SkillOpt rejected-edit buffer)
    if decision == DECISION_REJECTED:
        _record_rejected_edit(payload)

    log_audit(
        action="optimizer_decision",
        actor=actor,
        target=payload.get("dag_id", ""),
        detail={
            "proposal_id": proposal_id,
            "decision": decision,
            "kind": payload.get("kind"),
            "apply_outcome": payload.get("apply_outcome"),
            "resulting_version": payload.get("resulting_version"),
        },
    )
    return payload


async def _apply_accepted_topology(payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
    """Apply an accepted topology proposal through the candidate contract.

    Updates the payload dict in place with the truthful apply record keys and
    returns them. Never writes the verdict-authored values into the live DAG
    directly: the only mutation is a promoted, audited candidate version.
    """
    dag_id = payload.get("dag_id", "")
    tp = payload.get("topology_proposal") or {}
    mutation_kind = tp.get("kind", "")

    # Execution-tier/authorization changes are REQUESTS ONLY (#861; #845/#60
    # own the effective authority). Recording the request never mutates the
    # DAG and never stamps an approval field — the historical behavior wrote
    # `tier_approved_by: "admin"` here, certifying an approval nobody gave.
    if mutation_kind in ESCALATION_KINDS or payload.get("kind", "") in ESCALATION_KINDS:
        escalation = record_escalation(payload, actor=actor)
        return {
            "apply_outcome": escalation["outcome"],
            "apply_detail": escalation["detail"],
            "resulting_version": None,
            "candidate_hash": None,
            "applied": False,
        }

    candidate, outcome, detail = _mutated_snapshot(payload)
    if outcome != BUILT:
        return {
            "apply_outcome": outcome,
            "apply_detail": detail,
            "resulting_version": None,
            "candidate_hash": None,
            "applied": False,
        }
    assert candidate is not None  # for the type checker: non-built outcomes returned above
    committed = await commit_candidate(
        dag_id,
        candidate,
        actor=actor,
        proposal_id=payload.get("id", ""),
        source_hash=payload.get("source_dag_hash", ""),
        reason=payload.get("rationale", ""),
        workspace_id=payload.get("workspace_id", ""),
    )
    return {
        "apply_outcome": committed["outcome"],
        "apply_detail": committed["detail"],
        "resulting_version": committed.get("resulting_version"),
        "candidate_hash": committed.get("candidate_hash"),
        "applied": committed["outcome"] == "applied",
    }


# SkillOpt rejected-edit buffer — prevents re-proposing failed mutations
_rejected_buffer: list[dict[str, Any]] = []


def _record_rejected_edit(proposal: dict[str, Any]) -> None:
    """Remember a rejected edit so the optimizer avoids re-proposing it."""
    _rejected_buffer.append(
        {
            "kind": proposal.get("kind"),
            "field_path": proposal.get("field_path"),
            "dag_id": proposal.get("dag_id"),
            "rejected_at": datetime.now(UTC).isoformat(),
        }
    )
    # Keep buffer bounded
    while len(_rejected_buffer) > MAX_REJECTED_BUFFER:
        _rejected_buffer.pop(0)


def get_rejected_buffer(dag_id: str = "") -> list[dict[str, Any]]:
    """Return rejected edits for a DAG (or all). Fed to eval-judge as negative signal."""
    if dag_id:
        return [r for r in _rejected_buffer if r.get("dag_id") == dag_id]
    return list(_rejected_buffer)


def _apply_node_field_mutation(node: dict[str, Any], kind: str, tp: dict[str, Any]) -> None:
    """Mutate a single matched node's field in place, per `kind`.

    Only kinds with a concrete content effect are handled here. Authorization
    posture (execution tier) is deliberately absent: those proposals are
    requests, decided by the delegated authority, never materialized by the
    optimizer — and never self-stamped with an approval (#861, #845/#60).
    """
    if kind == "swap_model":
        node["model"] = tp.get("to_value", node.get("model"))
    elif kind == "rewrite_prompt":
        node["prompt"] = tp.get("to_value", node.get("prompt"))
    elif kind == "change_schema":
        node.setdefault("config", {})["output_schema"] = tp.get("to_value", "")
    elif kind == "change_temperature":
        with contextlib.suppress(ValueError, TypeError):
            node["temperature"] = float(tp.get("to_value", 0.3))
    elif kind == "change_max_tokens":
        with contextlib.suppress(ValueError, TypeError):
            node["max_tokens"] = int(tp.get("to_value", 4096))
    elif kind == "change_strategy":
        node["strategy"] = tp.get("to_value", "direct")
    elif kind == "rename_node":
        node["name"] = tp.get("to_value", node.get("name"))
    elif kind == "change_role":
        node["role"] = tp.get("to_value", node.get("role"))


def _apply_edge_field_mutation(edge: dict[str, Any], kind: str, tp: dict[str, Any]) -> None:
    """Mutate a single matched edge's field in place, per `kind`."""
    if kind == "tune_edge_weight":
        with contextlib.suppress(ValueError, TypeError):
            edge["weight"] = float(tp.get("to_value", 1.0))
    elif kind == "set_edge_condition":
        edge["condition"] = tp.get("to_value", "")


# Kinds that mutate a single target node's field.
_NODE_FIELD_KINDS = frozenset(
    {
        "swap_model",
        "rewrite_prompt",
        "change_schema",
        "change_temperature",
        "change_max_tokens",
        "change_strategy",
        "rename_node",
        "change_role",
    }
)
# `upgrade_execution_tier` is deliberately absent from both mutation sets:
# it is an escalation request (see ESCALATION_KINDS), not an optimizer-applied
# mutation. Adding it back here would reintroduce the self-stamped approval.
# Kinds that mutate a matched edge's field (matched on from_node==target, to_node==from_value).
_EDGE_FIELD_KINDS = frozenset({"tune_edge_weight", "set_edge_condition"})
# Kinds applied as whole-snapshot structural mutations (nodes/edges/dag-level).
_STRUCTURAL_KINDS = frozenset(
    {
        "add_node",
        "drop_node",
        "reorder",
        "add_edge",
        "remove_edge",
        "change_max_cycles",
        "change_entry",
    }
)

#: `_mutated_snapshot` success marker: a candidate snapshot was built and the
#: caller may commit it. Any other outcome string is already a truthful apply
#: outcome (stale / unsupported) and committing must not proceed.
BUILT = "built"


def _reorder_node(nodes: list[dict[str, Any]], target: str) -> None:
    """Swap the target node with the node immediately after it, in place."""
    ids = [n["id"] for n in nodes]
    if target not in ids:
        return
    idx = ids.index(target)
    if idx < len(nodes) - 1:
        nodes[idx], nodes[idx + 1] = nodes[idx + 1], nodes[idx]


def _apply_structural_mutation(
    dag: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    kind: str,
    target: str,
    tp: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply a structural/graph-level mutation, returning the (possibly new) node/edge lists."""
    from uuid import uuid4

    if kind == "add_node":
        new_id = str(uuid4())[:8]
        nodes.append(
            {
                "id": new_id,
                "role": "worker",
                "name": tp.get("to_value", "New Node"),
                "prompt": tp.get("expected_improvement", ""),
                "model": "gemini-3.5-flash",
                "strategy": "direct",
            }
        )
        # Add edge from target to new node
        if target:
            edges.append({"id": str(uuid4())[:8], "from_node": target, "to_node": new_id})
    elif kind == "drop_node":
        nodes = [n for n in nodes if n.get("id") != target]
        edges = [e for e in edges if e.get("from_node") != target and e.get("to_node") != target]
    elif kind == "reorder":
        _reorder_node(nodes, target)
    elif kind == "add_edge":
        edges.append(
            {"id": str(uuid4())[:8], "from_node": target, "to_node": tp.get("to_value", "")}
        )
    elif kind == "remove_edge":
        edges = [
            e
            for e in edges
            if not (e.get("from_node") == target and e.get("to_node") == tp.get("to_value"))
        ]
    elif kind == "change_max_cycles":
        with contextlib.suppress(ValueError, TypeError):
            dag["max_cycles"] = int(tp.get("to_value", 5))
    elif kind == "change_entry":
        dag["entry_node"] = tp.get("to_value", dag.get("entry_node"))

    return nodes, edges


def _mutate_node_fields(
    nodes: list[dict[str, Any]], kind: str, target: str, tp: dict[str, Any]
) -> str:
    """Apply a node-field mutation to the one matching node. Empty detail = ok."""
    for n in nodes:
        if n.get("id") == target:
            _apply_node_field_mutation(n, kind, tp)
            return ""
    return f"no node {target!r} in the bound snapshot"


def _mutate_edge_fields(
    edges: list[dict[str, Any]], kind: str, target: str, tp: dict[str, Any]
) -> str:
    """Apply an edge-field mutation to the matching edge. Empty detail = ok."""
    for e in edges:
        if e.get("from_node") == target and e.get("to_node") == tp.get("from_value"):
            _apply_edge_field_mutation(e, kind, tp)
            return ""
    return f"no edge {target!r} -> {tp.get('from_value')!r}"


def _mutate_retry_count(nodes: list[dict[str, Any]], target: str, tp: dict[str, Any]) -> str:
    """The one auto-apply kind: set the target node's retry budget to the
    proposal's concrete value (defaulting to the rationale's 3)."""
    try:
        to_value = int(tp.get("to_value", 3))
    except (TypeError, ValueError):
        return "retry-count proposal carries no integer target value"
    for n in nodes:
        if n.get("id") == target:
            n.setdefault("config", {})["max_retries"] = to_value
            return ""
    return f"no node {target!r} in the bound snapshot"


def _bound_source(proposal: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
    """The DAG snapshot a proposal is bound to, or a refusal.

    The binding check is the anti-retarget guard: a proposal whose recorded
    source hash no longer matches the current DAG content is refused (`stale`)
    rather than applied to whatever the DAG now holds — which is how verdict
    fallback used to mutate a different DAG than the one the proposal was
    authored against (#861).
    """
    import stores

    dag_id = proposal.get("dag_id", "")
    if not dag_id or dag_id not in stores.dags:
        return {}, STALE, "no DAG record to bind the proposal to"
    current = stores.dags[dag_id]
    source_hash = proposal.get("source_dag_hash", "")
    if not source_hash or snapshot_hash(current) != source_hash:
        return {}, STALE, "DAG changed since the proposal was created; refusing to re-target"
    return current, "", ""


def _mutated_snapshot(proposal: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
    """Build the candidate snapshot an accepted proposal would produce.

    Returns (candidate_snapshot, outcome, detail). The mutation is computed on
    a deep copy — the live DAG record is never touched here.
    """
    tp = proposal.get("topology_proposal") or {}
    kind = tp.get("kind", "") or proposal.get("kind", "")
    target = tp.get("target_node_id", "")

    # Kind vocabulary first: a proposal whose kind has no applicable mutation
    # can never be applied to *any* DAG state, so `unsupported` outranks the
    # binding check (a valueless model_swap on a missing DAG is unsupported,
    # not stale).
    if kind in ESCALATION_KINDS:
        return None, UNSUPPORTED, f"{kind!r} is an authorization request, never applied"
    if kind not in _NODE_FIELD_KINDS | _EDGE_FIELD_KINDS | _STRUCTURAL_KINDS | {KIND_RETRY_COUNT}:
        return None, UNSUPPORTED, f"kind {kind!r} has no applicable mutation"

    current, outcome, detail = _bound_source(proposal)
    if outcome:
        return None, outcome, detail

    candidate = copy.deepcopy(current)
    nodes = candidate.get("nodes", [])
    edges = candidate.get("edges", [])

    if kind in _NODE_FIELD_KINDS:
        detail = _mutate_node_fields(nodes, kind, target, tp)
    elif kind in _EDGE_FIELD_KINDS:
        detail = _mutate_edge_fields(edges, kind, target, tp)
    elif kind == KIND_RETRY_COUNT:
        detail = _mutate_retry_count(nodes, target, tp)
    else:
        nodes, edges = _apply_structural_mutation(candidate, nodes, edges, kind, target, tp)
        detail = ""

    if detail:
        return None, UNSUPPORTED, detail

    candidate["nodes"] = nodes
    candidate["edges"] = edges
    return candidate, BUILT, ""


def list_proposals(
    dag_id: str = "",
    *,
    decision: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List proposals, newest-first. Filter by dag_id and/or decision."""
    import stores

    items = list(stores.optimizer_proposals.values())
    if dag_id:
        items = [p for p in items if p.get("dag_id") == dag_id]
    if decision:
        items = [p for p in items if p.get("decision") == decision]
    items.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return items[: max(1, min(limit, 200))]
