from __future__ import annotations

import hashlib
import json
from typing import Any

from .curriculum import RESERVED_BENCHMARK_PREFIX
from .diversity import trait_vector
from .objective import DEFAULT_OBJECTIVE, EvaluationObjective
from .types import FitnessComponents, PipelineGenome

# Tuned per-benchmark minimums. A genome scoring below any of these on a
# benchmark it actually ran cannot breed.
#
# `osworld` used to sit here at 0.15. It was removed because `run_osworld`
# raises `NotImplementedError` and is not registered in `PROXY_BENCHMARKS`, so
# the entry could never fire — a gate for a benchmark that cannot produce a
# score is decoration, and it made the list look more complete than it was.
#
# Hard gates are *constraints*, not tradeable weights (#853): they live outside
# the ``EvaluationObjective`` weight vector on purpose, so re-weighting the
# objective can never rescue a candidate that failed a gate. Thresholds are
# module policy, versioned with the repo, not with a campaign's objective.
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


def hard_gate_thresholds() -> dict[str, float]:
    """Public, read-only view of the tuned per-benchmark gate thresholds.

    ``promotion.objective_version`` folds these into the objective digest, so
    the thresholds participate in the objective's immutable identity: changing
    a gate changes the objective version, which (per the #854 governed-promotion
    contract) invalidates evidence produced under the old one.
    """
    return dict(_HARD_GATE_THRESHOLDS)


# Semantic role of every fitness component (#853). The two `*_context` roles
# are population-level terms: they may reorder candidates within a bounded
# share of fitness, but they are *not* measured task quality and can never
# move `capability_score`. Tests pin the role split so a future term cannot
# silently join the measured set.
COMPONENT_ROLES: dict[str, str] = {
    "weighted_eval_score": "measured_task_quality",
    "capability_score": "measured_task_quality_gated",
    "cost_efficiency": "measured_efficiency",
    "latency_efficiency": "measured_efficiency",
    "diversity_bonus": "population_context",
    "elo_bonus": "head_to_head_context",
}

# Elo calibration for the head-to-head context term: a genome's average Elo is
# mapped from the [1000, 1400] band onto [0, 1]. Evidence-gated by battle
# count (see `_elo_bonus`): a genome that never battled has no relative
# standing to reward.
_ELO_FLOOR = 1000.0
_ELO_SPREAD = 400.0


def _curriculum_gate_failure(scores: dict[str, float]) -> str | None:
    """Name the curriculum-score violation, or ``None`` if there is none.

    M4-D (#24, SPEC-282): self-generated curriculum practice scores are not
    external evaluation. They cannot satisfy the hard gate, however high they
    are — a genome scored ONLY on its own generated challenges has no external
    evidence and must not breed.
    """
    reserved = sorted(b for b in scores if b.startswith(RESERVED_BENCHMARK_PREFIX))
    if not reserved:
        return None
    return (
        "self-generated curriculum scores ("
        + ", ".join(reserved)
        + ") are not external evaluation — they cannot satisfy the hard gate"
    )


def _external_gate_failures(external_scores: dict[str, float]) -> list[str]:
    """Gate every externally-scored benchmark against its threshold.

    **Every scored benchmark is gated.** Iterating `_HARD_GATE_THRESHOLDS` and
    testing `if bench in scores` silently passed anything absent from that
    dict — including `code_rsi`, the only benchmark the RSI loop scores.
    Unlisted benchmarks fall back to `_DEFAULT_GATE_FLOOR` instead of being
    waved through.
    """
    failures: list[str] = []
    for bench, score in sorted(external_scores.items()):
        tuned = _HARD_GATE_THRESHOLDS.get(bench)
        threshold = _DEFAULT_GATE_FLOOR if tuned is None else tuned
        if score < threshold:
            # Name which kind of threshold fired: a genome blocked by an
            # untuned default floor is a different conversation from one that
            # missed a benchmark's real minimum.
            kind = " (default floor — no tuned threshold)" if tuned is None else ""
            failures.append(f"{bench} score {score:.3f} below gate {threshold}{kind}")
    return failures


