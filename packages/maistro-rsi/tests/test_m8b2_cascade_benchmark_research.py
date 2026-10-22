"""M8-B2 research harness — cheap-model-first cascades with escalation.

Issue #915 (leaf of epic #900, initiative #879). Hypothesis under study:
routing a first pass through a cheaper model and escalating to a fixed strong
tier only when a *deterministic* confidence/evidence criterion fails can cut
inference spend materially without increasing task failure.

This module is a RESEARCH ARTIFACT, not product code. It implements the
measurement machinery the #915 benchmark procedure demands — tier cost and
latency accounting in ``ModelMetadata`` units (cents per 1k tokens, p50
milliseconds), a fixed strong-only baseline, deterministic escalation
policies over self-report / named-signal / historically-calibrated scores,
false-confidence and unnecessary-escalation accounting, provider-error
handling, and a threshold sweep for sensitivity analysis — so the real
experiment is reproducible the moment a paired (cheap, strong) outcome corpus
exists. The synthetic corpora below are deterministic fixtures for validating
the arithmetic and the policy mechanics; they are NOT experimental results
and must never be quoted as evidence about real models.

Relationship to #904 (M8-E): the escalation score deliberately accepts the
#904 signal families (self-report, historical outcome calibration, named
disagreement/verifier signals) as *inputs*. At this head the merged #904
harness is not yet in this tree (it lives on its research branch), so the
Beta-smoothed historical estimator here is a minimal, clearly-attributed
stand-in with the same leakage rule: it must be fitted on a prior period
only. Absent signals are loud errors, never fabricated defaults.

Trust boundary (the epic contract, enforced by construction):

- Every number produced here is ADVISORY EVIDENCE. Nothing reads or writes a
  Goal, a Run authority, a routing decision, or a Warden/HITL/delegation
  control. The module imports no maistro module at all, so it cannot become
  an authority by accident (M8 guardrails 1-2). Production adoption of any
  threshold found here routes to the canonical routing owner
  (``CostAwareRouter`` per the epic exit), never through this harness.
- Final success is judged by the observed strong-tier outcome on the same
  item — the fixed baseline is the only judge, matching the epic contract
  that quality claims compare against a fixed baseline.
- Records are frozen: measurements cannot be mutated into authorization
  after the fact.

The experiment record and terminal disposition live in
``docs/research/915-cheap-model-first-cascades.md``.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pytest

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-B2 output as
#: authorization. Routing authority remains CostAwareRouter (ADR-038);
#: human-escalation authority remains Warden/HITL (ADR-068).
ADVISORY_ONLY = True


# ---------------------------------------------------------------------------
# Cost model — ModelMetadata units (cents per 1k tokens, p50 milliseconds)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TierProfile:
    """Serving profile of one cascade tier.

    Units deliberately mirror ``ModelMetadata``
    (``packages/maistro-core/src/maistro/providers/types.py``): costs are
    cents per 1k input/output tokens, latency is p50 milliseconds — so a
    real experiment can populate profiles straight from the provider
    registry without unit conversion.
    """

    name: str
    cost_per_1k_input: float  # cents
    cost_per_1k_output: float  # cents
    latency_ms: int  # p50

    def __post_init__(self) -> None:
        if self.cost_per_1k_input < 0 or self.cost_per_1k_output < 0:
            raise ValueError(f"tier {self.name!r}: negative token cost")
        if self.latency_ms < 0:
            raise ValueError(f"tier {self.name!r}: negative latency")


def call_cost(tier: TierProfile, input_tokens: int, output_tokens: int) -> float:
    """Cost in cents of one completed call, in ModelMetadata units."""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("token counts must be non-negative")
    return (
        input_tokens / 1000.0 * tier.cost_per_1k_input
        + output_tokens / 1000.0 * tier.cost_per_1k_output
    )


# ---------------------------------------------------------------------------
# Corpus records — one judged workload item, both tiers observed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CascadeTask:
    """One workload item with the cheap tier's first-pass result and the
    strong tier's outcome on the same item.

    ``cheap_claimed`` is the cheap model's self-reported confidence in
    [0, 1] — a signal, never the truth. ``cheap_success`` is the observed
    outcome *if the cheap tier completed an answer*; it is ignored when
    ``cheap_provider_error`` is set (a failed call has no answer to judge).
    ``strong_success`` is the fixed baseline's observed outcome and is the
    only quality judge for this item. ``signals`` carries additional
    #904-family evidence, each in [0, 1] oriented so higher means predicted
    success. ``strong_output_tokens`` defaults to ``output_tokens`` (same
    answer rendered by the strong tier).
    """

    task_id: str
    context: str
    input_tokens: int
    output_tokens: int
    cheap_success: bool
    cheap_claimed: float
    strong_success: bool
    signals: Mapping[str, float] = field(default_factory=dict)
    cheap_provider_error: bool = False
    strong_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError(f"task {self.task_id!r}: negative token count")
        if self.strong_output_tokens is not None and self.strong_output_tokens < 0:
            raise ValueError(f"task {self.task_id!r}: negative strong output tokens")
        if not 0.0 <= self.cheap_claimed <= 1.0:
            raise ValueError(f"task {self.task_id!r}: claimed {self.cheap_claimed} outside [0, 1]")
        for name, value in self.signals.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"task {self.task_id!r}: signal {name!r}={value} outside [0, 1]")


# ---------------------------------------------------------------------------
# Historical calibration — minimal stand-in for the #904 estimator
# ---------------------------------------------------------------------------


def fit_historical(
    tasks: Sequence[CascadeTask],
    beta_prior: float = 1.0,
) -> tuple[Mapping[str, float], float]:
    """Beta-smoothed per-context cheap-tier success rates.

    STAND-IN for the #904 historical-calibration estimator (its harness is
    not merged at this head); same estimator shape, same leakage rule —
    the caller MUST fit on a prior period only. Provider-error items carry
    no outcome information and are excluded. Returns the per-context table
    and the global fallback rate for unseen contexts.
    """
    if beta_prior <= 0:
        raise ValueError("beta_prior must be positive")
    answered = [t for t in tasks if not t.cheap_provider_error]
    successes: dict[str, int] = {}
    totals: dict[str, int] = {}
    for t in answered:
        totals[t.context] = totals.get(t.context, 0) + 1
        if t.cheap_success:
            successes[t.context] = successes.get(t.context, 0) + 1
    global_rate = (sum(successes.values()) + beta_prior) / (len(answered) + 2.0 * beta_prior)
    table = {
        ctx: (successes.get(ctx, 0) + beta_prior) / (totals[ctx] + 2.0 * beta_prior)
        for ctx in totals
    }
    return table, global_rate


# ---------------------------------------------------------------------------
# Escalation policy — deterministic criterion, evidence-only
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EscalationPolicy:
    """Deterministic escalation criterion.

    ``score(task) < threshold`` escalates; the comparison is strict, so a
    task scoring exactly ``threshold`` stays with the cheap tier (the
    threshold is the minimum acceptable confidence). ``signal`` selects the
    score base: ``"self_report"`` uses the cheap tier's own claimed
    confidence; any other value names a per-task signal and raises loudly
    when a task lacks it (absent evidence is never fabricated). When
    ``historical`` is given, the base is blended with the context's fitted
    rate: ``blend_weight * base + (1 - blend_weight) * history``.
    """

    threshold: float
    signal: str = "self_report"
    historical: Mapping[str, float] | None = None
    historical_global: float = 0.5
    blend_weight: float = 0.5
    escalate_on_provider_error: bool = True

    def __post_init__(self) -> None:
        if self.threshold < 0:
            raise ValueError(
                "threshold must be non-negative (values above 1.0 mean "
                "'always escalate', the degenerate baseline point)"
            )
        if not 0.0 <= self.blend_weight <= 1.0:
            raise ValueError("blend_weight must be in [0, 1]")
        if not 0.0 <= self.historical_global <= 1.0:
            raise ValueError("historical_global must be in [0, 1]")


def escalation_score(task: CascadeTask, policy: EscalationPolicy) -> float:
    """Deterministic escalation score in [0, 1] for a completed cheap call."""
    if policy.signal == "self_report":
        base = task.cheap_claimed
    elif policy.signal in task.signals:
        base = task.signals[policy.signal]
    else:
        raise ValueError(
            f"task {task.task_id!r}: signal {policy.signal!r} absent — absent "
            "evidence is recorded as an error, never fabricated"
        )
    if policy.historical is None:
        return base
    rate = policy.historical.get(task.context, policy.historical_global)
    return policy.blend_weight * base + (1.0 - policy.blend_weight) * rate


# ---------------------------------------------------------------------------
# Measurement — baseline, per-task outcome, aggregate run
# ---------------------------------------------------------------------------


def _p95(latencies: Sequence[int]) -> int:
    """Nearest-rank 95th percentile of per-task latencies."""
    if not latencies:
        raise ValueError("p95 of an empty sequence is undefined")
    ordered = sorted(latencies)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


@dataclass(frozen=True)
class StrongBaseline:
    """Measured fixed strong-only run over a corpus. Evidence only."""

    n_tasks: int
    total_cost_cents: float
    mean_latency_ms: float
    p95_latency_ms: int
    success_rate: float


def run_strong_baseline(tasks: Sequence[CascadeTask], strong: TierProfile) -> StrongBaseline:
    """The fixed strong-model baseline: every item served by the strong tier."""
    if not tasks:
        raise ValueError("baseline over an empty corpus is undefined")
    total = 0.0
    successes = 0
    latencies: list[int] = []
    for t in tasks:
        out = t.strong_output_tokens if t.strong_output_tokens is not None else t.output_tokens
        total += call_cost(strong, t.input_tokens, out)
        latencies.append(strong.latency_ms)
        if t.strong_success:
            successes += 1
    n = len(tasks)
    return StrongBaseline(
        n_tasks=n,
        total_cost_cents=total,
        mean_latency_ms=sum(latencies) / n,
        p95_latency_ms=_p95(latencies),
        success_rate=successes / n,
    )


@dataclass(frozen=True)
class TaskMeasurement:
    """One item's cascade outcome. Evidence only — no actions."""

    task_id: str
    escalated: bool
    reason: str  # escalated | answered | provider_error | provider_error_unhandled
    provider_error: bool
    success: bool
    false_confidence: bool  # cheap answered (no error) and failed
    unnecessary_escalation: bool  # escalated although cheap would have succeeded
    cost_cents: float
    latency_ms: int


