"""Validation gate — test mutations before proposing them.

SkillOpt pattern: never accept a mutation without proving it improves score.

Flow:
  1. Take current DAG (variant A) — we already have its score
  2. Apply proposed mutation → create variant B
  3. Run variant B on the same task
  4. Score variant B with eval-judge
  5. Only surface the proposal if B.score > A.score (strict improvement)
"""

from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger("hive.validation_gate")


async def validate_proposal(
    dag_data: dict[str, Any],
    proposal: dict[str, Any],
    baseline_score: float,
) -> dict[str, Any]:
    """Test a proposed mutation. Returns the proposal with validation results."""
    from services.benchmark_eval import evaluate_dag_run
    from services.graph_runner import execute_dag

    # Create variant B by applying the mutation to a copy
    variant_b = copy.deepcopy(dag_data)
    _apply_mutation_to_dag(variant_b, proposal)

    # Run variant B
    try:
        result_b = await execute_dag(variant_b)
    except Exception as e:
        logger.warning("validation_run_failed proposal=%s error=%s", proposal.get("kind"), e)
        return {**proposal, "validated": False, "reason": f"Variant B failed to run: {e}"}

    # Score variant B
    task = dag_data.get("description", dag_data.get("name", ""))
    try:
        score_b = await evaluate_dag_run(result_b, task)
        total_b = score_b.get("total", 0)
    except Exception as e:
        logger.warning("validation_score_failed: %s", e)
        return {**proposal, "validated": False, "reason": f"Scoring failed: {e}"}

    # Strict improvement gate
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


async def validate_and_filter_proposals(
    dag_data: dict[str, Any],
    proposals: list[dict[str, Any]],
    baseline_score: float,
) -> list[dict[str, Any]]:
    """Validate all proposals, return only those that strictly improve."""
    validated = []
    for p in proposals:
        result = await validate_proposal(dag_data, p, baseline_score)
        if result.get("validated"):
            validated.append(result)
        else:
            logger.info("proposal_rejected kind=%s reason=%s", p.get("kind"), result.get("reason"))
    return validated


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
) -> list[dict[str, Any]]:
    """Test parameter variations, return any that beat baseline."""
    import asyncio

    async def test_param(param: str, value: float) -> dict[str, Any]:
        variant = copy.deepcopy(dag_data)
        for n in variant.get("nodes", []):
            n.setdefault("config", {})[param] = value
        try:
            from services.benchmark_eval import evaluate_dag_run
            from services.graph_runner import execute_dag

            result = await execute_dag(variant)
            task = dag_data.get("description", dag_data.get("name", ""))
            score = await evaluate_dag_run(result, task)
            total = float(score.get("total", 0))
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
        except Exception as e:
            return {"validated": False, "param_tested": f"{param}={value}", "reason": str(e)}

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
) -> list[dict[str, Any]]:
    """Test all candidate models in parallel, return any that beat baseline."""
    import asyncio

    current_model = dag_data.get("nodes", [{}])[0].get("model", "gemini-3.5-flash")

    async def test_model(model: str) -> dict[str, Any]:
        import time as _time

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
        result = await validate_proposal(dag_data, proposal, baseline_score)
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
