"""The population-owned evaluation objective (#853).

A candidate must not control its own ruler. Before #853 the per-benchmark
weight vector lived on ``PipelineGenome.eval_weights``, was deep-copied
through every mutation operator (``mutate.mutate_eval_weights``) and mixed by
``crossover`` — so a genome could raise its own ``_weighted_eval_score``
without improving on a single benchmark, and two cycles' fitness numbers were
not comparable whenever the weights drifted.

This module is the correction: the objective is owned by the *campaign*
(the ``EvolutionCycle`` / whatever host drives the population), not by any
genome. It is

- **versioned** — ``EvaluationObjective.version`` is recorded on every
  ``FitnessComponents`` (``objective_version``) and folded into the evidence
  hash, so a score states exactly which ruler produced it;
- **immutable** — the model is pydantic-frozen and the weight dict is
  defensively copied at construction, so neither genomes nor scoring code can
  retune it in place;
- **the only source of scoring weights** — ``fitness._weighted_eval_score``
  reads ``objective.benchmark_weights`` and never ``genome.eval_weights``.
  ``PipelineGenome.eval_weights`` survives as an inert, legacy, persisted
  field: old serialized genomes still load, but the field cannot influence a
  score.

Bumping ``OBJECTIVE_VERSION`` is a governed act (it changes what every future
fitness number means), not a tuning knob a cycle may adjust per-candidate.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict

# Version of the default objective defined below. v1 is the implicit,
# genome-owned weight vector this module retires: same numeric weights
# (0.65/0.15/0.10/0.05/0.05 and the per-benchmark defaults on ``EvalWeights``),
# different ownership and missing-data semantics — which is exactly why it
# needs a distinct version string (see the stop condition on #853: weights are
# deliberately NOT retuned here, ownership and missing-data policy are).
OBJECTIVE_VERSION = "pop-owned-v2"

# Score a fitness component receives when its measurement was never taken.
# Pessimistic by design (#853): an unrecorded cost/latency/Elo observation
# must never out-score a measured one, and the only defensible credit for
# evidence that does not exist is zero. Configurable per objective so a
# campaign can make the policy explicit rather than implicit in ``1.0``-on-
# missing arithmetic.
MISSING_EVIDENCE_CREDIT = 0.0


class FitnessTermWeights(BaseModel):
    """Weights of the five fitness terms. Frozen: a genome cannot retune them.

    Carried verbatim from the pre-#853 ``fitness._FITNESS_WEIGHTS`` — the
    issue's stop condition forbids tuning weights before the ownership and
    missing-data semantics are corrected, and this module is that correction.
    """

    model_config = ConfigDict(frozen=True)

    eval_score: float = 0.65
    cost_efficiency: float = 0.15
    latency_efficiency: float = 0.10
    diversity_bonus: float = 0.05
    elo_bonus: float = 0.05


class EvaluationObjective(BaseModel):
    """The immutable, versioned ruler a population is measured with.

    Held by the campaign driver (``EvolutionCycle``) and passed into
    ``fitness.compute_fitness``; never carried on, copied into, or mutated
    with a genome.
    """

    model_config = ConfigDict(frozen=True)

    version: str
    # Per-benchmark weights for the capability aggregate. Field names match
    # ``EvalResult.benchmark`` / ``genome.eval_scores`` keys; a scored
    # benchmark missing from this mapping gets ``default_benchmark_weight``
    # (e.g. ``code_rsi``) so a subset run still yields a real score.
    benchmark_weights: Annotated[
        dict[str, float],
        # Defensive copy: a caller mutating the dict they passed in must not
        # retroactively retune an already-constructed objective. Expressed as
        # an anonymous ``BeforeValidator`` rather than a named
        # ``@field_validator`` method so the framework-registered callable
        # cannot masquerade as dead code to static scanners.
        BeforeValidator(dict),
    ]
    default_benchmark_weight: float
    fitness_term_weights: FitnessTermWeights
    missing_evidence_credit: float = MISSING_EVIDENCE_CREDIT

    def weight_for(self, benchmark: str) -> float:
        return self.benchmark_weights.get(benchmark, self.default_benchmark_weight)


# The default population-owned objective. Weights are the pre-#853 values
# (``EvalWeights`` defaults / ``fitness._FITNESS_WEIGHTS``), carried over
# verbatim per the issue's stop condition; only ownership, versioning and
# missing-data semantics change.
DEFAULT_OBJECTIVE = EvaluationObjective(
    version=OBJECTIVE_VERSION,
    benchmark_weights={
        "proxy_ifeval": 0.15,
        "proxy_bfcl": 0.15,
        "proxy_swebench": 0.20,
        "proxy_terminalbench": 0.10,
        "proxy_tau_bench": 0.15,
        "proxy_gaia": 0.10,
        "proxy_ragas": 0.10,
        # The real tier registers under bare identifiers (REAL_BENCHMARKS).
        "ifeval": 0.15,
        "bfcl": 0.15,
    },
    default_benchmark_weight=0.15,
    fitness_term_weights=FitnessTermWeights(),
    missing_evidence_credit=MISSING_EVIDENCE_CREDIT,
)