@dataclass(frozen=True)
class CascadeRun:
    """Aggregate cascade measurements over one corpus, with the same
    corpus's strong baseline attached for like-for-like comparison."""

    threshold: float
    n_tasks: int
    total_cost_cents: float
    mean_latency_ms: float
    p95_latency_ms: int
    escalation_rate: float
    provider_error_rate: float
    false_confidence_failures: int
    unnecessary_escalations: int
    success_rate: float
    baseline: StrongBaseline
    measurements: tuple[TaskMeasurement, ...] = ()

    @property
    def cost_reduction_cents(self) -> float:
        return self.baseline.total_cost_cents - self.total_cost_cents

    @property
    def cost_reduction_ratio(self) -> float:
        if self.baseline.total_cost_cents == 0:
            raise ValueError("baseline cost is zero; reduction ratio undefined")
        return self.cost_reduction_cents / self.baseline.total_cost_cents

    @property
    def quality_delta(self) -> float:
        return self.success_rate - self.baseline.success_rate

    @property
    def dominates_baseline(self) -> bool:
        """Equal-or-better quality at strictly lower cost. A measurement
        predicate over stated numbers, not a routing decision."""
        return self.success_rate >= self.baseline.success_rate and (
            self.total_cost_cents < self.baseline.total_cost_cents
        )


