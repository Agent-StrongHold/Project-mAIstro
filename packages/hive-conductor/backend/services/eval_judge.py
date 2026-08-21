"""Phase 5 — Signal #3: eval-judge as an INTERNAL maistro agent.

This is NOT a Claude Code subagent. It's a service that builds a
rubric-scoring prompt + sends it to the LiteLLM gateway via the same
`_build_llm_call` path every other fleet agent uses (graph_runner._
build_llm_call).

Scoring contract (the LLM is asked for JSON):

    {
      "score": 0-100,
      "rationale": "short paragraph",
      "topology_proposal": null | {
          "kind": "swap_node_kind" | "add_node" | "drop_node" | "tune_param",
          "target_node_id": "<node_id>",
          "from_value": "<old>",
          "to_value": "<new>",
          "expected_improvement": "short rationale"
      }
    }

The verdict is persisted to stores.eval_verdicts keyed by run_id. The
optimizer (Phase 6) reads these to drive auto-apply / propose-only
mutations, gated by edit_lock.is_locked() per the IRON rule.

External-call safety: every LLM/parsing failure produces a structured
verdict with status='error' rather than raising. The Daily Report path
+ the manual trigger both stay green even if eval-judge is misconfigured.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


_RUBRIC = (
    "You are eval-judge: a strict, evidence-based reviewer of an AI agent's "
    "DAG run. Score this run on a 0-100 scale where:\n"
    "  90-100: nailed it — high-signal output, all nodes succeeded, "
    "user-visible value delivered\n"
    "  70-89: good — minor inefficiencies but the output is correct + usable\n"
    "  50-69: marginal — output is partially useful; clear topology improvements exist\n"
    "  0-49:  poor — wrong, irrelevant, or actively misleading output\n"
    "\n"
    "Optionally propose ONE concrete topology mutation that would "
    "demonstrably improve a future run of this DAG. Topology proposals "
    "can: add a node, remove a node, reorder nodes, add/remove edges, "
    "swap a node's model, or rewrite a node's prompt.\n"
    "\n"
    "Reply with ONLY a JSON object matching this schema, no prose around it:\n"
    "{\n"
    '  "score": <int 0-100>,\n'
    '  "rationale": <string>,\n'
    '  "topology_proposal": null | {\n'
    '      "kind": "add_node" | "drop_node" | "reorder" | "add_edge" | "remove_edge" | "tune_edge_weight" | "set_edge_condition" | "swap_model" | "rewrite_prompt" | "change_schema" | "change_temperature" | "change_max_tokens" | "change_strategy" | "change_max_cycles" | "change_entry" | "rename_node" | "change_role",\n'
    '      "target_node_id": <string>,\n'
    '      "from_value": <string>,\n'
    '      "to_value": <string>,\n'
    '      "expected_improvement": <string>\n'
    "  }\n"
    "}"
)


def _build_evidence_payload(
    run_record: Any,
    feedback_outcomes: list[Any] | None = None,
) -> dict[str, Any]:
    """Pack a finished DurableRunRecord + optional user thumbs into the
    evidence dict that the LLM rubric prompt consumes."""
    if run_record is None:
        return {}

    node_records = getattr(run_record, "node_records", None) or []
    nodes_summary = []
    for nr in node_records:
        nodes_summary.append(
            {
                "node_id": str(getattr(nr, "node_id", "") or ""),
                "kind": str(getattr(nr, "kind", "") or ""),
                "phase": str(getattr(nr, "phase", "") or "").split(".")[-1],
                "latency_ms": int(getattr(nr, "latency_ms", 0) or 0),
                "tokens_in": int(getattr(nr, "tokens_in", 0) or 0),
                "tokens_out": int(getattr(nr, "tokens_out", 0) or 0),
                "error_code": getattr(nr, "error_code", None),
                "error_message": getattr(nr, "error_message", None),
            }
        )

    feedback_summary = []
    for fo in feedback_outcomes or []:
        if not getattr(fo, "thumb", "") or getattr(fo, "dag_run_id", "") != getattr(
            run_record, "run_id", ""
        ):
            continue
        feedback_summary.append(
            {
                "thumb": fo.thumb,
                "comment": fo.thumb_comment,
                "node_id": fo.node_id,
            }
        )

    return {
        "run_id": str(getattr(run_record, "run_id", "") or ""),
        "dag_id": str(getattr(run_record, "dag_id", "") or ""),
        "status": str(getattr(run_record, "status", "") or "").split(".")[-1],
        "node_records": nodes_summary,
        "user_feedback": feedback_summary,
    }


def _parse_verdict(raw: str) -> dict[str, Any]:
    """Extract a JSON verdict object from `raw`.

    The LLM SHOULD return JSON-only, but some models prepend prose; this
    helper strips ```json fences + leading/trailing text. Returns
    {"status": "error", "detail": ...} on any parse failure.
    """
    if not raw or not raw.strip():
        return {"status": "error", "detail": "eval-judge returned empty response"}

    # Strip code fences ```json … ```
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw

    # Try direct json.loads first.
    try:
        return json.loads(candidate)
    except (TypeError, ValueError):
        pass

    # Last-ditch: find the first {...} block.
    obj_match = re.search(r"(\{.*\})", candidate, re.DOTALL)
    if obj_match is None:
        return {
            "status": "error",
            "detail": "eval-judge response not parseable as JSON",
        }
    try:
        return json.loads(obj_match.group(1))
    except (TypeError, ValueError) as exc:
        return {
            "status": "error",
            "detail": f"eval-judge JSON parse failed: {type(exc).__name__}",
        }


def _validate_verdict(parsed: dict[str, Any]) -> dict[str, Any]:
    """Coerce + range-check the parsed verdict. Always returns a valid
    shape — out-of-range scores get clamped, missing fields filled."""
    if parsed.get("status") == "error":
        return parsed

    try:
        score = int(parsed.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))

    rationale = str(parsed.get("rationale") or "")
    proposal = parsed.get("topology_proposal")
    if proposal is not None and not isinstance(proposal, dict):
        proposal = None
    if isinstance(proposal, dict):
        # Strip unknown keys; keep only the contracted ones.
        allowed = {"kind", "target_node_id", "from_value", "to_value", "expected_improvement"}
        proposal = {k: proposal.get(k) for k in allowed if proposal.get(k) is not None}

    return {
        "score": score,
        "rationale": rationale,
        "topology_proposal": proposal,
        "status": "ok",
    }


async def score_run(
    run_record: Any,
    *,
    feedback_outcomes: list[Any] | None = None,
    llm_call: Callable[..., Awaitable[str]] | None = None,
    persist: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the eval-judge on a finished DurableRunRecord.

    Returns the verdict dict (with status='ok' or status='error') and
    optionally persists it to stores.eval_verdicts under the run_id key.

    Parameters
    ----------
    run_record : object with `.run_id`, `.dag_id`, `.status`, `.node_records`
    feedback_outcomes : optional list of Outcome rows from the thumbs API,
        already filtered to relevant outcomes
    llm_call : async callable accepting `messages=[...], model=...` and
        returning a string. If None, builds via graph_runner._build_llm_call.
    persist : if True, writes the verdict to stores.eval_verdicts
    now : test seam for the timestamp
    """
    if run_record is None:
        raise ValueError("run_record is required")

    if llm_call is None:
        # Import lazily so tests can override without the heavy settings hop.
        try:
            from services.graph_runner import _build_llm_call

            llm_call = _build_llm_call()
        except Exception as exc:
            logger.warning("eval_judge_llm_unavailable: %s", exc)
            verdict = {
                "status": "error",
                "detail": f"LLM client unavailable: {type(exc).__name__}",
            }
            if persist:
                _persist(run_record, verdict, now=now)
            return verdict

    evidence = _build_evidence_payload(run_record, feedback_outcomes)
    messages = [
        {"role": "system", "content": _RUBRIC},
        {"role": "user", "content": json.dumps(evidence, default=str)},
    ]
    try:
        raw = await llm_call(messages=messages, temperature=0.2)
    except Exception as exc:
        logger.warning("eval_judge_llm_call_failed: %s", exc)
        verdict = {
            "status": "error",
            "detail": f"LLM call raised: {type(exc).__name__}",
        }
        if persist:
            _persist(run_record, verdict, now=now)
        return verdict

    parsed = _parse_verdict(raw)
    verdict = _validate_verdict(parsed)
    if persist:
        _persist(run_record, verdict, now=now)
    return verdict


def _persist(run_record: Any, verdict: dict[str, Any], *, now: datetime | None = None) -> None:
    import stores

    run_id = str(getattr(run_record, "run_id", "") or "")
    if not run_id:
        return
    payload = dict(verdict)
    payload["run_id"] = run_id
    payload["dag_id"] = str(getattr(run_record, "dag_id", "") or "")
    payload["project_id"] = str(getattr(run_record, "project_id", "") or "")
    payload["scored_at"] = (now or datetime.now(UTC)).isoformat()
    stores.eval_verdicts[run_id] = payload


def get_verdict(run_id: str) -> dict[str, Any] | None:
    import stores

    return stores.eval_verdicts.get(run_id)
