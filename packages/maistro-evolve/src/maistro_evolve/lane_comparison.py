"""Measured comparison: curriculum-enabled lane vs external-only evaluation.

The M4-D exit evidence (#24, SPEC-282) requires an actual *measured*
comparison — the bounded curriculum-enabled lane against the same external
evaluation without generated curriculum, reporting capability, cost and
failure results, **including no improvement**. This module is that
measurement, kept next to the lane it measures.

It is a harness, not a leaderboard. Capability comes from the genome's real
external evaluation evidence via :func:`maistro_evolve.fitness.compute_fitness`
under the population-owned objective; the curriculum lane adds only bounded
generation behind the protected gates (``curriculum.generate_curriculum``) and
never writes a score into ``genome.eval_scores`` — the shipped posture (SPEC-
282 reconciliation) is that practice signal stays inside ``Curriculum`` and
out of external evaluation. The report therefore states the external
capability delta honestly, zero difference included, and prices the lane in
the only currencies it actually spends: generation/solver/gate probes and
recorded refusals.

Every number in a :class:`LaneComparisonReport` is measured from the run that
produced it; the ``summary`` string is rendered from those same numbers, so a
report can be quoted without re-deriving anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from inspect import isawaitable
from typing import Any

from .curriculum import (
    GATES,
    AdmissionDecision,
    ChallengeDraft,
    Curriculum,
    generate_curriculum,
)
from .fitness import compute_fitness
from .objective import DEFAULT_OBJECTIVE, EvaluationObjective
from .types import PipelineGenome

__all__ = [
    "CURRICULUM_ENABLED_LANE",
    "EXTERNAL_ONLY_LANE",
    "LaneBudget",
    "LaneComparisonReport",
    "LaneMeasurement",
    "compare_lanes",
]

#: The control lane: the same external evaluation, no generated curriculum.
EXTERNAL_ONLY_LANE = "external-only"

#: The treatment lane: identical external evaluation plus the bounded
#: self-generated curriculum behind its protected validity gates.
CURRICULUM_ENABLED_LANE = "curriculum-enabled"


@dataclass(frozen=True)
class LaneBudget:
    """The bounded budgets of one curriculum-lane measurement.

    SPEC-282 requires generation to be budget-bounded: the curriculum lane
    spends exactly ``generation_rounds`` proposer calls, and every downstream
    probe count derives from what those rounds actually cost. There is no
    unbounded mode.
    """

    generation_rounds: int

    def __post_init__(self) -> None:
        if self.generation_rounds < 1:
            raise ValueError(
                f"generation_rounds must be >= 1, got {self.generation_rounds} — "
                "an unbudgeted curriculum lane is not a measurement, it is a "
                "leak"
            )


@dataclass(frozen=True)
class LaneMeasurement:
    """One lane's measured capability, cost and failure results.

    ``capability``/``fitness_total`` come from ``compute_fitness`` under the
    population-owned objective. ``cost_probes`` and ``failures`` name every
    unit of work the lane spent and every refusal it recorded — a lane that
    did nothing reports empty dicts, not flattering ones.
    """

    lane: str
    capability: float
    fitness_total: float
    passed_hard_gate: bool
    cost_probes: dict[str, int] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class LaneComparisonReport:
    """The measured comparison of the two lanes over identical external evidence.

    ``capability_delta`` is ``curriculum_enabled.capability -
    external_only.capability`` and ``capability_verdict`` names it in the
    report's only honest vocabulary — an external capability that did not move
    is reported as ``"no improvement"``, which is a *result*, not a failure of
    the harness. ``admission_yield`` is the fraction of the generation budget
    the protected gates admitted; ``curriculum_records`` carries each accepted
    challenge's full provenance record (generator/validator versions, content
    identity, validation evidence, run references). ``summary`` is the
    rendered text form of exactly these numbers.
    """

    external_only: LaneMeasurement
    curriculum_enabled: LaneMeasurement
    capability_delta: float
    capability_verdict: str
    admission_yield: float
    curriculum_records: tuple[dict[str, Any], ...] = ()
    summary: str = ""


async def _counted(
    probe_key: str,
    probes: dict[str, int],
    seam: Any,
    *args: Any,
) -> Any:
    """Count one seam call, then delegate — sync or async both supported."""
    probes[probe_key] += 1
    result = seam(*args)
    if isawaitable(result):
        result = await result
    return result


def _executed_probe_count(curriculum: Curriculum) -> int:
    """Gate probes actually executed, over every decision the run produced."""
    decisions: list[AdmissionDecision] = [i.validation for i in curriculum.items]
    decisions.extend(curriculum.rejected)
    return sum(1 for d in decisions for o in d.outcomes if o.executed)


def _refusal_counts(curriculum: Curriculum) -> dict[str, int]:
    """Refusals by gate, plus proposer failures, from one curriculum run."""
    failures: dict[str, int] = {}
    for decision in curriculum.rejected:
        for outcome in decision.outcomes:
            if not (outcome.executed and outcome.passed):
                key = f"refused_by/{outcome.gate}"
                failures[key] = failures.get(key, 0) + 1
    if curriculum.proposer_errors:
        failures["proposer_errors"] = len(curriculum.proposer_errors)
    return failures


def _verdict(delta: float) -> str:
    if delta > 0:
        return "improvement"
    if delta < 0:
        return "regression"
    return "no improvement"


def _render(report: LaneComparisonReport, generation_rounds: int) -> str:
    """Render the measured numbers; the summary and the fields cannot drift."""
    ext = report.external_only
    cur = report.curriculum_enabled
    cost_keys = sorted(set(ext.cost_probes) | set(cur.cost_probes))
    failure_keys = sorted(cur.failures)
    lines = [
        f"lane comparison over identical external evidence "
        f"(generation budget: {generation_rounds} rounds)",
        f"  external-only      : capability={ext.capability:.6f} "
        f"fitness_total={ext.fitness_total:.6f} gate_passed={ext.passed_hard_gate}",
        f"  curriculum-enabled : capability={cur.capability:.6f} "
        f"fitness_total={cur.fitness_total:.6f} gate_passed={cur.passed_hard_gate}",
        f"  capability_delta   : {report.capability_delta:+.6f} "
        f"({report.capability_verdict}) — external evaluation remains the "
        f"promotion gate",
        f"  admission_yield    : {report.admission_yield:.3f} of the "
        f"generation budget admitted by the protected gates "
        f"({'+'.join(GATES)})",
    ]
    lines.append("  cost_probes:")
    for key in cost_keys:
        lines.append(
            f"    {key}: external_only={ext.cost_probes.get(key, 0)} "
            f"curriculum_enabled={cur.cost_probes.get(key, 0)}"
        )
    if failure_keys:
        lines.append("  curriculum-lane failures:")
        for key in failure_keys:
            lines.append(f"    {key}: {cur.failures[key]}")
    else:
        lines.append("  curriculum-lane failures: none recorded")
    lines.append(
        f"  accepted challenges retained: {len(report.curriculum_records)} "
        "(each with generator/validator version, content identity, validation "
        "evidence and run references)"
    )
    return "\n".join(lines)


async def compare_lanes(
    genome: PipelineGenome,
    population: list[PipelineGenome],
    *,
    propose: Any,
    solver: Any,
    baseline_answer: str,
    budget: LaneBudget,
    objective: EvaluationObjective = DEFAULT_OBJECTIVE,
    generator_version: str | None = None,
) -> LaneComparisonReport:
    """Measure the curriculum-enabled lane against the external-only lane.

    Both lanes score the *same* genome evidence under the same objective; the
    curriculum lane additionally spends the bounded generation budget behind
    the protected gates. The curriculum lane never writes a score into
    ``genome.eval_scores``, so any capability delta is measured, not assumed
    away — and with the shipped posture it measures as zero even when the
    gates admitted practice material, which the report states plainly.
    """
    external_fitness = compute_fitness(genome, population, objective)
    external_evaluations = len(genome.eval_scores)
    external_lane = LaneMeasurement(
        lane=EXTERNAL_ONLY_LANE,
        capability=external_fitness.capability_score,
        fitness_total=external_fitness.total,
        passed_hard_gate=external_fitness.passed_hard_gate,
        cost_probes={"external_evaluations": external_evaluations},
    )

    probes = {"generator_proposals": 0, "solver_attempts": 0}

    async def counted_propose() -> ChallengeDraft:
        # The seam is deliberately Any-typed (sync or async, like the solver
        # gate in curriculum.py); the local annotation carries the contract
        # that generate_curriculum re-checks at runtime anyway.
        draft: ChallengeDraft = await _counted("generator_proposals", probes, propose)
        return draft

    async def counted_solver(draft: ChallengeDraft) -> str:
        answer: str = await _counted("solver_attempts", probes, solver, draft)
        return answer

    curriculum = await generate_curriculum(
        counted_propose,
        solver=counted_solver,
        baseline_answer=baseline_answer,
        rounds=budget.generation_rounds,
        generator_version=generator_version,
    )

    # Identical evidence in, so fitness is recomputed — not assumed — equal.
    # The practice signal stays inside `Curriculum` (reserved namespace); it
    # never reaches eval_scores through any shipped path, which is exactly the
    # fact this re-measurement makes observable.
    curriculum_fitness = compute_fitness(genome, population, objective)
    curriculum_lane = LaneMeasurement(
        lane=CURRICULUM_ENABLED_LANE,
        capability=curriculum_fitness.capability_score,
        fitness_total=curriculum_fitness.total,
        passed_hard_gate=curriculum_fitness.passed_hard_gate,
        cost_probes={
            "external_evaluations": external_evaluations,
            "generator_proposals": probes["generator_proposals"],
            "solver_attempts": probes["solver_attempts"],
            "gate_probes": _executed_probe_count(curriculum),
        },
        failures=_refusal_counts(curriculum),
    )

    delta = curriculum_lane.capability - external_lane.capability
    records = tuple(item.provenance_record() for item in curriculum.items)
    report = LaneComparisonReport(
        external_only=external_lane,
        curriculum_enabled=curriculum_lane,
        capability_delta=delta,
        capability_verdict=_verdict(delta),
        admission_yield=len(curriculum.items) / budget.generation_rounds,
        curriculum_records=records,
        summary="",
    )
    # The rendered summary is derived from the very fields above, so a report
    # can be quoted without trusting any separately maintained prose.
    return replace(report, summary=_render(report, budget.generation_rounds))