def run_cascade(
    tasks: Sequence[CascadeTask],
    cheap: TierProfile,
    strong: TierProfile,
    policy: EscalationPolicy,
) -> CascadeRun:
    """Run the corpus through cheap-first-then-escalate and measure it.

    Stated accounting rules: an escalated item pays the cheap call (a
    completed first pass is a sunk cost) *plus* the strong call; a
    provider-errored cheap call bills nothing (no completed usage) but pays
    its attempt latency; latency is sequential (cheap always, strong when
    escalated). Final quality is the escalated item's strong outcome or the
    answered item's cheap outcome.
    """
    if not tasks:
        raise ValueError("cascade over an empty corpus is undefined")
    baseline = run_strong_baseline(tasks, strong)
    measurements: list[TaskMeasurement] = []
    total = 0.0
    escalated = 0
    errored = 0
    false_confident = 0
    unnecessary = 0
    successes = 0
    latencies: list[int] = []
    for t in tasks:
        if t.cheap_provider_error:
            errored += 1
            if policy.escalate_on_provider_error:
                do_escalate, reason = True, "provider_error"
            else:
                do_escalate, reason = False, "provider_error_unhandled"
            cheap_cost = 0.0  # a failed call has no completed usage to bill
            cheap_answered_ok = False
        else:
            do_escalate = escalation_score(t, policy) < policy.threshold
            reason = "escalated" if do_escalate else "answered"
            cheap_cost = call_cost(cheap, t.input_tokens, t.output_tokens)
            cheap_answered_ok = t.cheap_success
        success = t.strong_success if do_escalate else cheap_answered_ok
        strong_out = (
            t.strong_output_tokens if t.strong_output_tokens is not None else t.output_tokens
        )
        cost = cheap_cost + (call_cost(strong, t.input_tokens, strong_out) if do_escalate else 0.0)
        latency = cheap.latency_ms + (strong.latency_ms if do_escalate else 0)
        false_conf = (not do_escalate) and (not t.cheap_provider_error) and (not success)
        unnec = do_escalate and (not t.cheap_provider_error) and t.cheap_success
        measurements.append(
            TaskMeasurement(
                task_id=t.task_id,
                escalated=do_escalate,
                reason=reason,
                provider_error=t.cheap_provider_error,
                success=success,
                false_confidence=false_conf,
                unnecessary_escalation=unnec,
                cost_cents=cost,
                latency_ms=latency,
            )
        )
        total += cost
        latencies.append(latency)
        escalated += int(do_escalate)
        false_confident += int(false_conf)
        unnecessary += int(unnec)
        successes += int(success)
    n = len(tasks)
    return CascadeRun(
        threshold=policy.threshold,
        n_tasks=n,
        total_cost_cents=total,
        mean_latency_ms=sum(latencies) / n,
        p95_latency_ms=_p95(latencies),
        escalation_rate=escalated / n,
        provider_error_rate=errored / n,
        false_confidence_failures=false_confident,
        unnecessary_escalations=unnecessary,
        success_rate=successes / n,
        baseline=baseline,
        measurements=tuple(measurements),
    )


