from __future__ import annotations

from .types import FitnessComponents, PipelineGenome

# Tuned per-benchmark minimums. A genome scoring below any of these on a
# benchmark it actually ran cannot breed.
#
# `osworld` used to sit here at 0.15. It was removed because `run_osworld`
# raises `NotImplementedError` and is not registered in `PROXY_BENCHMARKS`, so
# the entry could never fire — a gate for a benchmark that cannot produce a
# score is decoration, and it made the list look more complete than it was.
_HARD_GATE_THRESHOLDS: dict[str, float] = {
    "proxy_ifeval": 0.25,
    "proxy_bfcl": 0.20,
    "proxy_swebench": 0.15,
    "proxy_tau_bench": 0.20,
    "proxy_gaia": 0.30,
    "proxy_ragas": 0.25,
    "proxy_terminalbench": 0.20,
    # The real tier reports under bare identifiers (`REAL_BENCHMARKS` in
    # benchmarks/__init__.py), not the `proxy_`-prefixed ones, and the gate keys
    # off `EvalResult.benchmark`. Without these two entries a real ifeval/bfcl
    # run would fall through to `_DEFAULT_GATE_FLOOR` (0.01) — nominally gated,
    # effectively ungated — which is the same fail-open shape this gate exists
    # to close. Same thresholds as their proxy counterparts.
    "ifeval": 0.25,
    "bfcl": 0.20,
}

# Floor applied to any benchmark that was scored but has no tuned threshold —
# `code_rsi`, `swebench_pro`, and anything a caller registers itself.
#
# This exists because the gate used to iterate `_HARD_GATE_THRESHOLDS` and check
# `if bench in scores`, which silently passed every benchmark NOT in that dict.
# The RSI loop scores exactly one benchmark, `code_rsi`, which was never in it —
# so the hard gate was inert for the entire self-improvement loop. `code_rsi`
# collapses to 0.0 when the fix is rejected or the test signal is stubbed
# (see `code_rsi.code_rsi_score`), which means a genome whose fix was rejected
# outright still bred, competing on cost/latency/diversity alone.
#
# 0.01 rather than a tuned value on purpose: with no data on the composite
# distribution, the only defensible universal claim is "a score of zero is a
# total failure and must not breed". Replace it with a real per-benchmark entry
# above once there is evidence for one — but fail closed in the meantime, since
# the alternative is the fail-open behaviour this replaces.
_DEFAULT_GATE_FLOOR = 0.01

_FITNESS_WEIGHTS = {
    "eval_score": 0.65,
    "cost_efficiency": 0.15,
    "latency_efficiency": 0.10,
    "diversity_bonus": 0.05,
    "elo_bonus": 0.05,
}


# Weight for a benchmark scored but outside the standard EvalWeights set (e.g.
# the code_rsi RSI benchmark), so a subset run still yields a real fitness.
_DEFAULT_BENCH_WEIGHT = 0.15


def _check_hard_gate(genome: PipelineGenome) -> tuple[bool, list[str]]:
    """Gate every benchmark the genome actually ran, fail-closed.

    Two properties have to hold together, and the previous implementation only
    had the first:

    1. **A subset run is not penalised for what it skipped.** A code_rsi-only RSI
       run must not fail because it has no ifeval score. So iterate the genome's
       *scores*, never the full threshold list.
    2. **Every scored benchmark is gated.** Iterating `_HARD_GATE_THRESHOLDS` and
       testing `if bench in scores` satisfied (1) but silently passed anything
       absent from that dict — including `code_rsi`, the only benchmark the RSI
       loop scores. Unlisted benchmarks now fall back to `_DEFAULT_GATE_FLOOR`
       instead of being waved through.
    """
    failures: list[str] = []
    scores = genome.eval_scores

    # A genome must have been evaluated on *something* to be gated meaningfully.
    if not scores:
        return False, ["no benchmarks evaluated"]

    for bench, score in sorted(scores.items()):
        tuned = _HARD_GATE_THRESHOLDS.get(bench)
        threshold = _DEFAULT_GATE_FLOOR if tuned is None else tuned
        if score < threshold:
            # Name which kind of threshold fired: a genome blocked by an
            # untuned default floor is a different conversation from one that
            # missed a benchmark's real minimum.
            kind = " (default floor — no tuned threshold)" if tuned is None else ""
            failures.append(f"{bench} score {score:.3f} below gate {threshold}{kind}")

    return len(failures) == 0, failures


def _weighted_eval_score(genome: PipelineGenome) -> float:
    scores = genome.eval_scores
    if not scores:
        return 0.0
    weights = genome.eval_weights
    total = 0.0
    total_weight = 0.0
    # Weight only the benchmarks that actually ran, renormalising over them, so a
    # subset run isn't penalised for the benchmarks it deliberately skipped. A
    # scored benchmark outside the standard EvalWeights set (code_rsi) gets a
    # default weight so it drives fitness rather than being silently dropped.
    for bench, score in scores.items():
        weight = getattr(weights, bench, None)
        if weight is None:
            weight = _DEFAULT_BENCH_WEIGHT
        total += weight * score
        total_weight += weight
    return total / total_weight if total_weight > 0 else 0.0


def _cost_efficiency(genome: PipelineGenome) -> float:
    cost: float = genome.harness_params.get("total_cost_usd", 0.0)
    if cost <= 0.0:
        return 1.0
    return 1.0 / (1.0 + cost)


def _latency_efficiency(genome: PipelineGenome) -> float:
    latency: float = genome.harness_params.get("avg_latency_seconds", 0.0)
    if latency <= 0.0:
        return 1.0
    return 1.0 / (1.0 + latency)


def _diversity_bonus(genome: PipelineGenome, population: list[PipelineGenome]) -> float:
    if len(population) < 2:
        return 0.0
    from .diversity import _euclidean, trait_vector

    v = trait_vector(genome)
    distances = []
    for other in population:
        if other.id != genome.id:
            distances.append(_euclidean(v, trait_vector(other)))
    if not distances:
        return 0.0
    avg_dist = sum(distances) / len(distances)
    return min(avg_dist / 5.0, 1.0)


def _elo_bonus(genome: PipelineGenome) -> float:
    avg_elo: float = genome.harness_params.get("avg_elo", 0.0)
    if avg_elo <= 0.0:
        return 0.0
    return min(max(0.0, (avg_elo - 1000.0) / 400.0), 1.0)


def compute_fitness(
    genome: PipelineGenome,
    population: list[PipelineGenome],
) -> FitnessComponents:
    passed, gate_failures = _check_hard_gate(genome)

    w_eval = _weighted_eval_score(genome)
    cost_eff = _cost_efficiency(genome)
    lat_eff = _latency_efficiency(genome)
    div_bonus = _diversity_bonus(genome, population)
    elo_bon = _elo_bonus(genome)

    if not passed:
        total = 0.0
    else:
        total = (
            w_eval * _FITNESS_WEIGHTS["eval_score"]
            + cost_eff * _FITNESS_WEIGHTS["cost_efficiency"]
            + lat_eff * _FITNESS_WEIGHTS["latency_efficiency"]
            + div_bonus * _FITNESS_WEIGHTS["diversity_bonus"]
            + elo_bon * _FITNESS_WEIGHTS["elo_bonus"]
        ) * 100.0

    return FitnessComponents(
        weighted_eval_score=w_eval,
        cost_efficiency=cost_eff,
        latency_efficiency=lat_eff,
        diversity_bonus=div_bonus,
        total=total,
        passed_hard_gate=passed,
        gate_failures=gate_failures,
    )
