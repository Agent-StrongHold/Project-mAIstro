"""Validation gate — measure a mutation before anything is built on it.

SkillOpt pattern: never accept a mutation without proving it improves score.

Flow:
  1. Measure the current DAG (variant A) — the incumbent
  2. Apply the proposed mutation → create variant B
  3. Run variant B on the same task
  4. Score variant B with the evaluator
  5. The proposal is validated only if B.score > A.score (strict improvement)

A measurement is **typed evidence** (#2501), never a bare number:

- a run that raises or times out, an evaluator that is missing, refuses (no
  Binding, billing), or returns a score without Run lineage is *unavailable*
  (ADR-083026-a91e: an unmeasured metric is absent, not zero);
- an unavailable incumbent means **nothing can be compared**, so nothing is
  validated. The historical gate scored a failed baseline as ``0.0``, which
  let every positive variant look like an improvement.

Every measurement carries its canonical lineage — the executed Run, the judge
Run, the judge Invocation, the evaluator version and the usage — because the
promotion contract that consumes it must be able to cite the Runs that
justify a promotion (SPEC-100126-a9c4 R4/R8).

Measurements are deduplicated **while in flight**: two callers that ask for
the same idempotent content under the same scope and acting user share one Run and one judge
call, so concurrent optimizer passes over one source version never pay for
the same evaluation twice. Nothing is cached after completion — a later pass
measures again (#854: one lucky sample must not become permanent evidence).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from services.dag_execution_scope import DagExecutionScope
from services.optimizer_candidates import snapshot_hash
from services.safe_projection import public_failure, public_failure_text

logger = logging.getLogger("hive.validation_gate")

#: A measurement that produced a score with complete lineage.
AVAILABLE = "available"
#: A measurement that produced no usable evidence. Its ``reason`` says which.
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ScoredRun:
    """One executed + evaluated DAG snapshot: typed evidence or a typed absence."""

    status: str
    score: float | None = None
    reason: str = ""
    #: The canonical Run that executed the snapshot.
    run_id: str = ""
    #: The canonical child Run the judge was recorded under.
    evaluation_run_id: str = ""
    #: The governed Invocation of the judge call.
    invocation_id: str = ""
    evaluator_version: str = ""
    usage: dict[str, Any] | None = None

    @property
    def available(self) -> bool:
        return self.status == AVAILABLE

    def lineage(self) -> dict[str, Any]:
        """The Run / Invocation / cost lineage, as a plain record for rows and audit."""
        return {
            "run_id": self.run_id,
            "evaluation_run_id": self.evaluation_run_id,
            "invocation_id": self.invocation_id,
            "evaluator_version": self.evaluator_version,
            "usage": dict(self.usage) if self.usage else None,
        }


def _unavailable(reason: str, *, run_id: str = "") -> ScoredRun:
    return ScoredRun(status=UNAVAILABLE, reason=reason, run_id=run_id)


# In-flight measurements keyed by (workspace, project, content hash). Entries
# live only as long as the measurement runs; see the module docstring.
_inflight: dict[tuple[str, str, str], asyncio.Task[ScoredRun]] = {}


async def _shared(
    key: tuple[str, str, str], measure: Callable[[], Awaitable[ScoredRun]]
) -> ScoredRun:
    """Await `measure()` once per key across every concurrent caller."""

    def _forget(done: asyncio.Task[ScoredRun]) -> None:
        if _inflight.get(key) is done:
            del _inflight[key]

    running = asyncio.get_running_loop()
    task = _inflight.get(key)
    if task is None or task.done() or task.get_loop() is not running:
        task = asyncio.ensure_future(measure())
        _inflight[key] = task
        task.add_done_callback(_forget)
    # One caller cancelling its own request must not cancel a measurement
    # another caller is still waiting on.
    return await asyncio.shield(task)


async def _measure(dag_data: dict[str, Any], *, scope: DagExecutionScope) -> ScoredRun:
    """Execute one snapshot and evaluate it; every failure is typed, never 0.0."""
    from services.benchmark_eval import evaluate_dag_run
    from services.graph_runner import execute_dag

    try:
        result = await execute_dag(copy.deepcopy(dag_data), scope=scope)
    except Exception as exc:
        logger.warning("validation_run_failed: %s", public_failure(exc))
        return _unavailable(f"execution failed: {public_failure(exc)}")
    run_id = str(result.get("run_id") or "")
    if result.get("status") != "completed":
        return _unavailable("execution did not complete", run_id=run_id)
    task = dag_data.get("description", dag_data.get("name", ""))
    try:
        score = await evaluate_dag_run(result, task)
    except Exception as exc:
        logger.warning("validation_score_failed: %s", public_failure(exc))
        return _unavailable(f"evaluator raised {public_failure(exc)}", run_id=run_id)
    if not isinstance(score, dict):
        return _unavailable("evaluator returned no score", run_id=run_id)
    if score.get("error"):
        kind = str(score.get("error_kind") or "evaluation")
        # The refusal's own text is bounded by the shared disclosure policy;
        # the full reason stays in the evaluator's log and Invocation record.
        return _unavailable(
            f"evaluator refused ({kind}): {public_failure_text(str(score['error']))}",
            run_id=run_id,
        )
    total = score.get("total")
    if isinstance(total, bool) or not isinstance(total, (int, float)) or not math.isfinite(total):
        return _unavailable("evaluator returned no numeric score", run_id=run_id)
    evaluation_run_id = str(score.get("evaluation_run_id") or "").strip()
    evaluator_version = str(score.get("evaluator_version") or "").strip()
    if not evaluation_run_id or not evaluator_version:
        return _unavailable(
            "evaluator returned a score without Run lineage "
            "(no evaluation_run_id / evaluator_version)",
            run_id=run_id,
        )
    usage = score.get("usage")
    return ScoredRun(
        status=AVAILABLE,
        score=float(total),
        run_id=run_id,
        evaluation_run_id=evaluation_run_id,
        invocation_id=str(score.get("invocation_id") or ""),
        evaluator_version=evaluator_version,
        usage=usage if isinstance(usage, dict) else None,
    )


async def score_variant(dag_data: dict[str, Any], *, scope: DagExecutionScope) -> ScoredRun:
    """Execute one DAG snapshot and evaluate its output.

    Keyed by content and principal: the same snapshot under the same scope
    and acting user is measured once while that measurement is in flight.
    The acting user is part of the key because execution authority is
    per-principal (host roles, Sentinel permission checks) — one user must
    never inherit another user's execution evidence.
    """
    key = (scope.workspace_id, scope.project_id, scope.user_id, snapshot_hash(dag_data))
    return await _shared(key, lambda: _measure(dag_data, scope=scope))


async def measure_baseline(dag_data: dict[str, Any], *, scope: DagExecutionScope) -> ScoredRun:
    """The incumbent's own measurement — variant A.

    Unavailable evidence here means the incumbent could not be judged; it is
    never read as "the incumbent scores zero".
    """
    return await score_variant(dag_data, scope=scope)


async def validate_proposal(
    dag_data: dict[str, Any],
    proposal: dict[str, Any],
    baseline_score: float,
    *,
    scope: DagExecutionScope,
) -> dict[str, Any]:
    """Test a proposed mutation against a measured baseline.

    Returns the proposal annotated with the verdict. An unavailable variant is
    `validated: False` with a typed reason, never a zero score that would read
    as "measured and bad".
    """
    # Create variant B by applying the mutation to a copy
    variant_b = copy.deepcopy(dag_data)
    _apply_mutation_to_dag(variant_b, proposal)

    measured = await score_variant(variant_b, scope=scope)
    if not measured.available:
        logger.warning(
            "validation_variant_unavailable proposal=%s reason=%s",
            proposal.get("kind"),
            measured.reason,
        )
        return {
            **proposal,
            "validated": False,
            "reason": f"Variant B unmeasured: {measured.reason}",
        }

    # Strict improvement gate
    total_b = float(measured.score or 0.0)
    improved = total_b > baseline_score
    logger.info(
        "validation_gate proposal=%s baseline=%.1f variant_b=%.1f improved=%s",
        proposal.get("kind"),
        baseline_score,
        total_b,
        improved,
    )

    return {
        **proposal,
        "validated": improved,
        "baseline_score": baseline_score,
        "variant_b_score": total_b,
        "improvement": total_b - baseline_score,
        "reason": f"Score {'improved' if improved else 'did not improve'}: {baseline_score} → {total_b}",
        "evaluation": measured.lineage(),
    }


def _apply_mutation_to_dag(dag: dict[str, Any], proposal: dict[str, Any]) -> None:
    """Apply a topology proposal to a DAG dict (in-place)."""
    tp = proposal.get("topology_proposal") or {}
    kind = tp.get("kind", "")
    target = tp.get("target_node_id", "")
    nodes = dag.get("nodes", [])
    edges = dag.get("edges", [])

    if kind == "rewrite_prompt":
        for n in nodes:
            if n.get("id") == target or n.get("role") == target or n.get("name") == target:
                n["prompt"] = tp.get("to_value", n.get("prompt", ""))
                break

    elif kind == "swap_model":
        for n in nodes:
            if n.get("id") == target or n.get("role") == target or n.get("name") == target:
                n["model"] = tp.get("to_value", n.get("model", ""))
                break

    elif kind == "add_node":
        from uuid import uuid4

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
        if target:
            edges.append({"id": str(uuid4())[:8], "from_node": target, "to_node": new_id})

    elif kind == "drop_node":
        dag["nodes"] = [n for n in nodes if n.get("id") != target and n.get("role") != target]
        dag["edges"] = [
            e for e in edges if e.get("from_node") != target and e.get("to_node") != target
        ]
        return

    dag["nodes"] = nodes
    dag["edges"] = edges


async def validate_proposals(
    dag_data: dict[str, Any],
    proposals: list[dict[str, Any]],
    baseline_score: float,
    *,
    scope: DagExecutionScope,
) -> list[dict[str, Any]]:
    """Validate every proposal and return them all, annotated, in order.

    Nothing is dropped (#2501): a proposal that did not improve stays visible
    with its verdict, so the caller's response, the persisted rows and the
    audit trail agree. Filtering the list here is what let an already-applied
    proposal vanish from the response that reported it applied.
    """
    return [await validate_proposal(dag_data, p, baseline_score, scope=scope) for p in proposals]


# Models to test when hill-climbing
CANDIDATE_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.5-flash",
    "gemini-3.5-pro",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5.1",
    "gpt-5.2",
    "gpt-5.4",
    "gpt-5.5",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "o4-mini",
]


# Parameters to sweep
PARAM_GRID = {
    "temperature": [0.0, 0.1, 0.3, 0.5, 0.7, 1.0],
    "top_p": [0.1, 0.5, 0.9, 1.0],
    "frequency_penalty": [0.0, 0.3, 0.5, 0.8],
    "presence_penalty": [0.0, 0.3, 0.6],
}


async def hill_climb_params(
    dag_data: dict[str, Any],
    baseline_score: float,
    *,
    scope: DagExecutionScope,
) -> list[dict[str, Any]]:
    """Test parameter variations, return any that beat baseline."""
    import asyncio

    async def test_param(param: str, value: float) -> dict[str, Any]:
        variant = copy.deepcopy(dag_data)
        for n in variant.get("nodes", []):
            n.setdefault("config", {})[param] = value
        measured = await score_variant(variant, scope=scope)
        if not measured.available:
            return {
                "validated": False,
                "param_tested": f"{param}={value}",
                "reason": f"Variant unmeasured: {measured.reason}",
            }
        total = float(measured.score or 0.0)
        improved = total > baseline_score
        logger.info("param_test %s=%s: score=%s improved=%s", param, value, total, improved)
        return {
            "kind": "topology_mutation",
            "validated": improved,
            "param_tested": f"{param}={value}",
            "baseline_score": baseline_score,
            "variant_b_score": total,
            "improvement": total - baseline_score,
            "rationale": f"Parameter {param}={value} {'improves' if improved else 'does not improve'} score",
            "evaluation": measured.lineage(),
            "topology_proposal": {
                "kind": f"change_{param}",
                "target_node_id": dag_data.get("nodes", [{}])[0].get("id", ""),
                "from_value": str(
                    dag_data.get("nodes", [{}])[0].get("config", {}).get(param, "default")
                ),
                "to_value": str(value),
                "expected_improvement": f"{param}={value} scored {total} vs baseline {baseline_score}",
            },
        }

    # Test a subset — don't test every combination, just each param independently
    tasks = []
    for param, values in PARAM_GRID.items():
        for value in values:
            tasks.append(test_param(param, value))

    all_results = await asyncio.gather(*tasks)
    # Find the knee in quality/cost curve — keep only variants above the bend
    passing = [r for r in all_results if r.get("variant_b_score", 0) > 0]
    if passing:
        passing = _filter_above_knee(passing)
    return [r for r in passing if r.get("validated")]


def _filter_above_knee(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only variants above the quality/cost knee.

    The knee is where marginal quality gain per unit cost drops sharply.
    Variants below the knee are expensive for minimal improvement.
    """
    if len(results) <= 2:
        return results

    # Estimate cost from model (rough $/1M tokens)
    MODEL_COST = {
        "gemini-3.1-flash-lite": 0.02,
        "gemini-3.5-flash": 0.15,
        "gemini-3.5-pro": 1.25,
        "gpt-4.1-nano": 0.05,
        "gpt-4.1-mini": 0.10,
        "gpt-5-nano": 0.08,
        "gpt-5-mini": 0.15,
        "gpt-5.1": 0.50,
        "gpt-5.2": 0.75,
        "gpt-5.4": 1.50,
        "gpt-5.5": 2.00,
        "claude-haiku-4-5": 0.25,
        "claude-sonnet-4-6": 1.50,
        "o4-mini": 0.30,
    }
    DEFAULT_COST = 0.20

    # Score each by quality/cost ratio
    for r in results:
        model = r.get("model_tested") or r.get("param_tested", "")
        cost = DEFAULT_COST
        for m, c in MODEL_COST.items():
            if m in model:
                cost = c
                break
        quality = float(r.get("variant_b_score", 0))
        r["_cost"] = cost
        r["_quality"] = quality
        r["_efficiency"] = quality / max(cost, 0.001)  # quality per dollar

    # Sort by efficiency (best bang for buck first)
    results.sort(key=lambda r: r["_efficiency"], reverse=True)

    # Find the knee: where efficiency drops by more than 50% from the best
    best_efficiency = results[0]["_efficiency"]
    knee_threshold = best_efficiency * 0.5
    above_knee = [r for r in results if r["_efficiency"] >= knee_threshold]

    logger.info(
        "knee_filter: %d/%d variants above knee (threshold=%.1f efficiency)",
        len(above_knee),
        len(results),
        knee_threshold,
    )
    return above_knee


async def hill_climb_models(
    dag_data: dict[str, Any],
    baseline_score: float,
    *,
    scope: DagExecutionScope,
) -> list[dict[str, Any]]:
    """Test all candidate models in parallel, return any that beat baseline."""
    import asyncio
    import time as _time

    current_model = dag_data.get("nodes", [{}])[0].get("model", "gemini-3.5-flash")

    async def test_model(model: str) -> dict[str, Any]:
        proposal = {
            "kind": "topology_mutation",
            "rationale": f"Testing model swap: {current_model} → {model}",
            "topology_proposal": {
                "kind": "swap_model",
                "target_node_id": dag_data.get("nodes", [{}])[0].get("id", ""),
                "from_value": current_model,
                "to_value": model,
                "expected_improvement": f"Model {model} may produce better output",
            },
        }
        _start = _time.monotonic()
        result = await validate_proposal(dag_data, proposal, baseline_score, scope=scope)
        _elapsed_ms = int((_time.monotonic() - _start) * 1000)
        result["model_tested"] = model
        result["latency_ms"] = _elapsed_ms
        logger.info(
            "model_test %s: score=%s latency=%dms improved=%s",
            model,
            result.get("variant_b_score"),
            _elapsed_ms,
            result.get("validated"),
        )
        return result

    # Run all model tests in parallel
    # Future: each test runs in its own Hyperlight micro-VM (hardware isolation, ~1ms startup)
    # Current: asyncio.gather (I/O-bound, GIL doesn't matter for HTTP calls)
    models_to_test = [m for m in CANDIDATE_MODELS if m != current_model]
    results = await asyncio.gather(*[test_model(m) for m in models_to_test])
    results = [r for r in results if "variant_b_score" in r]

    # Pareto-optimal selection: best quality/cost/latency composite
    MODEL_COST = {
        "gemini-3.1-flash-lite": 0.02,
        "gemini-3.5-flash": 0.15,
        "gemini-3.5-pro": 1.25,
        "gpt-4.1-nano": 0.05,
        "gpt-4.1-mini": 0.10,
        "gpt-5-nano": 0.08,
        "gpt-5-mini": 0.15,
        "gpt-5.1": 0.50,
        "gpt-5.2": 0.75,
        "gpt-5.4": 1.50,
        "gpt-5.5": 2.00,
        "claude-haiku-4-5": 0.25,
        "claude-sonnet-4-6": 1.50,
        "o4-mini": 0.30,
    }
    for r in results:
        score = float(r.get("variant_b_score", 0))
        model = r.get("model_tested", "")
        cost = MODEL_COST.get(model, 0.20)
        latency_s = r.get("latency_ms", 10000) / 1000.0

        # Per-DAG optimization weights — the meta-agent tunes these
        weights = dag_data.get("config", {}).get("optimization_weights", {})
        w_quality = weights.get("quality", 0.5)
        w_cost = weights.get("cost", 0.3)
        w_speed = weights.get("speed", 0.2)

        # Normalize each dimension to 0-1
        norm_quality = score / 50.0  # max possible score
        norm_cost = 1.0 - min(cost / 2.0, 1.0)  # cheaper = higher
        norm_speed = 1.0 - min(latency_s / 30.0, 1.0)  # faster = higher

        r["_composite"] = (w_quality * norm_quality) + (w_cost * norm_cost) + (w_speed * norm_speed)
        r["_cost"] = cost
        r["_quality"] = score
        r["_latency_ms"] = r.get("latency_ms", 0)

    if not results:
        return []
    results.sort(key=lambda r: r.get("_composite", 0), reverse=True)

    # Winner: beats baseline on quality OR same quality at lower cost OR same quality+cost but faster
    current_cost = MODEL_COST.get(current_model, 0.20)
    winners = []
    for r in results:
        q = r.get("variant_b_score", 0)
        c = r.get("_cost", 999)
        if q > baseline_score:
            r["validated"] = True
            r["rationale"] = (
                f"Better quality ({q} vs {baseline_score}) — {r.get('model_tested')} in {r.get('_latency_ms', 0)}ms"
            )
            winners.append(r)
        elif q >= baseline_score and c < current_cost:
            r["validated"] = True
            r["rationale"] = (
                f"Same quality, cheaper (${c} vs ${current_cost}) — {r.get('model_tested')} in {r.get('_latency_ms', 0)}ms"
            )
            winners.append(r)

    logger.info("pareto_models: %d tested, %d winners", len(results), len(winners))
    return winners