def _check_hard_gate(genome: PipelineGenome) -> tuple[bool, list[str]]:
    """Gate every benchmark the genome actually ran, fail-closed.

    Two properties have to hold together, and the previous implementation only
    had the first:

    1. **A subset run is not penalised for what it skipped.** A code_rsi-only RSI
       run must not fail because it has no ifeval score. So iterate the genome's
       *scores*, never the full threshold list.
    2. **Every scored benchmark is gated.** See `_external_gate_failures`:
       unlisted benchmarks fall back to `_DEFAULT_GATE_FLOOR` instead of being
       waved through.
    """
    failures: list[str] = []
    scores = genome.eval_scores

    curriculum_failure = _curriculum_gate_failure(scores)
    if curriculum_failure is not None:
        failures.append(curriculum_failure)

    external_scores = {
        b: s for b, s in scores.items() if not b.startswith(RESERVED_BENCHMARK_PREFIX)
    }

    # A genome must have been evaluated on *something* external to be gated
    # meaningfully. Curriculum-only scores are not that something, and the two
    # empty cases are named distinctly: no evidence at all vs no external
    # evidence (#24/SPEC-282 — self-generated scores are not external).
    if not external_scores:
        if scores:
            failures.append("no external benchmarks evaluated")
        else:
            failures.append("no benchmarks evaluated")
        return False, failures

    failures.extend(_external_gate_failures(external_scores))

    return len(failures) == 0, failures


def hard_gate_threshold(benchmark: str) -> float:
    """Public per-benchmark hard-gate threshold: the tuned minimum when one
    exists, else the fail-closed default floor.

    Exposed for the retrodiction prefilter, which must predict gate
    outcomes per benchmark without duplicating (and drifting from) this
    table. The gate itself stays in ``_check_hard_gate``.
    """
    tuned = _HARD_GATE_THRESHOLDS.get(benchmark)
    return _DEFAULT_GATE_FLOOR if tuned is None else tuned


def passes_hard_gate(genome: PipelineGenome) -> bool:
    """Public pass/fail read of the hard gate over a genome's current scores.

    Used by the retrodiction prefilter's false-negative accounting: a
    filtered candidate that later passes full evaluation counts against the
    filter. Delegates to ``_check_hard_gate`` — same gate, one definition.
    """
    passed, _ = _check_hard_gate(genome)
    return passed


def _weighted_eval_score(
    genome: PipelineGenome,
    objective: EvaluationObjective = DEFAULT_OBJECTIVE,
) -> float:
    """Measured task-quality aggregate, weighted by the population-owned
    objective (#853).

    The genome's own ``eval_weights`` field is deliberately **not** consulted —
    it was the defect where a genome carried (and mutated) the weights its own
    score was computed with. Weights come from the immutable campaign
    objective; a scored benchmark the objective does not name (``code_rsi``)
    gets ``objective.default_benchmark_weight`` so a subset run still yields a
    real score. Iteration is over ``sorted`` items so the float sum is
    independent of dict insertion order — the same evidence must recompute to
    the same number.
    """
    scores = genome.eval_scores
    if not scores:
        return 0.0
    total = 0.0
    total_weight = 0.0
    # Weight only the benchmarks that actually ran, renormalising over them, so a
    # subset run isn't penalised for the benchmarks it deliberately skipped.
    # Iteration is over ``sorted`` items so the float sum is independent of
    # dict insertion order.
    #
    # M4-D (#24, SPEC-282): scores under the reserved self-generated namespace
    # are excluded outright — they must not drive the weighted eval score, not
    # even through the objective's default weight for benchmarks it does not
    # name, and they must not shift the renormalisation denominator for the
    # benchmarks that legitimately ran.
    for bench, score in sorted(scores.items()):
        if bench.startswith(RESERVED_BENCHMARK_PREFIX):
            continue
        weight = objective.weight_for(bench)
        total += weight * score
        total_weight += weight
    return total / total_weight if total_weight > 0 else 0.0