# ---------------------------------------------------------------------------
# Threshold sensitivity — sweep and deterministic best-point selection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UtilityWeights:
    """Stated operator costs for ranking sweep points. Dimensionless
    reward/penalty per final outcome plus a weight on measured cents."""

    correct_reward: float = 1.0
    wrong_penalty: float = -1.0
    cost_per_cents: float = 0.0

    def __post_init__(self) -> None:
        if self.correct_reward < 0:
            raise ValueError("correct_reward must be non-negative")
        if self.wrong_penalty > 0:
            raise ValueError("wrong_penalty must be non-positive")
        if self.cost_per_cents < 0:
            raise ValueError("cost_per_cents must be non-negative")


@dataclass(frozen=True)
class ThresholdPoint:
    """One threshold of the sweep. Evidence only."""

    threshold: float
    run: CascadeRun
    utility: float | None = None


def sweep_threshold(
    tasks: Sequence[CascadeTask],
    cheap: TierProfile,
    strong: TierProfile,
    policy_template: EscalationPolicy,
    thresholds: Sequence[float],
    utility: UtilityWeights | None = None,
) -> tuple[ThresholdPoint, ...]:
    """Sweep the escalation threshold, ascending, one point per threshold.

    ``policy_template`` supplies the score configuration; only the
    threshold varies. Thresholds must be unique, finite (``math.inf`` is
    accepted as the documented always-escalate degenerate point) and
    non-negative.
    """
    if not thresholds:
        raise ValueError("threshold sweep over an empty grid is undefined")
    if len(set(thresholds)) != len(thresholds):
        raise ValueError("threshold grid must not repeat a threshold")
    for tau in thresholds:
        if tau < 0 or math.isnan(tau):
            raise ValueError(f"invalid threshold {tau!r}")
    points = []
    for tau in sorted(thresholds):
        run = run_cascade(tasks, cheap, strong, dataclasses.replace(policy_template, threshold=tau))
        util = None
        if utility is not None:
            n_success = run.success_rate * run.n_tasks
            n_fail = run.n_tasks - n_success
            util = (
                utility.correct_reward * n_success
                + utility.wrong_penalty * n_fail
                - utility.cost_per_cents * run.total_cost_cents
            )
        points.append(ThresholdPoint(threshold=tau, run=run, utility=util))
    return tuple(points)


def best_point(points: Sequence[ThresholdPoint]) -> ThresholdPoint:
    """Deterministic ranking: max utility (plain quality when unstated),
    then min cost, then min escalation rate, then min threshold."""
    if not points:
        raise ValueError("no sweep points to rank")

    def utility_of(p: ThresholdPoint) -> float:
        if p.utility is not None:
            return p.utility
        n_success = p.run.success_rate * p.run.n_tasks
        return n_success  # reward 1 per success, no other terms

    chosen = points[0]
    for candidate in points[1:]:
        if utility_of(candidate) > utility_of(chosen):
            chosen = candidate
            continue
        if utility_of(candidate) < utility_of(chosen):
            continue
        # utility tie: prefer lower cost, then lower escalation rate, then lower threshold
        challenger = (
            candidate.run.total_cost_cents,
            candidate.run.escalation_rate,
            candidate.threshold,
        )
        incumbent = (
            chosen.run.total_cost_cents,
            chosen.run.escalation_rate,
            chosen.threshold,
        )
        if challenger < incumbent:
            chosen = candidate
    return chosen


# ---------------------------------------------------------------------------
# Deterministic demonstration corpus (FIXTURE — not experimental evidence)
# ---------------------------------------------------------------------------


def m8b2_demo_corpus() -> list[CascadeTask]:
    """240-item two-regime fixture: easy items the cheap tier handles, hard
    items where the cheap tier fails while *over-reporting* confidence, and
    a verifier-style #904 signal that separates the hard failures the
    self-report cannot. Built from closed-form lattices (no RNG) so every
    endpoint is hand-checkable and every run is reproducible."""
    tasks: list[CascadeTask] = []
    for i in range(120):  # easy: cheap succeeds, claims high, signal high
        tasks.append(
            CascadeTask(
                task_id=f"easy-{i}",
                context="easy",
                input_tokens=800,
                output_tokens=400,
                cheap_success=True,
                cheap_claimed=0.86 + 0.08 * i / 119,
                strong_success=True,
                signals={"verifier_score": 0.9},
            )
        )
    for j in range(60):  # hard successes: cheap succeeds, signal high
        tasks.append(
            CascadeTask(
                task_id=f"hard-ok-{j}",
                context="hard",
                input_tokens=2000,
                output_tokens=800,
                cheap_success=True,
                cheap_claimed=0.80 + 0.14 * j / 59,
                strong_success=True,
                signals={"verifier_score": 0.8},
            )
        )
    for k in range(60):  # hard failures: cheap fails, OVER-claims, signal low
        tasks.append(
            CascadeTask(
                task_id=f"hard-bad-{k}",
                context="hard",
                input_tokens=2000,
                output_tokens=800,
                cheap_success=False,
                cheap_claimed=0.76 + 0.18 * k / 59,
                strong_success=True,
                signals={"verifier_score": 0.10 + 0.20 * k / 59},
            )
        )
    return tasks


