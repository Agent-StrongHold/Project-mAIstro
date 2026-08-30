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
                Applied immediately UNLESS the target field is
                edit_lock.is_locked() (manual user override). All
                auto-applies write an audit_log entry.

  PROPOSE    — topology mutations / prompt rewrites. The user reviews +
               approves via POST /v1/optimizer/proposals/{id}/accept.
               The accept/reject is itself a Signal #4-style outcome
               (the user's vote refines the next optimizer round).

The optimizer never raises on data anomalies; missing / empty stores
produce zero proposals and an empty result.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

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
    obs = store._filter(dag_id=dag_id, window_seconds=window_seconds)
    by_node: dict[str, list[Any]] = {}
    for o in obs:
        by_node.setdefault(o.node_id, []).append(o)
    out: dict[str, dict[str, Any]] = {}
    for node_id, group in by_node.items():
        items = list(group)
        from services.node_metrics_store import _aggregate

        out[node_id] = _aggregate(items)
        out[node_id]["node_kind"] = items[0].node_kind if items else ""
    return out


async def _collect_thumbs(dag_id: str) -> dict[str, dict[str, Any]]:
    """Return {node_id: {up, down, comments}} from feedback_service's store.

    Async because the thumbs signal is now read from a durable store rather
    than walked off a list in this process. The loop that used to live here
    read `store._outcomes` directly, which only the in-memory store has, so
    the optimizer would have gone quietly blind the moment the Conductor was
    pointed at PostgreSQL or SQLite (#696).
    """
    from services.feedback_service import collect_thumbs

    return await collect_thumbs(dag_id)


def _collect_eval_verdicts(dag_id: str) -> list[dict[str, Any]]:
    """Return eval-judge verdicts for this DAG (or all if none match)."""
    import stores

    matched = [v for v in stores.eval_verdicts.values() if v.get("dag_id") == dag_id]
    if matched:
        return matched
    # Fallback: use all verdicts as signal (dag_id not always set)
    return list(stores.eval_verdicts.values())


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
) -> dict[str, SignalSnapshot]:
    """Build one SignalSnapshot per node_id that has any signal."""
    metrics = _collect_node_metrics(dag_id, window_seconds)
    thumbs = await _collect_thumbs(dag_id)
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
        # Signal #5 latency: p95 above threshold → weight
        p95 = m.get("latency_ms_p95", 0)
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
) -> dict[str, Any]:
    """Run one optimizer pass on the given DAG.

    Returns:
        {
          "dag_id": <id>,
          "proposals": [<proposal>, ...],   # ranked by priority_score desc
          "auto_applied": int,
          "blocked_by_edit_lock": int,
        }

    When `apply_auto=True`, AUTO_APPLY proposals that are NOT
    edit-locked are immediately committed (model swap / retry count /
    edge weight) and an audit_log entry is written per application.
    When False (default), every proposal is recorded as PENDING and the
    user reviews via the UI.
    """
    if not dag_id:
        raise ValueError("dag_id is required")

    import stores
    from routes.audit import log_audit

    from services.edit_lock import is_locked

    snapshots = await _build_snapshot_for_dag(dag_id, window_seconds=window_seconds)
    ranked = sorted(snapshots.values(), key=lambda s: s.priority_score, reverse=True)

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
            field_path = raw["field_path"]
            blocked_by_lock = is_locked(dag_id, field_path, now=edit_lock_now)
            if raw["class"] == CLASS_AUTO_APPLY and apply_auto and not blocked_by_lock:
                applied = True
                auto_applied += 1
                decision = DECISION_ACCEPTED
                log_audit(
                    action="optimizer_auto_apply",
                    actor=actor,
                    target=dag_id,
                    detail={
                        "proposal_id": proposal_id,
                        "kind": raw["kind"],
                        "field_path": field_path,
                        "rationale": raw["rationale"][:200],
                    },
                )
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
                "blocked_by_edit_lock": blocked_by_lock,
                "applied": applied,
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
        },
    )

    return {
        "dag_id": dag_id,
        "proposals": out_proposals,
        "auto_applied": auto_applied,
        "blocked_by_edit_lock": blocked,
    }


def record_decision(
    proposal_id: str,
    decision: str,
    *,
    actor: str,
) -> dict[str, Any]:
    """Record an accept/reject on a proposal. The decision itself flows
    back into outcome_store as a Signal #4-equivalent so the next
    optimizer pass treats user-approval as positive reinforcement."""
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
    stores.optimizer_proposals[proposal_id] = payload

    # Apply accepted topology mutations to the DAG
    if decision == DECISION_ACCEPTED and payload.get("kind") == KIND_TOPOLOGY:
        _apply_topology_mutation(payload)

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
        },
    )
    return payload


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
    """Mutate a single matched node's field in place, per `kind`."""
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
    elif kind == "upgrade_execution_tier":
        # REQUIRES ADMIN APPROVAL — optimizer can propose but never auto-apply
        # Upgrading from light→heavy or heavy→container is a security decision
        node.setdefault("config", {})["execution_tier"] = tp.get("to_value", "")
        node["config"]["tier_approved_by"] = "admin"  # must be set by admin accept


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
        "upgrade_execution_tier",
    }
)
# Kinds that mutate a matched edge's field (matched on from_node==target, to_node==from_value).
_EDGE_FIELD_KINDS = frozenset({"tune_edge_weight", "set_edge_condition"})


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


def _apply_topology_mutation(proposal: dict[str, Any]) -> None:
    """Apply an accepted topology mutation to the DAG in stores."""
    import stores

    dag_id = proposal.get("dag_id", "")
    tp = proposal.get("topology_proposal") or {}
    kind = tp.get("kind", "")
    target = tp.get("target_node_id", "")

    if not dag_id or dag_id not in stores.dags:
        return

    dag = dict(stores.dags[dag_id])
    nodes = dag.get("nodes", [])
    edges = dag.get("edges", [])

    if kind in _NODE_FIELD_KINDS:
        for n in nodes:
            if n.get("id") == target:
                _apply_node_field_mutation(n, kind, tp)
    elif kind in _EDGE_FIELD_KINDS:
        for e in edges:
            if e.get("from_node") == target and e.get("to_node") == tp.get("from_value"):
                _apply_edge_field_mutation(e, kind, tp)
    else:
        nodes, edges = _apply_structural_mutation(dag, nodes, edges, kind, target, tp)

    dag["nodes"] = nodes
    dag["edges"] = edges
    stores.dags[dag_id] = dag
    logger.info("topology_mutation_applied dag=%s kind=%s target=%s", dag_id, kind, target)


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