def _cost_efficiency(genome: PipelineGenome) -> float | None:
    """Measured cost efficiency, or ``None`` when cost was never recorded.

    Missing-data policy (#853): absence of a measurement is not a zero-cost
    observation. Before #853 an unrecorded/zero cost returned 1.0 — full
    marks — so unrecorded work beat measured expensive work. ``None`` is
    scored pessimistically by ``compute_fitness`` via the objective's
    ``missing_evidence_credit``.
    """
    cost: Any = genome.harness_params.get("total_cost_usd")
    if cost is None:
        return None
    try:
        cost_num = float(cost)
    except (TypeError, ValueError):
        return None
    # A non-positive number is no evidence of a measured spend (the harness
    # never records a negative or free sample as 0.0-by-omission) — treat it as
    # unrecorded rather than as a perfect free run.
    if cost_num <= 0.0:
        return None
    return 1.0 / (1.0 + cost_num)


def _latency_efficiency(genome: PipelineGenome) -> float | None:
    """Measured latency efficiency, or ``None`` when latency was never
    recorded. Same missing-data policy as `_cost_efficiency` (#853)."""
    latency: Any = genome.harness_params.get("avg_latency_seconds")
    if latency is None:
        return None
    try:
        latency_num = float(latency)
    except (TypeError, ValueError):
        return None
    if latency_num <= 0.0:
        return None
    return 1.0 / (1.0 + latency_num)


def _diversity_bonus(genome: PipelineGenome, population: list[PipelineGenome]) -> float:
    if len(population) < 2:
        return 0.0
    from .diversity import _euclidean

    v = trait_vector(genome)
    distances = []
    for other in population:
        if other.id != genome.id:
            distances.append(_euclidean(v, trait_vector(other)))
    if not distances:
        return 0.0
    # Sort before summing: floating-point addition is order-sensitive, and the
    # population list order is caller-supplied. Sorting makes the bonus — and
    # therefore fitness — a deterministic function of the evidence multiset
    # (#853: same evidence, same score, across cycles).
    avg_dist = sum(sorted(distances)) / len(distances)
    return min(avg_dist / 5.0, 1.0)


def _elo_bonus(genome: PipelineGenome) -> float | None:
    """Head-to-head context term, or ``None`` without battle evidence.

    Before #853 any genome whose harness carried an ``avg_elo`` — including
    the default 1200 written for genomes that never battled — collected a
    0.5-strength bonus for mere existence, and Elo accumulated across cycles
    purely through re-battling. Now the term only fires on recorded battle
    evidence (``elo_battles`` > 0), so existence/re-battling without wins
    cannot mint fitness, and a never-battled genome scores ``None`` → the
    objective's pessimistic missing-evidence credit.
    """
    battles: Any = genome.harness_params.get("elo_battles", 0)
    try:
        battles_num = float(battles)
    except (TypeError, ValueError):
        return None
    if battles_num <= 0.0:
        return None
    avg_elo: Any = genome.harness_params.get("avg_elo", 0.0)
    try:
        avg_elo_num = float(avg_elo)
    except (TypeError, ValueError):
        return None
    if avg_elo_num <= 0.0:
        return None
    return min(max(0.0, (avg_elo_num - _ELO_FLOOR) / _ELO_SPREAD), 1.0)