CHEAP = TierProfile(
    name="cheap-fast", cost_per_1k_input=0.05, cost_per_1k_output=0.20, latency_ms=300
)
STRONG = TierProfile(
    name="strong-fixed", cost_per_1k_input=2.50, cost_per_1k_output=10.00, latency_ms=800
)


def corpus_a() -> list[CascadeTask]:
    """Three-item arithmetic-proof corpus with one overconfident cheap failure."""
    return [
        CascadeTask(
            task_id="t1",
            context="summarize",
            input_tokens=1000,
            output_tokens=1000,
            cheap_success=True,
            cheap_claimed=0.9,
            strong_success=True,
        ),
        CascadeTask(
            task_id="t2",
            context="sql",
            input_tokens=2000,
            output_tokens=1000,
            cheap_success=False,
            cheap_claimed=0.8,  # overconfident: claims above many thresholds yet fails
            strong_success=True,
        ),
        CascadeTask(
            task_id="t3",
            context="summarize",
            input_tokens=4000,
            output_tokens=2000,
            cheap_success=True,
            cheap_claimed=0.95,
            strong_success=True,
        ),
    ]


def corpus_b() -> list[CascadeTask]:
    """Provider-error corpus: one errored attempt, one easy win, one caught failure."""
    return [
        CascadeTask(
            task_id="p1",
            context="etl",
            input_tokens=1000,
            output_tokens=1000,
            cheap_success=False,
            cheap_claimed=0.9,
            strong_success=True,
            cheap_provider_error=True,  # claimed value is ignored on errors
        ),
        CascadeTask(
            task_id="p2",
            context="etl",
            input_tokens=1000,
            output_tokens=1000,
            cheap_success=True,
            cheap_claimed=0.95,
            strong_success=True,
        ),
        CascadeTask(
            task_id="p3",
            context="etl",
            input_tokens=1000,
            output_tokens=1000,
            cheap_success=False,
            cheap_claimed=0.4,
            strong_success=True,
        ),
    ]


# ---------------------------------------------------------------------------
# Tests: the deterministic escalation criterion
# ---------------------------------------------------------------------------


class TestEscalationCriterion:
    def test_self_report_score_is_the_claimed_value(self) -> None:
        task = corpus_a()[0]
        assert escalation_score(task, EscalationPolicy(threshold=0.85)) == 0.9

    def test_named_signal_used_and_absence_raises(self) -> None:
        task = corpus_a()[0]
        with_signal = dataclasses.replace(task, signals={"verifier_score": 0.2})
        policy = EscalationPolicy(threshold=0.85, signal="verifier_score")
        assert escalation_score(with_signal, policy) == 0.2
        with pytest.raises(ValueError, match="absent"):
            escalation_score(task, policy)  # no fabricated default for a missing signal

    def test_blend_combines_self_report_with_history(self) -> None:
        task = corpus_a()[1]  # claimed 0.8, context "sql"
        policy = EscalationPolicy(
            threshold=0.85,
            historical={"sql": 0.2},
            historical_global=0.5,
            blend_weight=0.5,
        )
        assert escalation_score(task, policy) == pytest.approx(0.5 * 0.8 + 0.5 * 0.2)

    def test_provider_error_escalates_regardless_of_score(self) -> None:
        run = run_cascade(corpus_b(), CHEAP, STRONG, EscalationPolicy(threshold=0.0))
        (p1,) = [m for m in run.measurements if m.task_id == "p1"]
        assert p1.escalated and p1.reason == "provider_error"
        # even the never-escalate threshold cannot keep an errored attempt

    def test_threshold_comparison_is_strict(self) -> None:
        # claimed exactly at threshold stays with the cheap tier
        run = run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=0.9))
        (t1,) = [m for m in run.measurements if m.task_id == "t1"]
        assert not t1.escalated and t1.reason == "answered"

    def test_claims_and_signals_are_range_validated(self) -> None:
        with pytest.raises(ValueError, match="outside \\[0, 1\\]"):
            CascadeTask("x", "c", 10, 10, True, 1.4, True)
        with pytest.raises(ValueError, match="outside \\[0, 1\\]"):
            CascadeTask("x", "c", 10, 10, True, 0.5, True, signals={"v": -0.1})


