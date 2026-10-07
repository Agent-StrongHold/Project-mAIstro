"""The weighted proven-scenario objective (M5-B, #108).

Before #108 the RSI fitness scalar was composed of priority-weighted *work
signals* (spec completion, coverage, code quality — ``scorecard.FitnessWeights``);
the product behaviour itself entered only indirectly. This module makes the
scenario corpus — the proven Gherkin acceptance scenarios a candidate must keep
green — the *initial scalar objective* of the RSI fitness, with the contract /
acceptance tests as the non-negotiable correctness oracle.

The contract, mirroring :mod:`maistro_evolve.objective` (the #853 ruler):

- **criticality-ordered weights** — every scenario carries a weight clamped
  into a half-open band keyed by its criticality tier (cosmetic [1, 2),
  product [2, 4), security [4, 8)). Because the bands do not overlap and the
  upper bounds are exclusive, ANY security scenario outweighs ANY product
  scenario, which outweighs ANY cosmetic scenario — structurally, not by
  tuning discipline (acceptance: high-criticality product/security scenarios
  carry higher weight than cosmetic work);
- **correctness and scalar recorded separately** — a
  :class:`ScenarioEvaluation` carries the :class:`CorrectnessResult` and the
  ``objective_score`` as sibling fields, and the raw criticality-weighted
  aggregate is preserved as ``raw_weighted_score`` for audit even when the
  scalar is zeroed;
- **a correctness failure scores zero / no promotion** — the objective scalar
  is 0.0 and ``promotable`` is False whenever the correctness oracle failed,
  however perfect the scenario evidence;
- **a regression cannot be compensated** — when any *proven* scenario (one
  with historical evidence, the same prior proven scenario set
  ``archive.proven_scenario_scores`` defends) falls below its proven score —
  or is not evaluated at all, including a proven id the ruler does not
  define — the scalar is 0.0 and ``promotable`` is False,
  even when the weighted aggregate itself rose. Unrelated gains move
  ``raw_weighted_score``; they never move the verdict;
- **immutable, versioned ruler** — the objective and every definition are
  pydantic-frozen, the version and a content digest are stamped on every
  evaluation, and the evaluation records themselves are frozen, so a score
  states exactly which ruler produced it and the ruler cannot be retuned
  under a candidate;
- **backlog utility stays out** — the aggregate folds ONLY scenario scores.
  The work signals (spec completion, coverage, quality) remain separate
  Scorecard signals, and correctness/security gates remain gates: a later,
  more general utility function may add terms, but it cannot trade them
  against the correctness oracle or a proven-scenario regression.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScenarioCriticality(StrEnum):
    """Product-criticality tier of one acceptance scenario.

    The tier — not a free-form number — is what makes the weight ordering a
    structural guarantee: weights are clamped into non-overlapping bands, so
    no amount of per-scenario tuning can outrank a security scenario with a
    cosmetic one.
    """

    SECURITY = "security"
    PRODUCT = "product"
    COSMETIC = "cosmetic"


# Half-open weight bands [low, high) per criticality tier, ordered lowest
# tier first. The exclusivity of each upper bound is the guarantee: a
# cosmetic scenario can reach 1.999… but never 2.0, so it can never reach
# even the weakest product weight; a product scenario can never reach the
# weakest security weight.
CRITICALITY_WEIGHT_BANDS: Mapping[ScenarioCriticality, tuple[float, float]] = {
    ScenarioCriticality.COSMETIC: (1.0, 2.0),
    ScenarioCriticality.PRODUCT: (2.0, 4.0),
    ScenarioCriticality.SECURITY: (4.0, 8.0),
}


class ScenarioDefinition(BaseModel):
    """One proven Gherkin scenario and its criticality-bound weight.

    ``weight`` is validated into the half-open band of its ``criticality``
    (see :data:`CRITICALITY_WEIGHT_BANDS`); the default for a tier is its band
    floor. Frozen: an objective's definitions cannot be retuned after
    construction.
    """

    model_config = ConfigDict(frozen=True)

    scenario_id: str = Field(min_length=1)
    # Human-readable name (e.g. the Gherkin `Scenario:` line); folded into the
    # objective digest so a retitle changes the ruler's identity.
    title: str = ""
    criticality: ScenarioCriticality
    weight: float

    # Pydantic dispatches mode="after" validators at model construction; the
    # method is never called by name (same reviewed suppression as
    # maistro_design.consistency, PR #1663).
    @model_validator(mode="after")  # noqa: V105
    def _weight_in_criticality_band(self) -> ScenarioDefinition:
        low, high = CRITICALITY_WEIGHT_BANDS[self.criticality]
        if not (low <= self.weight < high):
            raise ValueError(
                f"scenario {self.scenario_id!r}: {self.criticality.value} weight "
                f"{self.weight} outside its band [{low}, {high}) — weights are "
                "clamped per criticality so a lower tier can never outweigh a "
                "higher one"
            )
        return self


def _finite_score(scenario_id: str, score: float) -> float:
    """Reject non-finite measurements before any clamp or comparison.

    ``min(1.0, nan)`` is ``1.0`` and ``nan < x`` is ``False``, so an unguarded
    NaN/inf measurement would clamp to full credit and never count as a
    regression. A failed numerical measurement is malformed input, not a
    perfect score.
    """
    if not math.isfinite(score):
        raise ValueError(
            f"scenario {scenario_id} score must be finite, got {score!r} — "
            "a NaN/inf measurement cannot be clamped or compared"
        )
    return score


class ScenarioObjective(BaseModel):
    """The immutable, versioned scenario ruler a candidate is measured with.

    Held by the campaign/loop that evaluates candidates — never carried on,
    copied into, or mutated by one. ``version`` plus :meth:`digest` identify
    the ruler; every :class:`ScenarioEvaluation` stamps both.
    """

    model_config = ConfigDict(frozen=True)

    version: str = Field(min_length=1)
    scenarios: tuple[ScenarioDefinition, ...] = Field(min_length=1)
    # How far below a scenario's proven score a candidate may fall before it
    # counts as a regression (run-to-run noise allowance — same semantics as
    # archive.RetentionPolicy.regression_tolerance).
    regression_tolerance: float = Field(default=0.0, ge=0.0, le=1.0)

    # Pydantic-dispatched; never called by name (see _weight_in_criticality_band).
    @model_validator(mode="after")  # noqa: V105
    def _unique_scenario_ids(self) -> ScenarioObjective:
        ids = [s.scenario_id for s in self.scenarios]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(
                f"duplicate scenario ids in objective: {', '.join(duplicates)} — "
                "a scenario that appears twice would double its weight"
            )
        return self

    def weighted_score(self, scores: Mapping[str, float]) -> float:
        """Criticality-weighted aggregate over the scenarios that scored.

        Renormalises over the scenarios actually present in ``scores`` (a
        subset run is not penalised for what it skipped — same semantics as
        ``fitness._weighted_eval_score``), iterating in sorted id order so the
        float sum is independent of dict insertion order. Scores are clamped
        to [0, 1]: a scenario result is a pass-quality measure, not an
        unbounded reward.
        """
        total = 0.0
        total_weight = 0.0
        for definition in sorted(self.scenarios, key=lambda d: d.scenario_id):
            score = scores.get(definition.scenario_id)
            if score is None:
                continue
            clamped = max(0.0, min(1.0, _finite_score(definition.scenario_id, score)))
            total += definition.weight * clamped
            total_weight += definition.weight
        return total / total_weight if total_weight > 0 else 0.0

    def digest(self) -> str:
        """Stable content digest of the ruler: version, tolerance, and every
        definition (sorted by id so construction order cannot change it).

        Any change to a weight, tier, title, id, or tolerance changes the
        digest — and therefore invalidates comparison with evaluations stamped
        under the previous digest. Floats are serialized at full repr
        precision (json.dumps emits Python's shortest round-trip repr): no
        rounding, so near-boundary tolerances such as ``1e-10`` vs ``2e-10``
        — which can flip a regression verdict — always yield distinct
        digests.
        """
        payload = {
            "version": self.version,
            "regression_tolerance": self.regression_tolerance,
            "scenarios": [
                {
                    "scenario_id": d.scenario_id,
                    "title": d.title,
                    "criticality": d.criticality.value,
                    "weight": d.weight,
                }
                for d in sorted(self.scenarios, key=lambda d: d.scenario_id)
            ],
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class CorrectnessResult(BaseModel):
    """The non-negotiable correctness oracle's verdict for one evaluation.

    Recorded as a sibling of the scalar score, never folded into it: the
    tests either prove the candidate or they do not, and no scenario
    aggregate can speak for them. ``failures`` names what failed.
    """

    model_config = ConfigDict(frozen=True)

    passed: bool
    failures: tuple[str, ...] = ()


class ScenarioStatus(StrEnum):
    """Per-proven-scenario verdict, mirroring archive.RetentionOutcome."""

    PASS = "pass"
    REGRESSED = "regressed"
    NOT_EVALUATED = "not_evaluated"


class ScenarioOutcome(BaseModel):
    """One proven scenario's historical-vs-candidate comparison.

    ``criticality``/``weight`` are ``None`` when the proven id is absent from
    the ruler (an unmatched-proven outcome is blocking regardless of tier).
    """

    model_config = ConfigDict(frozen=True)

    scenario_id: str
    criticality: ScenarioCriticality | None = None
    weight: float | None = None
    proven_score: float
    candidate_score: float | None = None
    status: ScenarioStatus


class ScenarioEvaluation(BaseModel):
    """One candidate's evaluation under a scenario objective — the record.

    ``correctness_gate`` (the correctness gate) and ``objective_score`` (the
    scalar) are recorded separately; ``raw_weighted_score`` preserves what the pure
    aggregate would have been even when the gate or a regression zeroed the
    scalar, so the audit trail shows a compensation attempt rather than
    hiding it.
    """

    model_config = ConfigDict(frozen=True)

    objective_version: str
    objective_digest: str
    # The correctness oracle's verdict, recorded as a sibling of the scalar —
    # never folded into it.
    correctness_gate: CorrectnessResult
    raw_weighted_score: float
    # The scalar objective: the raw aggregate, or 0.0 when the correctness
    # gate failed or a proven scenario regressed/went unproven.
    objective_score: float
    per_scenario: tuple[ScenarioOutcome, ...] = ()
    regression_blocked: bool = False
    promotable: bool = False

    @property
    def regressed(self) -> list[str]:
        return [o.scenario_id for o in self.per_scenario if o.status == ScenarioStatus.REGRESSED]

    @property
    def not_evaluated(self) -> list[str]:
        return [
            o.scenario_id for o in self.per_scenario if o.status == ScenarioStatus.NOT_EVALUATED
        ]

    def summary(self) -> str:
        parts = [
            f"objective={self.objective_version}",
            f"digest={self.objective_digest}",
            f"correctness={'pass' if self.correctness_gate.passed else 'FAIL'}",
            f"score={self.objective_score:.4f}",
            f"raw={self.raw_weighted_score:.4f}",
            f"blocked={self.regression_blocked}",
        ]
        if self.correctness_gate.failures:
            parts.append("correctness: " + "; ".join(self.correctness_gate.failures))
        for outcome in self.per_scenario:
            if outcome.status == ScenarioStatus.REGRESSED:
                parts.append(
                    f"regressed {outcome.scenario_id}: candidate "
                    f"{outcome.candidate_score:.4f} < proven {outcome.proven_score:.4f}"
                )
        if self.not_evaluated:
            parts.append(f"not_evaluated={','.join(self.not_evaluated)}")
        return "; ".join(parts)


def evaluate_proven_scenarios(
    objective: ScenarioObjective,
    proven_scores: Mapping[str, float],
    candidate_scores: Mapping[str, float],
    correctness_oracle: CorrectnessResult,
) -> ScenarioEvaluation:
    """Evaluate ``candidate_scores`` against the prior proven scenario set.

    Only scenarios with historical evidence (``proven_scores``) are defended —
    they are the *proven* set, the same rows ``archive.proven_scenario_scores``
    derives. A proven scenario the candidate never scored is
    ``not_evaluated`` and blocks: a policy that let a challenger skip the
    scenarios it would have to defend would make the replay a paperwork
    exercise (the archive.RetentionGate ruling). A proven id absent from the
    ruler is likewise ``not_evaluated`` and blocks — omitting a proven
    scenario from the objective must not silently drop its evidence.

    Verdict semantics:
    - correctness failure → ``objective_score = 0.0``, ``promotable = False``
      (a correctness failure scores zero / no promotion);
    - any regressed or not-evaluated proven scenario → ``regression_blocked``,
      ``objective_score = 0.0``, ``promotable = False`` — even when the raw
      aggregate improved, so unrelated scalar gains cannot buy back a
      regression;
    - otherwise ``objective_score`` is the criticality-weighted aggregate and
      the candidate is promotable on this axis.
    """
    outcomes: list[ScenarioOutcome] = []
    ruler_ids = {definition.scenario_id for definition in objective.scenarios}
    for definition in sorted(objective.scenarios, key=lambda d: d.scenario_id):
        proven = proven_scores.get(definition.scenario_id)
        if proven is None:
            # No historical evidence for this scenario: nothing proven to
            # defend. It still participates in the weighted aggregate.
            continue
        candidate = candidate_scores.get(definition.scenario_id)
        if candidate is None:
            status = ScenarioStatus.NOT_EVALUATED
        elif (
            _finite_score(definition.scenario_id, candidate)
            < proven - objective.regression_tolerance
        ):
            status = ScenarioStatus.REGRESSED
        else:
            status = ScenarioStatus.PASS
        outcomes.append(
            ScenarioOutcome(
                scenario_id=definition.scenario_id,
                criticality=definition.criticality,
                weight=definition.weight,
                proven_score=proven,
                candidate_score=candidate,
                status=status,
            )
        )
    # Historical evidence the ruler does not cover: the candidate cannot score
    # these scenarios at all, so they are ``not_evaluated`` and block — same
    # ruling as a skipped proven scenario, never a silent pass.
    for scenario_id in sorted(set(proven_scores) - ruler_ids):
        outcomes.append(
            ScenarioOutcome(
                scenario_id=scenario_id,
                proven_score=proven_scores[scenario_id],
                candidate_score=None,
                status=ScenarioStatus.NOT_EVALUATED,
            )
        )

    regression_blocked = any(
        o.status in (ScenarioStatus.REGRESSED, ScenarioStatus.NOT_EVALUATED) for o in outcomes
    )
    raw = objective.weighted_score(candidate_scores)
    if not correctness_oracle.passed or regression_blocked:
        promotable = False
        objective_score = 0.0
    else:
        promotable = True
        objective_score = raw

    return ScenarioEvaluation(
        objective_version=objective.version,
        objective_digest=objective.digest(),
        correctness_gate=correctness_oracle,
        raw_weighted_score=raw,
        objective_score=objective_score,
        per_scenario=tuple(outcomes),
        regression_blocked=regression_blocked,
        promotable=promotable,
    )