def _evidence_hash(
    genome: PipelineGenome,
    population: list[PipelineGenome],
    objective: EvaluationObjective,
) -> str:
    """Stable digest of the exact inputs a fitness score was computed from
    (#853): measured scores, recorded cost/latency/Elo evidence, the genome's
    position-relevant traits, the population trait evidence diversity was
    computed against, and the objective version. Recomputing fitness from the
    same evidence must reproduce this hash — and therefore the score —
    bit-for-bit; any fitness movement across cycles is traceable to a hash
    change.
    """

    def _num(x: Any) -> float | None:
        if x is None:
            return None
        try:
            return round(float(x), 9)
        except (TypeError, ValueError):
            return None

    payload = {
        "objective": objective.model_dump(),
        "eval_scores": {k: _num(v) for k, v in sorted(genome.eval_scores.items())},
        "cost_evidence": _num(genome.harness_params.get("total_cost_usd")),
        "latency_evidence": _num(genome.harness_params.get("avg_latency_seconds")),
        "elo_evidence": _num(genome.harness_params.get("avg_elo")),
        "elo_battles_evidence": _num(genome.harness_params.get("elo_battles")),
        "self_traits": [round(v, 9) for v in trait_vector(genome)],
        # Population evidence diversity was computed against (other members
        # only, sorted by id so list order cannot change the hash).
        "population_traits": sorted(
            (
                gid,
                [round(v, 9) for v in trait_vector(g)],
            )
            for gid, g in ((o.id, o) for o in population)
            if gid != genome.id
        ),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compute_fitness(
    genome: PipelineGenome,
    population: list[PipelineGenome],
    objective: EvaluationObjective = DEFAULT_OBJECTIVE,
) -> FitnessComponents:
    """Score one genome against the population under the population-owned
    objective.

    Determinism contract (#853): the returned components are a pure function
    of (genome evidence, population evidence, objective). The same evidence
    recomputes the same ``total`` and the same ``evidence_hash`` in any cycle;
    fitness cannot drift upward on unchanged evidence.

    Gate semantics (#853): correctness gates are constraints, not weights.
    ``capability_score`` is the measured task quality **after** gating (0.0
    when gated out); Elo/diversity are bounded context terms with explicit
    roles (``COMPONENT_ROLES``) that can reorder candidates but can never move
    ``capability_score``, and a gate failure zeroes ``total`` regardless of
    any weight configuration or padded context evidence.
    """
    passed, gate_failures = _check_hard_gate(genome)

    w_eval = _weighted_eval_score(genome, objective)
    cost_eff = _cost_efficiency(genome)
    lat_eff = _latency_efficiency(genome)
    div_bonus = _diversity_bonus(genome, population)
    elo_bon = _elo_bonus(genome)

    fw = objective.fitness_term_weights
    credit = objective.missing_evidence_credit
    missing = [
        name
        for name, value in (
            ("cost_efficiency", cost_eff),
            ("latency_efficiency", lat_eff),
            ("elo_bonus", elo_bon),
        )
        if value is None
    ]

    # Measured task quality after the hard gates. Context terms never enter it.
    capability = w_eval if passed else 0.0

    if not passed:
        # Hard gates are non-tradeable: no Elo/diversity/cost/context gain can
        # compensate a failed correctness gate, under any objective weighting.
        total = 0.0
    else:
        total = (
            capability * fw.eval_score
            + (cost_eff if cost_eff is not None else credit) * fw.cost_efficiency
            + (lat_eff if lat_eff is not None else credit) * fw.latency_efficiency
            + div_bonus * fw.diversity_bonus
            + (elo_bon if elo_bon is not None else credit) * fw.elo_bonus
        ) * 100.0

    return FitnessComponents(
        weighted_eval_score=w_eval,
        capability_score=capability,
        cost_efficiency=cost_eff,
        latency_efficiency=lat_eff,
        diversity_bonus=div_bonus,
        elo_bonus=elo_bon,
        total=total,
        passed_hard_gate=passed,
        gate_failures=gate_failures,
        missing_evidence=missing,
        objective_version=objective.version,
        evidence_hash=_evidence_hash(genome, population, objective),
        component_roles=dict(COMPONENT_ROLES),
    )