# ---------------------------------------------------------------------------
# Tests: cost, latency, and the fixed strong baseline (hand-checked)
# ---------------------------------------------------------------------------


class TestCostAccounting:
    def test_baseline_cost_is_strong_only(self) -> None:
        # t1: 1*2.5 + 1*10 = 12.5; t2: 2*2.5 + 1*10 = 15.0; t3: 4*2.5 + 2*10 = 30.0
        baseline = run_strong_baseline(corpus_a(), STRONG)
        assert baseline.total_cost_cents == pytest.approx(57.5)
        assert baseline.success_rate == 1.0

    def test_baseline_latency_and_p95(self) -> None:
        baseline = run_strong_baseline(corpus_a(), STRONG)
        assert baseline.mean_latency_ms == pytest.approx(800.0)
        assert baseline.p95_latency_ms == 800

    def test_cascade_cost_hand_value_at_threshold(self) -> None:
        # tau=0.85: t1 cheap (0.05+0.20=0.25), t2 escalated (0.30 + 15.0 = 15.30),
        # t3 cheap (4*0.05 + 2*0.20 = 0.60) -> 16.15 vs baseline 57.5
        run = run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=0.85))
        assert run.total_cost_cents == pytest.approx(16.15)
        assert run.escalation_rate == pytest.approx(1 / 3)
        assert run.success_rate == 1.0
        assert run.cost_reduction_cents == pytest.approx(41.35)
        assert run.cost_reduction_ratio == pytest.approx(41.35 / 57.5)

    def test_escalated_pays_both_tiers_answered_pays_one(self) -> None:
        run = run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=0.85))
        by_id = {m.task_id: m for m in run.measurements}
        assert by_id["t2"].cost_cents == pytest.approx(0.30 + 15.0)  # cheap + strong
        assert by_id["t2"].latency_ms == 300 + 800  # sequential tiers
        assert by_id["t1"].cost_cents == pytest.approx(0.25)
        assert by_id["t1"].latency_ms == 300

    def test_always_escalate_equals_baseline_plus_cheap_spend(self) -> None:
        # tau > 1 escalates every task: the strong bill is exactly the
        # baseline's, plus the sunk cheap spend (0.25 + 0.30 + 0.60 = 1.15).
        run = run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=1.5))
        assert run.total_cost_cents == pytest.approx(57.5 + 1.15)
        assert run.escalation_rate == 1.0
        assert run.success_rate == pytest.approx(run.baseline.success_rate)
        assert run.cost_reduction_cents < 0  # a cascade can lose money

    def test_provider_error_bills_nothing_but_pays_latency(self) -> None:
        run = run_cascade(corpus_b(), CHEAP, STRONG, EscalationPolicy(threshold=0.85))
        (p1,) = [m for m in run.measurements if m.task_id == "p1"]
        assert p1.cost_cents == pytest.approx(12.5)  # strong only; failed call unbilled
        assert p1.latency_ms == 300 + 800  # attempt latency still paid
        assert run.provider_error_rate == pytest.approx(1 / 3)

    def test_provider_error_left_unhandled_is_a_final_failure(self) -> None:
        policy = EscalationPolicy(threshold=0.85, escalate_on_provider_error=False)
        run = run_cascade(corpus_b(), CHEAP, STRONG, policy)
        (p1,) = [m for m in run.measurements if m.task_id == "p1"]
        assert not p1.escalated and p1.reason == "provider_error_unhandled"
        assert not p1.success and p1.cost_cents == pytest.approx(0.0)
        assert p1.latency_ms == 300
        assert run.success_rate == pytest.approx(2 / 3)  # the error became a failure


# ---------------------------------------------------------------------------
# Tests: policy outcomes — quality, false confidence, monotonicity
# ---------------------------------------------------------------------------


