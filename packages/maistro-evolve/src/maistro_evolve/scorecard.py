"""Transparent multi-signal fitness: gates + weighted, auditable scores.

Composes the fitness signals into one decision, but never as an opaque number.
Every category carries *how* it was measured so the whole score is auditable:

  - **calculated** — deterministic from a tool/metric (ruff violation count, a
    bandit severity weight). Rationale = the arithmetic.
  - **derived**    — an aggregate/normalisation of other measures (the code-
    quality composite, a benchmark delta). Rationale = the formula, expanded.
  - **judge**      — an LLM produced the score. Rationale = its reasoning and the
    ADRs/specs it cited.

Two-tier by design (see the fitness discussion): **gates** are pass/fail vetoes
— a failing candidate is rejected regardless of scores — and only survivors get
a **weighted score** for ranking. Weights live in `FitnessWeights` so they can
be tuned (eventually learned from which candidates the user actually keeps);
the default is capability-dominant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MeasureKind(StrEnum):
    CALCULATED = "calculated"
    DERIVED = "derived"
    JUDGE = "judge"


@dataclass
class SignalScore:
    name: str
    kind: MeasureKind
    score: float  # normalised 0..1
    weight: float
    rationale: str
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def contribution(self) -> float:
        return self.score * self.weight


@dataclass
class GateResult:
    name: str
    passed: bool
    reason: str
    # Optional raw numeric evidence behind the pass/fail (e.g. a judge's score) —
    # so a downstream reviewer can read the underlying confidence, not just the
    # boolean veto. Mirrors SignalScore.detail's existing convention.
    detail: dict[str, object] = field(default_factory=dict)


@dataclass
class FitnessWeights:
    """Score weights. Capability is the dominant overall axis; among the
    improvement-move signals the priority favours *substantive* work — adding a
    real test and strengthening assertions — over docstring/style churn.

    ``composite`` renormalises over the signals actually *present* on a candidate,
    so a signal's weight is only its pull *relative to the others that fired*. That
    is the lever behind ``new_test``: it is present (and large) only when a
    genuinely new, green, coverage-raising test was added, so its presence pulls a
    test-adding cycle's composite well above a docstring-only cycle (which lacks
    it). Tunable — the intent is to learn these from revealed preference (what the
    user keeps vs. edits/rejects). Weights need not sum to 1.
    """

    # THE MATURITY LADDER's top rewards (ADR-070126-6386 v3): finishing an
    # already-CONTRACTED spec AC (with a marked, passing test) is the single
    # highest-value move in the system; formalising a genuinely new idea into a
    # well-formed spec (backlog → contract) is deliberately just barely below
    # it — proposing new work never outranks finishing promised work.
    spec_completion: float = 0.45  # net-new @pytest.mark.ac claims, tests green
    spec_proposed: float = 0.40  # a new well-formed docs/specs/ contract (≥2 ACs)
    new_test: float = 0.30  # a genuinely new, green, coverage-raising test
    capability: float = 0.28  # benchmark skill gain (present only with a benchmark)
    assertion_strength: float = 0.20  # strengthened test assertions
    mutation_strength: float = 0.18  # diff-scoped mutants the changed tests kill
    red_green: float = 0.14  # test-first / bug-fix that drives code
    feature_judge: float = 0.14  # LLM impact judge for FEATURE (v2.0) work
    coverage: float = 0.10  # coverage delta (a new test raises it)
    architecture_fit: float = 0.10
    personalized_judge: float = 0.10
    perf: float = 0.10  # measured speedup (present only with a timing signal)
    code_quality: float = 0.04  # lowest — docstring/style; presence, not substance


@dataclass
class Scorecard:
    gates: list[GateResult] = field(default_factory=list)
    scores: list[SignalScore] = field(default_factory=list)

    @property
    def gates_passed(self) -> bool:
        return all(g.passed for g in self.gates)

    @property
    def composite(self) -> float:
        # A gate failure is a veto: the candidate is rejected, score is 0.
        if not self.gates_passed:
            return 0.0
        total_w = sum(s.weight for s in self.scores)
        if total_w == 0:
            return 0.0
        return round(sum(s.contribution for s in self.scores) / total_w, 4)

    @property
    def accepted(self) -> bool:
        return self.gates_passed

    def explain(self) -> str:
        lines: list[str] = []
        verdict = "ACCEPTED" if self.accepted else "REJECTED (failed a gate)"
        lines.append(f"Fitness: {verdict}   composite={self.composite}")
        lines.append("  Gates (pass/fail vetoes):")
        for g in self.gates:
            mark = "PASS" if g.passed else "FAIL"
            lines.append(f"    [{mark}] {g.name}: {g.reason}")
        lines.append("  Scores (weighted, only counted if all gates pass):")
        for s in sorted(self.scores, key=lambda x: x.contribution, reverse=True):
            lines.append(
                f"    {s.name} [{s.kind.value}]  score={s.score:.3f} "
                f"* weight={s.weight:.2f} = {s.contribution:.3f}"
            )
            lines.append(f"        rationale: {s.rationale}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Signal builders — turn each subsystem's raw output into an explained score.
# ---------------------------------------------------------------------------


def code_quality_signal(cq: object, weight: float) -> SignalScore:
    """Wrap a maistro_evolve.code_quality.CodeQualityScore (a *derived* measure)."""
    parts = []
    for name, val, raw in (
        ("pylint", getattr(cq, "pylint", None), getattr(cq, "pylint_rating", 0)),
        ("type_cov", getattr(cq, "type_coverage", None), getattr(cq, "type_coverage_pct", 0)),
        ("cognitive", getattr(cq, "cognitive", None), getattr(cq, "cognitive_avg", 0)),
        ("duplication", getattr(cq, "duplication", None), getattr(cq, "duplication_pct", 0)),
        ("docstrings", getattr(cq, "docstrings", None), getattr(cq, "docstring_pct", 0)),
        ("halstead", getattr(cq, "halstead", None), getattr(cq, "halstead_difficulty", 0)),
        ("radon_mi", getattr(cq, "radon_mi", None), getattr(cq, "maintainability", 0)),
        ("radon_cc", getattr(cq, "radon_cc", None), getattr(cq, "avg_complexity", 0)),
        ("dead_code", getattr(cq, "dead_code", None), getattr(cq, "dead_code_count", 0)),
        ("ruff", getattr(cq, "ruff", None), getattr(cq, "ruff_violations", 0)),
        ("bandit", getattr(cq, "bandit", None), getattr(cq, "bandit_issues", 0)),
        ("mypy", getattr(cq, "mypy", None), getattr(cq, "mypy_errors", 0)),
    ):
        if val is not None:
            parts.append(f"{name}={val:.2f}(raw {raw})")
    rationale = "composite of " + ", ".join(parts) if parts else "no tools available"
    return SignalScore(
        name="code_quality",
        kind=MeasureKind.DERIVED,
        score=float(getattr(cq, "composite", 0.0)),
        weight=weight,
        rationale=rationale,
        detail={"tools_missing": list(getattr(cq, "tools_missing", []))},
    )


def architecture_fit_signal(
    verdict: object, weight: float, *, candidate_side: str = "B"
) -> SignalScore:
    """Wrap an architecture_fit.ArchFitVerdict (a *judge* measure).

    The candidate scores 1.0 if the judge picks its side, 0.5 on a tie, else 0.0.
    """
    winner = str(getattr(verdict, "winner", "tie"))
    score = 1.0 if winner == candidate_side else (0.5 if winner == "tie" else 0.0)
    cited = getattr(verdict, "cited", []) or []
    rationale = f"judge winner={winner}; {getattr(verdict, 'rationale', '')}"
    if cited:
        rationale += f" [cited: {', '.join(cited)}]"
    return SignalScore(
        name="architecture_fit",
        kind=MeasureKind.JUDGE,
        score=score,
        weight=weight,
        rationale=rationale,
        detail={"winner": winner, "cited": list(cited)},
    )


def assertion_strength_signal(strength: object, weight: float) -> SignalScore:
    """Wrap an assertion_strength.AssertionStrength (a *calculated* AST measure)."""
    score = getattr(strength, "score", None)
    return SignalScore(
        name="assertion_strength",
        kind=MeasureKind.CALCULATED,
        score=float(score) if score is not None else 0.0,
        weight=weight,
        rationale=(
            f"{getattr(strength, 'n_tests', 0)} tests, "
            f"{getattr(strength, 'strong', 0)} strong / {getattr(strength, 'weak', 0)} weak checks"
        ),
    )


def capability_signal(
    baseline_score: float,
    candidate_score: float,
    weight: float,
    *,
    benchmark: str = "proxy_swebench",
) -> SignalScore:
    """Benchmark capability (a *derived* measure): candidate's absolute score,
    with the delta vs. baseline in the rationale."""
    delta = candidate_score - baseline_score
    sign = "+" if delta >= 0 else ""
    return SignalScore(
        name="capability",
        kind=MeasureKind.DERIVED,
        score=max(0.0, min(1.0, candidate_score)),
        weight=weight,
        rationale=(
            f"{benchmark}: candidate {candidate_score:.3f} vs baseline "
            f"{baseline_score:.3f} ({sign}{delta:.3f})"
        ),
        detail={"baseline": baseline_score, "candidate": candidate_score, "delta": delta},
    )


def judge_signal(name: str, score: float, weight: float, rationale: str) -> SignalScore:
    """A generic LLM-as-judge score (e.g. the personalized prefs/goals judge, or
    the ``feature_judge`` impact score for a FEATURE / v2.0 change)."""
    return SignalScore(
        name=name, kind=MeasureKind.JUDGE, score=score, weight=weight, rationale=rationale
    )


def perf_signal(baseline_seconds: float, candidate_seconds: float, weight: float) -> SignalScore:
    """Measured speedup (a *derived* measure) for a PERF change.

    Score is the fraction of total time the candidate saves: 0.5 at parity, →1.0
    as the candidate approaches instant, <0.5 if it regresses. Present only when a
    timing measurement is available, so it can't dilute non-perf candidates.
    """
    b = max(0.0, baseline_seconds)
    c = max(0.0, candidate_seconds)
    total = b + c
    score = 0.5 if total == 0 else max(0.0, min(1.0, b / total))
    delta = c - b
    sign = "+" if delta >= 0 else ""
    return SignalScore(
        name="perf",
        kind=MeasureKind.DERIVED,
        score=score,
        weight=weight,
        rationale=f"candidate {c:.3f}s vs baseline {b:.3f}s ({sign}{delta:.3f}s)",
        detail={"baseline_seconds": b, "candidate_seconds": c, "delta_seconds": delta},
    )


def calculated_gate(name: str, passed: bool, reason: str) -> GateResult:
    return GateResult(name=name, passed=passed, reason=reason)