class TestPolicyOutcomes:
    def test_low_threshold_ships_the_overconfident_failure(self) -> None:
        # tau=0.7: t2's claim (0.8) clears it, so the hard failure ships.
        run = run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=0.7))
        assert run.false_confidence_failures == 1
        assert run.success_rate == pytest.approx(2 / 3)
        assert run.quality_delta == pytest.approx(-1 / 3)
        assert run.total_cost_cents == pytest.approx(0.25 + 0.30 + 0.60)

    def test_high_threshold_catches_it_below_baseline_cost(self) -> None:
        run = run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=0.85))
        assert run.false_confidence_failures == 0
        assert run.dominates_baseline  # equal quality (1.0), strictly cheaper

    def test_degenerate_zero_threshold_never_escalates(self) -> None:
        run = run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=0.0))
        assert run.escalation_rate == 0.0
        assert run.total_cost_cents == pytest.approx(1.15)
        assert run.success_rate == pytest.approx(2 / 3)

    def test_false_confidence_failures_non_increasing_in_threshold(self) -> None:
        grid = [0.0, 0.5, 0.7, 0.85, 1.0]
        runs = [
            run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=tau)) for tau in grid
        ]
        counts = [r.false_confidence_failures for r in runs]
        assert counts == sorted(counts, reverse=True)
        assert counts[0] == 1 and counts[-1] == 0

    def test_escalation_rate_non_decreasing_in_threshold(self) -> None:
        grid = [0.0, 0.5, 0.7, 0.85, 1.0]
        rates = [
            run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=tau)).escalation_rate
            for tau in grid
        ]
        assert rates == sorted(rates)
        assert rates[0] == 0.0 and rates[-1] == 1.0

    def test_final_quality_non_decreasing_when_strong_dominates(self) -> None:
        grid = [0.0, 0.5, 0.7, 0.85, 1.0]
        quality = [
            run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=tau)).success_rate
            for tau in grid
        ]
        assert quality == sorted(quality)

    def test_total_cost_non_decreasing_in_threshold(self) -> None:
        grid = [0.0, 0.5, 0.7, 0.85, 1.0]
        costs = [
            run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=tau)).total_cost_cents
            for tau in grid
        ]
        assert costs == sorted(costs)

    def test_unnecessary_escalations_are_counted(self) -> None:
        always = run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=1.5))
        assert always.unnecessary_escalations == 2  # t1 and t3: cheap would have won
        tuned = run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=0.85))
        assert tuned.unnecessary_escalations == 0  # t2 is escalated and cheap fails there


# ---------------------------------------------------------------------------
# Tests: #904-family signals as escalation evidence
# ---------------------------------------------------------------------------


class TestHistoricalAndSignals:
    def test_fit_historical_beta_smoothing_hand_value(self) -> None:
        # one success in four answered "sql" items, prior 1.0 -> (1+1)/(4+2) = 1/3
        tasks = [
            CascadeTask(f"s{i}", "sql", 100, 100, success, 0.9, True)
            for i, success in enumerate([True, False, False, False])
        ]
        table, global_rate = fit_historical(tasks)
        assert table["sql"] == pytest.approx(1 / 3)
        assert global_rate == pytest.approx(1 / 3)

    def test_provider_error_items_carry_no_outcome_information(self) -> None:
        errored = CascadeTask("e", "sql", 100, 100, False, 0.9, True, cheap_provider_error=True)
        tasks = [CascadeTask("a", "sql", 100, 100, True, 0.9, True), errored]
        table, _ = fit_historical(tasks)
        assert table["sql"] == pytest.approx((1 + 1) / (1 + 2))  # the error is excluded

    def test_historical_global_fallback_for_unseen_context(self) -> None:
        task = CascadeTask("u", "unseen", 100, 100, False, 0.9, True)
        policy = EscalationPolicy(
            threshold=0.85, historical={"sql": 0.2}, historical_global=0.5, blend_weight=0.5
        )
        assert escalation_score(task, policy) == pytest.approx(0.5 * 0.9 + 0.5 * 0.5)

    def test_signal_cascade_escalates_despite_high_self_report(self) -> None:
        # A hard failure that *claims* 0.95 but whose verifier signal says 0.1:
        # the self-report criterion keeps it cheap, the signal criterion escalates.
        task = CascadeTask(
            "v",
            "hard",
            1000,
            500,
            False,
            0.95,
            True,
            signals={"verifier_score": 0.1},
        )
        kept = run_cascade([task], CHEAP, STRONG, EscalationPolicy(threshold=0.85))
        escalated = run_cascade(
            [task], CHEAP, STRONG, EscalationPolicy(threshold=0.85, signal="verifier_score")
        )
        assert not kept.measurements[0].escalated and kept.success_rate == 0.0
        assert escalated.measurements[0].escalated and escalated.success_rate == 1.0


# ---------------------------------------------------------------------------
# Tests: threshold sensitivity sweep
# ---------------------------------------------------------------------------


class TestSensitivitySweep:
    def test_sweep_points_are_unique_sorted_and_aligned(self) -> None:
        points = sweep_threshold(
            corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=0.0), [1.0, 0.0, 0.7, 0.85]
        )
        assert [p.threshold for p in points] == [0.0, 0.7, 0.85, 1.0]
        for point in points:
            assert point.run.threshold == point.threshold
        with pytest.raises(ValueError, match="repeat"):
            sweep_threshold(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=0.0), [0.7, 0.7])

    def test_best_point_tie_break_is_deterministic(self) -> None:
        # 0.5 and 0.7 both answer everything: identical quality, cost,
        # escalation — the lower threshold wins the tie.
        points = sweep_threshold(
            corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=0.0), [0.7, 0.5]
        )
        assert best_point(points).threshold == 0.5

    def test_stated_costs_move_the_chosen_threshold(self) -> None:
        grid = [0.0, 0.7, 0.85, 1.0]
        template = EscalationPolicy(threshold=0.0)
        quality_first = best_point(
            sweep_threshold(corpus_a(), CHEAP, STRONG, template, grid, UtilityWeights())
        )
        cost_heavy = best_point(
            sweep_threshold(
                corpus_a(),
                CHEAP,
                STRONG,
                template,
                grid,
                UtilityWeights(correct_reward=1.0, wrong_penalty=-0.5, cost_per_cents=0.2),
            )
        )
        # Judging failures harshly: escalate the overconfident item (quality 1.0 wins).
        assert quality_first.threshold == 0.85
        # Treating a shipped failure as cheap relative to strong-token spend:
        # answer with the cheap tier everywhere (threshold 0.0 wins).
        assert cost_heavy.threshold == 0.0

    def test_utility_weights_are_validated(self) -> None:
        with pytest.raises(ValueError, match="wrong_penalty"):
            UtilityWeights(wrong_penalty=0.5)
        with pytest.raises(ValueError, match="cost_per_cents"):
            UtilityWeights(cost_per_cents=-1.0)


# ---------------------------------------------------------------------------
# Tests: the demonstration corpus (fixture semantics, not evidence)
# ---------------------------------------------------------------------------


class TestDemoCorpus:
    def test_demo_corpus_is_deterministic(self) -> None:
        assert m8b2_demo_corpus() == m8b2_demo_corpus()
        assert len(m8b2_demo_corpus()) == 240

    def test_signal_cascade_dominates_baseline(self) -> None:
        tasks = m8b2_demo_corpus()
        run = run_cascade(
            tasks,
            CHEAP,
            STRONG,
            EscalationPolicy(threshold=0.5, signal="verifier_score"),
        )
        # escalates exactly the 60 hard failures; quality matches, cost collapses
        assert run.escalation_rate == pytest.approx(0.25)
        assert run.success_rate == 1.0
        assert run.quality_delta == 0.0
        assert run.dominates_baseline
        assert run.cost_reduction_ratio == pytest.approx((2280.0 - 825.6) / 2280.0)

    def test_self_report_cascade_ships_failures_or_escalates_everything(self) -> None:
        tasks = m8b2_demo_corpus()
        shipped = run_cascade(tasks, CHEAP, STRONG, EscalationPolicy(threshold=0.9))
        # hard failures claim up to ~0.94; tau=0.9 leaves 14 of them uncaught
        assert shipped.false_confidence_failures == 14
        assert shipped.quality_delta < 0
        assert not shipped.dominates_baseline
        catch_all = run_cascade(tasks, CHEAP, STRONG, EscalationPolicy(threshold=0.97))
        # the only way self-report reaches baseline quality is escalating everything,
        # which pays the whole baseline bill plus every sunk cheap attempt
        assert catch_all.escalation_rate == 1.0
        assert catch_all.success_rate == 1.0
        signal_run = run_cascade(
            tasks, CHEAP, STRONG, EscalationPolicy(threshold=0.5, signal="verifier_score")
        )
        assert catch_all.total_cost_cents > signal_run.total_cost_cents
        assert not catch_all.dominates_baseline


# ---------------------------------------------------------------------------
# Tests: the evidence-only contract
# ---------------------------------------------------------------------------


class TestEvidenceOnlyContract:
    def test_harness_declares_itself_advisory(self) -> None:
        assert ADVISORY_ONLY is True

    def test_records_are_frozen(self) -> None:
        task = corpus_a()[0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            task.cheap_claimed = 0.1  # type: ignore[misc]
        run = run_cascade(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=0.85))
        with pytest.raises(dataclasses.FrozenInstanceError):
            run.success_rate = 1.0  # type: ignore[misc]
        baseline = run_strong_baseline(corpus_a(), STRONG)
        with pytest.raises(dataclasses.FrozenInstanceError):
            baseline.total_cost_cents = 0.0  # type: ignore[misc]

    def test_outputs_are_measurements_not_actions(self) -> None:
        for record in (CascadeRun, StrongBaseline, TaskMeasurement, ThresholdPoint):
            for f in dataclasses.fields(record):
                assert isinstance(f.type, str) or f.type in (int, float, bool, str, tuple)
            for verb in ("apply", "execute", "route", "escalate", "authorize"):
                assert not callable(getattr(record, verb, None))

    def test_module_imports_no_maistro_module(self) -> None:
        tree = ast.parse(inspect.getsource(sys.modules[__name__]))
        imported = {
            node.names[0].name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        }
        assert "maistro" not in imported

    def test_empty_corpus_is_rejected_not_silently_zero(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            run_strong_baseline([], STRONG)
        with pytest.raises(ValueError, match="empty"):
            run_cascade([], CHEAP, STRONG, EscalationPolicy(threshold=0.5))
        with pytest.raises(ValueError, match="empty"):
            sweep_threshold(corpus_a(), CHEAP, STRONG, EscalationPolicy(threshold=0.5), [])
        with pytest.raises(ValueError, match="no sweep points"):
            best_point([])
