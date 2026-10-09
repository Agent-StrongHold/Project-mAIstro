"""M8-E3 research harness — heterogeneous-model disagreement and verifier signals.

Issue #932 (leaf of epic #904, initiative #879). Hypothesis under study:
disagreement between independently trained model families and independent
verifier/critic judgments predict failures better than repeated samples from
one model (#930) or per-context history alone (#931), and the two signal
families cover complementary error slices — disagreement cannot see errors
the families *share* (correlated errors), while a verifier can.

This module is a RESEARCH ARTIFACT, not product code. It implements the
measurements the #932 leaf demands — correlated-error overlap and joint error
rate across families, verifier confusion (false approval / false rejection),
a convex combination of success-oriented signals, panel-vs-self-consistency
cost and latency accounting, and a deterministic family-upgrade perturbation
for robustness re-measurement — and runs the required comparison *against the
merged #930/#931 machinery* by loading ``test_m8e_uncertainty_calibration_research``
from its file (pytest's global ``--import-mode=importlib`` addopt keeps test
directories off ``sys.path``, so a plain sibling import cannot resolve). The
comparison must score every signal family with one metric definition, or the
ranking is an artifact of two implementations.

Trust boundary (the epic's contract, enforced by construction):

- Every number produced here is ADVISORY EVIDENCE. Nothing reads or writes a
  Goal, a Run authority, a routing decision, or a Warden/HITL/delegation
  control; like the merged M8-E harness, this module imports nothing from
  ``maistro`` (asserted by a test), so it cannot become an authority by
  accident (M8 guardrails 1-2).
- Observed outcomes are the only judge. Per-family correctness is derived by
  comparing each family's answer to ``expected``; verifier verdicts and
  self-reported confidence are signals, never truth.
- Records are frozen: measurements cannot be mutated into authorization
  after the fact.

The experiment record and terminal disposition live in
``docs/research/904-uncertainty-calibration-abstention.md``. The synthetic
panel below is a deterministic fixture for validating the machinery and
demonstrating the comparison's structure — it is NOT experimental evidence
about any real model family, and must never be quoted as such.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import math
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import pytest


def _load_merged_harness() -> ModuleType:
    """Load the merged M8-E harness (#904) from its test-module file.

    pytest's global ``--import-mode=importlib`` addopt does not put test
    directories on ``sys.path``, so a plain sibling import cannot resolve;
    loading by path keeps exactly one metric definition per comparison — the
    #930/#931 baselines this leaf compares against are the merged harness's
    own implementations, not re-derivations. Registered under a private name
    so it never collides with pytest's own import of that file.
    """
    path = Path(__file__).resolve().parent / "test_m8e_uncertainty_calibration_research.py"
    spec = importlib.util.spec_from_file_location("_m8e_uncertainty_harness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: The merged M8-E harness module (#904): calibration metrics, variation
#: signals, and historical calibration — the #930/#931 baselines.
m8e = _load_merged_harness()

#: Shared evidence-only contract marker, taken from the merged M8-E harness
#: and asserted by a test so it cannot silently rot. Nothing outside these
#: research modules may treat M8-E output as authorization (ADR-068
#: authorization paths and Warden/HITL remain canonical).
ADVISORY_ONLY_E3 = m8e.ADVISORY_ONLY

if TYPE_CHECKING:
    # Type-only: the runtime module is loaded by path above (import-mode).
    from test_m8e_uncertainty_calibration_research import UncertaintyObservation

#: The primary family is the answer the system would actually ship; its
#: observed outcome is what every signal in this module is judged against.
PRIMARY = "alpha"


# ---------------------------------------------------------------------------
# Data model — one matched task through a heterogeneous panel
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PanelTask:
    """One matched task answered by several model families and judged once.

    ``expected`` is the ground-truth answer and the *only* judge: per-family
    correctness is derived by comparing each family's ``answer`` against it,
    never by asking a family or a verifier whether it was right. ``primary``
    names the family whose answer the system would ship — its self-report is
    ``claimed``, the verifiers judge its answer, and the repeated samples of
    the #930 baseline are draws from it. Verdicts, samples, and answers are
    evidence maps; absent evidence is omitted, never fabricated.
    """

    task_id: str
    context: str
    expected: str
    primary: str
    answers: Mapping[str, str]
    claimed: float
    verifiers: Mapping[str, bool] = field(default_factory=dict)
    single_family_samples: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.claimed <= 1.0:
            raise ValueError(f"claimed confidence {self.claimed} outside [0, 1]")
        if not self.answers:
            raise ValueError("panel task needs at least one family answer")
        if self.primary not in self.answers:
            raise ValueError(f"primary family {self.primary!r} did not answer")

    def family_correct(self, family: str) -> bool:
        """Observed correctness of one family against the ground-truth answer."""
        if family not in self.answers:
            raise KeyError(f"family {family!r} did not answer task {self.task_id!r}")
        return self.answers[family] == self.expected

    @property
    def primary_correct(self) -> bool:
        return self.family_correct(self.primary)


@dataclass(frozen=True)
class VerifierConfusion:
    """Verifier error accounting against observed outcomes (#932).

    ``false_approval_rate`` is the share of actually-wrong primary answers
    the verifier waved through; ``false_rejection_rate`` is the share of
    actually-correct answers it killed. Both are conditional on an outcome
    class existing — a verifier that never faces a wrong answer has an
    *unmeasured*, not zero, false-approval rate.
    """

    name: str
    approved: int
    rejected: int
    false_approvals: int
    false_rejections: int
    false_approval_rate: float
    false_rejection_rate: float


@dataclass(frozen=True)
class CallProfile:
    """Serving profile of one panel member.

    ``cost_per_call`` is currency per call and ``latency_ms`` is p50
    milliseconds — deliberately coarser than ``ModelMetadata``'s per-token
    units because a panel experiment buys whole calls; populate from the
    provider registry when running the real experiment.
    """

    name: str
    cost_per_call: float
    latency_ms: float


@dataclass(frozen=True)
class PanelCost:
    """Measured cost/latency of one signal-acquisition strategy. Evidence only."""

    label: str
    total_cost: float
    latency_ms: float


# ---------------------------------------------------------------------------
# Signals and projections (all oriented higher = predicted success)
# ---------------------------------------------------------------------------


def m8e3_panel_agreement(task: PanelTask, families: Sequence[str] | None = None) -> float:
    """1 - cross-family disagreement over the panel (the #932 signal)."""
    chosen = list(families) if families is not None else sorted(task.answers)
    return 1.0 - m8e.m8e_heterogeneous_disagreement({f: task.answers[f] for f in chosen})


def m8e3_observation(
    task: PanelTask, historical: Mapping[str, float] | None = None
) -> UncertaintyObservation:
    """Project a panel task onto the shared M8-E observation schema.

    Signals, each present only when its evidence exists:
    ``family_agree`` (#932 cross-family agreement), ``self_consistency``
    (#930 repeated-sample agreement), ``verifier_approve`` (fraction of
    verifiers approving the primary answer), and ``historical`` (a #931
    Beta-smoothed context rate, when the caller fitted one). The judged
    outcome is the primary family's observed result. A signal a caller wants
    to score but that is absent raises KeyError downstream — loudly, never
    as a fabricated default.
    """
    signals: dict[str, float] = {"family_agree": m8e3_panel_agreement(task)}
    if task.single_family_samples:
        signals["self_consistency"] = m8e.m8e_agreement(task.single_family_samples)
    if task.verifiers:
        signals["verifier_approve"] = sum(task.verifiers.values()) / len(task.verifiers)
    if historical is not None:
        if task.context not in historical:
            raise KeyError(f"no historical calibration for context {task.context!r}")
        signals["historical"] = historical[task.context]
    return m8e.UncertaintyObservation(task.context, task.claimed, task.primary_correct, signals)


def m8e3_combine(scores: Mapping[str, float], weights: Mapping[str, float]) -> float:
    """Convex combination of success-oriented signal scores.

    Every input must already be oriented higher = predicted success (a
    disagreement signal must be inverted before it arrives here), so the
    combined score keeps one unambiguous orientation.
    """
    if not scores:
        raise ValueError("combine needs at least one signal")
    if set(scores) != set(weights):
        raise ValueError("weights must name exactly the combined signals")
    if any(w < 0.0 for w in weights.values()):
        raise ValueError("weights must be non-negative")
    if not math.isclose(sum(weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("weights must sum to 1")
    if any(not 0.0 <= v <= 1.0 for v in scores.values()):
        raise ValueError("signal scores must be in [0, 1]")
    return sum(weights[name] * scores[name] for name in weights)


# ---------------------------------------------------------------------------
# Correlated-error accounting (#932: the failure mode disagreement cannot see)
# ---------------------------------------------------------------------------


def m8e3_error_overlap(tasks: Sequence[PanelTask], left: str, right: str) -> float:
    """P(both wrong) / P(either wrong): overlap of two families' error sets.

    1.0 means the families fail on exactly the same items — fully correlated
    errors, so the second family contributes no independent evidence and the
    disagreement signal is blind by construction. 0.0 means their errors
    never co-occur. Undefined — a loud error, not a zero — when neither
    family ever errs, because then panel independence is unmeasured rather
    than perfect.
    """
    if not tasks:
        raise ValueError("error overlap needs at least one judged task")
    both = 0
    either = 0
    for task in tasks:
        left_wrong = not task.family_correct(left)
        right_wrong = not task.family_correct(right)
        both += left_wrong and right_wrong
        either += left_wrong or right_wrong
    if either == 0:
        raise ValueError("error overlap is undefined when neither family ever errs")
    return both / either


def m8e3_joint_error_rate(tasks: Sequence[PanelTask], families: Sequence[str]) -> float:
    """P(every listed family is wrong on the same item).

    This is the error rate no selection among the panel can recover: if the
    joint rate is high, adding families does not buy accuracy, whatever the
    disagreement signal claims.
    """
    if not tasks:
        raise ValueError("joint error rate needs at least one judged task")
    if not families:
        raise ValueError("joint error rate needs at least one family")
    joint = 0
    for task in tasks:
        if all(not task.family_correct(f) for f in families):
            joint += 1
    return joint / len(tasks)


def m8e3_verifier_confusion(tasks: Sequence[PanelTask], name: str) -> VerifierConfusion:
    """Judge one verifier's verdicts against observed primary outcomes (#932)."""
    if not tasks:
        raise ValueError("verifier confusion needs at least one judged task")
    approved = 0
    rejected = 0
    false_approvals = 0
    false_rejections = 0
    wrong = 0
    correct = 0
    for task in tasks:
        if name not in task.verifiers:
            raise KeyError(f"verifier {name!r} did not judge task {task.task_id!r}")
        ok = task.primary_correct
        correct += ok
        wrong += not ok
        if task.verifiers[name]:
            approved += 1
            false_approvals += not ok
        else:
            rejected += 1
            false_rejections += ok
    if wrong == 0:
        raise ValueError("false-approval rate is undefined when no answer is wrong")
    if correct == 0:
        raise ValueError("false-rejection rate is undefined when no answer is correct")
    return VerifierConfusion(
        name=name,
        approved=approved,
        rejected=rejected,
        false_approvals=false_approvals,
        false_rejections=false_rejections,
        false_approval_rate=false_approvals / wrong,
        false_rejection_rate=false_rejections / correct,
    )


# ---------------------------------------------------------------------------
# Incremental cost/latency accounting (#932: what heterogeneity buys, at price)
# ---------------------------------------------------------------------------


def m8e3_self_consistency_cost(primary: CallProfile, n_samples: int) -> PanelCost:
    """#930 baseline strategy: n sequential samples of one family."""
    if n_samples < 1:
        raise ValueError("self-consistency needs at least one sample")
    if primary.cost_per_call < 0.0 or primary.latency_ms < 0.0:
        raise ValueError("profile costs and latencies must be non-negative")
    return PanelCost(
        label=f"self-consistency:{primary.name}x{n_samples}",
        total_cost=n_samples * primary.cost_per_call,
        latency_ms=n_samples * primary.latency_ms,
    )


def m8e3_panel_cost(
    panel: Sequence[CallProfile],
    verifiers: Sequence[CallProfile] = (),
    *,
    parallel: bool = True,
) -> PanelCost:
    """#932 strategy: one call per panel family plus the verifier pass.

    Panel families run concurrently (latency is the slowest family), while
    the verifiers run afterwards — they judge the produced answers. With
    ``parallel=False`` the whole panel is billed and latencyed sequentially,
    the pessimistic deployment.
    """
    if not panel:
        raise ValueError("panel needs at least one family profile")
    members = (*panel, *verifiers)
    if any(p.cost_per_call < 0.0 or p.latency_ms < 0.0 for p in members):
        raise ValueError("profile costs and latencies must be non-negative")
    total_cost = sum(p.cost_per_call for p in members)
    if parallel:
        panel_latency = max(p.latency_ms for p in panel)
    else:
        panel_latency = sum(p.latency_ms for p in panel)
    latency = panel_latency + sum(v.latency_ms for v in verifiers)
    names = [p.name for p in panel] + [f"verify:{v.name}" for v in verifiers]
    return PanelCost(
        label="panel[" + ",".join(names) + "]", total_cost=total_cost, latency_ms=latency
    )


def m8e3_incremental_cost_ratio(candidate: PanelCost, baseline: PanelCost) -> float:
    """Candidate strategy cost as a multiple of the baseline strategy cost."""
    if baseline.total_cost <= 0.0:
        raise ValueError("baseline cost must be positive to measure incrementality")
    return candidate.total_cost / baseline.total_cost


# ---------------------------------------------------------------------------
# Model-upgrade robustness (#932: re-measure, never carry a threshold across)
# ---------------------------------------------------------------------------


def m8e3_apply_family_upgrade(
    tasks: Sequence[PanelTask],
    family: str,
    fix_fraction: float,
    rng: random.Random,
) -> list[PanelTask]:
    """Simulate upgrading one family: a fraction of its errors become correct.

    Returns *new* tasks; every other family's answers, the expected answers,
    and the primary outcome are untouched, so callers can re-measure error
    overlap, joint error rate, and signal discrimination after the upgrade —
    the leaf's robustness requirement. Verifier verdicts and repeated
    samples refer to the *pre-upgrade* answers (a real experiment re-runs
    them; that re-run is part of the upgrade's cost). Deterministic under
    the seeded rng.
    """
    if not 0.0 <= fix_fraction <= 1.0:
        raise ValueError("fix_fraction must be in [0, 1]")
    upgraded: list[PanelTask] = []
    for task in tasks:
        if not task.family_correct(family) and rng.random() < fix_fraction:
            answers = dict(task.answers)
            answers[family] = task.expected
            upgraded.append(replace(task, answers=answers))
        else:
            upgraded.append(task)
    return upgraded


# ---------------------------------------------------------------------------
# Deterministic synthetic panel — a fixture, NOT experimental evidence
# ---------------------------------------------------------------------------

#: Probability that an alpha error is a shared trap answer beta repeats. This
#: parameter is what makes the fixture's errors correlated and is exactly the
#: quantity :func:`m8e3_error_overlap` measures on real families.
TRAP_PROBABILITY = 0.6

#: Verifier quality in the fixture: 5% false rejections, 25% false approvals.
CRITIC_FALSE_REJECTION = 0.05
CRITIC_FALSE_APPROVAL = 0.25


def m8e3_synthetic_panel(seed: int = 932, n: int = 400) -> list[PanelTask]:
    """A fixed paired corpus with a correlated-error trap and a critic verifier.

    Structure, deterministic under ``seed``:

    - contexts cycle coding/research/tool-use with base skill 0.9/0.7/0.5;
    - family ``alpha`` (primary) errs with probability 1 - skill, and an
      error is a shared ``TRAP`` answer with probability ``TRAP_PROBABILITY``;
    - family ``beta`` repeats the trap when trapped (a correlated error),
      otherwise errs independently;
    - the ``critic`` verifier approves correct answers with probability
      1 - ``CRITIC_FALSE_REJECTION`` and wrong answers with probability
      ``CRITIC_FALSE_APPROVAL``;
    - claimed confidence tracks skill with sigma 0.08 and never sees the trap;
    - the #930 baseline is 5 i.i.d. alpha samples: they vary near alpha's
      skill boundary but agree exactly when alpha is confidently wrong
      (trapped) — self-consistency's known blind spot, reproduced here so
      the comparison can show it.

    The fixture validates the machinery and demonstrates the comparison's
    structure; it is evidence about this construction only.
    """
    rng = random.Random(seed)
    skill = {"coding": 0.9, "research": 0.7, "tool-use": 0.5}
    contexts = sorted(skill)
    tasks: list[PanelTask] = []
    correct = "ok"
    trap = "TRAP"
    for i in range(n):
        context = contexts[i % len(contexts)]
        base = skill[context]
        claimed = min(1.0, max(0.0, rng.gauss(base, 0.08)))
        if rng.random() < base:
            alpha_answer, alpha_state = correct, "correct"
        elif rng.random() < TRAP_PROBABILITY:
            alpha_answer, alpha_state = trap, "trap"
        else:
            alpha_answer, alpha_state = f"alpha-wrong-{i}", "unlucky"
        if alpha_state == "trap":
            beta_answer = trap
        elif alpha_state == "correct":
            beta_answer = correct if rng.random() < 0.9 else f"beta-wrong-{i}"
        else:
            beta_answer = correct if rng.random() < base else f"beta-wrong-{i}"
        samples: list[str] = []
        for _ in range(5):
            if alpha_state == "correct":
                samples.append(correct if rng.random() < 0.97 else f"alpha-var-{i}")
            elif alpha_state == "trap":
                samples.append(trap)
            else:
                samples.append(rng.choice((alpha_answer, f"alt-{i}a", f"alt-{i}b")))
        if alpha_state == "correct":
            approved = rng.random() >= CRITIC_FALSE_REJECTION
        else:
            approved = rng.random() < CRITIC_FALSE_APPROVAL
        tasks.append(
            PanelTask(
                task_id=f"t{i}",
                context=context,
                expected=correct,
                primary=PRIMARY,
                answers={PRIMARY: alpha_answer, "beta": beta_answer},
                claimed=claimed,
                verifiers={"critic": approved},
                single_family_samples=tuple(samples),
            )
        )
    return tasks


# ---------------------------------------------------------------------------
# Tests: panel data model and signal projection
# ---------------------------------------------------------------------------


class TestPanelModel:
    def test_family_correctness_is_derived_from_expected_not_from_verdicts(self) -> None:
        task = PanelTask(
            task_id="t0",
            context="c",
            expected="ok",
            primary=PRIMARY,
            answers={PRIMARY: "ok", "beta": "nope"},
            claimed=0.9,
            verifiers={"critic": True},
        )
        assert task.family_correct(PRIMARY) is True
        assert task.family_correct("beta") is False
        assert task.primary_correct is True  # verifier approval changed nothing

    def test_unknown_family_and_primary_are_loud_errors(self) -> None:
        task = PanelTask("t0", "c", "ok", PRIMARY, {PRIMARY: "ok", "beta": "ok"}, 0.5)
        with pytest.raises(KeyError, match="did not answer"):
            task.family_correct("gamma")
        with pytest.raises(ValueError, match="primary"):
            PanelTask("t1", "c", "ok", "gamma", {PRIMARY: "ok"}, 0.5)
        with pytest.raises(ValueError, match="at least one family"):
            PanelTask("t2", "c", "ok", PRIMARY, {}, 0.5)

    def test_observation_projection_carries_present_signals_only(self) -> None:
        bare = PanelTask("t0", "c", "ok", PRIMARY, {PRIMARY: "ok", "beta": "ok"}, 0.7)
        o = m8e3_observation(bare)
        assert set(o.signals) == {"family_agree"}
        assert o.success is True
        assert o.claimed == 0.7
        full = PanelTask(
            "t1",
            "c",
            "ok",
            PRIMARY,
            {PRIMARY: "nope", "beta": "ok"},
            0.7,
            verifiers={"critic": True},
            single_family_samples=("a", "a"),
        )
        o_full = m8e3_observation(full, historical={"c": 0.6})
        assert set(o_full.signals) == {
            "family_agree",
            "self_consistency",
            "verifier_approve",
            "historical",
        }
        assert o_full.signals["family_agree"] == pytest.approx(0.0)  # families diverge
        assert o_full.signals["self_consistency"] == pytest.approx(1.0)
        assert o_full.signals["verifier_approve"] == pytest.approx(1.0)
        assert o_full.signals["historical"] == pytest.approx(0.6)
        assert o_full.success is False  # the primary was wrong, whatever the signals said

    def test_projection_rejects_missing_history_context(self) -> None:
        task = PanelTask("t0", "new-context", "ok", PRIMARY, {PRIMARY: "ok"}, 0.5)
        with pytest.raises(KeyError, match="historical"):
            m8e3_observation(task, historical={"old": 0.5})

    def test_single_family_panel_carries_no_heterogeneous_evidence(self) -> None:
        # One family alone reports maximum agreement — *absence of
        # cross-family evidence*, which downstream metrics must see as the
        # constant (uninformative) signal it is, not as confidence.
        solo = [PanelTask(f"t{i}", "c", "ok", PRIMARY, {PRIMARY: "ok"}, 0.9) for i in range(4)]
        assert all(m8e3_observation(t).signals["family_agree"] == pytest.approx(1.0) for t in solo)

    def test_panel_agreement_can_score_a_subset_of_families(self) -> None:
        task = PanelTask(
            "t0", "c", "ok", PRIMARY, {PRIMARY: "ok", "beta": "ok", "gamma": "nope"}, 0.5
        )
        assert m8e3_panel_agreement(task) == pytest.approx(1.0 - 2 / 3)
        assert m8e3_panel_agreement(task, [PRIMARY, "beta"]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Tests: correlated-error accounting
# ---------------------------------------------------------------------------


class TestCorrelatedErrors:
    def _corpus(self) -> list[PanelTask]:
        # Hand-checked: alpha wrong on t0,t1; beta wrong on t0,t2.
        return [
            PanelTask("t0", "c", "ok", PRIMARY, {PRIMARY: "x", "beta": "y"}, 0.5),
            PanelTask("t1", "c", "ok", PRIMARY, {PRIMARY: "x", "beta": "ok"}, 0.5),
            PanelTask("t2", "c", "ok", PRIMARY, {PRIMARY: "ok", "beta": "y"}, 0.5),
            PanelTask("t3", "c", "ok", PRIMARY, {PRIMARY: "ok", "beta": "ok"}, 0.5),
        ]

    def test_error_overlap_hand_values(self) -> None:
        corpus = self._corpus()
        # Both wrong only on t0; either wrong on t0,t1,t2.
        assert m8e3_error_overlap(corpus, PRIMARY, "beta") == pytest.approx(1 / 3)
        with pytest.raises(ValueError, match="at least one judged"):
            m8e3_error_overlap([], PRIMARY, "beta")
        with pytest.raises(KeyError, match="did not answer"):
            m8e3_error_overlap(corpus, PRIMARY, "gamma")

    def test_perfectly_correlated_and_independent_extremes(self) -> None:
        same_errors = [
            PanelTask("t0", "c", "ok", PRIMARY, {PRIMARY: "x", "beta": "x"}, 0.5),
            PanelTask("t1", "c", "ok", PRIMARY, {PRIMARY: "x", "beta": "x"}, 0.5),
            PanelTask("t2", "c", "ok", PRIMARY, {PRIMARY: "ok", "beta": "ok"}, 0.5),
        ]
        assert m8e3_error_overlap(same_errors, PRIMARY, "beta") == pytest.approx(1.0)
        disjoint = [
            PanelTask("t0", "c", "ok", PRIMARY, {PRIMARY: "x", "beta": "ok"}, 0.5),
            PanelTask("t1", "c", "ok", PRIMARY, {PRIMARY: "ok", "beta": "y"}, 0.5),
        ]
        assert m8e3_error_overlap(disjoint, PRIMARY, "beta") == pytest.approx(0.0)
        # Neither family ever errs: independence is UNMEASURED, not perfect.
        flawless = [PanelTask("t0", "c", "ok", PRIMARY, {PRIMARY: "ok", "beta": "ok"}, 0.5)]
        with pytest.raises(ValueError, match="undefined"):
            m8e3_error_overlap(flawless, PRIMARY, "beta")

    def test_joint_error_rate_bounds(self) -> None:
        corpus = self._corpus()
        assert m8e3_joint_error_rate(corpus, [PRIMARY]) == pytest.approx(0.5)
        assert m8e3_joint_error_rate(corpus, ["beta"]) == pytest.approx(0.5)
        assert m8e3_joint_error_rate(corpus, [PRIMARY, "beta"]) == pytest.approx(0.25)
        with pytest.raises(ValueError, match="at least one"):
            m8e3_joint_error_rate(corpus, [])
        with pytest.raises(ValueError, match="at least one judged"):
            m8e3_joint_error_rate([], [PRIMARY])

    def test_fixture_errors_are_correlated_and_overlap_is_measured(self) -> None:
        # The fixture plants traps on purpose: the measured overlap must
        # expose them (strictly between the disjoint and identical extremes),
        # and the joint error rate must be strictly worse than alpha's alone —
        # the correlation penalty an ensemble cannot recover.
        corpus = m8e3_synthetic_panel()
        overlap = m8e3_error_overlap(corpus, PRIMARY, "beta")
        assert 0.0 < overlap < 1.0
        alpha_alone = m8e3_joint_error_rate(corpus, [PRIMARY])
        joint = m8e3_joint_error_rate(corpus, [PRIMARY, "beta"])
        assert joint < alpha_alone  # a second family still recovers *something*
        traps = sum(
            1 for t in corpus if t.answers[PRIMARY] == "TRAP" and t.answers["beta"] == "TRAP"
        )
        assert traps > 0  # the correlated slice the fixture plants is non-empty


# ---------------------------------------------------------------------------
# Tests: verifier confusion (false approval / false rejection)
# ---------------------------------------------------------------------------


class TestVerifierConfusion:
    def _corpus(self) -> list[PanelTask]:
        return [
            PanelTask("t0", "c", "ok", PRIMARY, {PRIMARY: "ok"}, 0.5, verifiers={"critic": True}),
            PanelTask("t1", "c", "ok", PRIMARY, {PRIMARY: "ok"}, 0.5, verifiers={"critic": False}),
            PanelTask("t2", "c", "ok", PRIMARY, {PRIMARY: "x"}, 0.5, verifiers={"critic": True}),
            PanelTask("t3", "c", "ok", PRIMARY, {PRIMARY: "x"}, 0.5, verifiers={"critic": False}),
        ]

    def test_confusion_hand_values(self) -> None:
        confusion = m8e3_verifier_confusion(self._corpus(), "critic")
        assert (confusion.approved, confusion.rejected) == (2, 2)
        assert (confusion.false_approvals, confusion.false_rejections) == (1, 1)
        assert confusion.false_approval_rate == pytest.approx(0.5)  # half of errors waved through
        assert confusion.false_rejection_rate == pytest.approx(0.5)  # half of good answers killed

    def test_absent_outcome_classes_are_undefined_not_zero(self) -> None:
        all_correct = [
            PanelTask("t0", "c", "ok", PRIMARY, {PRIMARY: "ok"}, 0.5, verifiers={"critic": True})
        ]
        with pytest.raises(ValueError, match="false-approval"):
            m8e3_verifier_confusion(all_correct, "critic")
        all_wrong = [
            PanelTask("t0", "c", "ok", PRIMARY, {PRIMARY: "x"}, 0.5, verifiers={"critic": True})
        ]
        with pytest.raises(ValueError, match="false-rejection"):
            m8e3_verifier_confusion(all_wrong, "critic")

    def test_missing_verifier_and_empty_corpus_are_loud(self) -> None:
        with pytest.raises(ValueError, match="at least one judged"):
            m8e3_verifier_confusion([], "critic")
        with pytest.raises(KeyError, match="did not judge"):
            m8e3_verifier_confusion(self._corpus(), "other-critic")

    def test_fixture_critic_operates_at_its_designed_operating_point(self) -> None:
        # The fixture's critic is built with 5% false rejections and 25%
        # false approvals; the confusion measurement must recover roughly
        # those rates from outcomes alone — this is the machinery a real
        # verifier strategy would be judged with.
        corpus = m8e3_synthetic_panel()
        confusion = m8e3_verifier_confusion(corpus, "critic")
        assert confusion.false_rejection_rate == pytest.approx(CRITIC_FALSE_REJECTION, abs=0.03)
        assert confusion.false_approval_rate == pytest.approx(CRITIC_FALSE_APPROVAL, abs=0.03)


# ---------------------------------------------------------------------------
# Tests: signal combination
# ---------------------------------------------------------------------------


class TestCombination:
    def test_combine_is_a_convex_weighted_mean(self) -> None:
        assert m8e3_combine({"a": 1.0, "b": 0.0}, {"a": 0.5, "b": 0.5}) == pytest.approx(0.5)
        assert m8e3_combine({"a": 1.0, "b": 0.0}, {"a": 1.0, "b": 0.0}) == pytest.approx(1.0)
        assert m8e3_combine({"a": 0.6}, {"a": 1.0}) == pytest.approx(0.6)

    def test_combine_rejects_degenerate_specifications(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            m8e3_combine({}, {})
        with pytest.raises(ValueError, match="exactly"):
            m8e3_combine({"a": 0.5}, {"a": 0.5, "b": 0.5})
        with pytest.raises(ValueError, match="non-negative"):
            m8e3_combine({"a": 0.5, "b": 0.5}, {"a": 1.5, "b": -0.5})
        with pytest.raises(ValueError, match="sum to 1"):
            m8e3_combine({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.4})
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            m8e3_combine({"a": 1.5, "b": 0.0}, {"a": 0.5, "b": 0.5})


# ---------------------------------------------------------------------------
# Tests: incremental cost/latency accounting
# ---------------------------------------------------------------------------


class TestCostAccounting:
    ALPHA = CallProfile("alpha", 2.0, 400.0)
    BETA = CallProfile("beta", 3.0, 600.0)
    CRITIC = CallProfile("critic", 1.0, 200.0)

    def test_self_consistency_costs_are_sequential(self) -> None:
        baseline = m8e3_self_consistency_cost(self.ALPHA, 5)
        assert baseline.total_cost == pytest.approx(10.0)
        assert baseline.latency_ms == pytest.approx(2000.0)  # samples cannot overlap
        assert baseline.label == "self-consistency:alphax5"
        with pytest.raises(ValueError, match="at least one sample"):
            m8e3_self_consistency_cost(self.ALPHA, 0)

    def test_panel_costs_are_parallel_with_a_sequential_verifier_pass(self) -> None:
        panel = m8e3_panel_cost([self.ALPHA, self.BETA], [self.CRITIC])
        assert panel.total_cost == pytest.approx(6.0)  # every call is still billed
        assert panel.latency_ms == pytest.approx(800.0)  # max(400, 600) + 200
        assert panel.label == "panel[alpha,beta,verify:critic]"
        serial = m8e3_panel_cost([self.ALPHA, self.BETA], [self.CRITIC], parallel=False)
        assert serial.latency_ms == pytest.approx(1200.0)
        assert serial.total_cost == pytest.approx(panel.total_cost)
        with pytest.raises(ValueError, match="at least one family"):
            m8e3_panel_cost([])
        with pytest.raises(ValueError, match="non-negative"):
            m8e3_panel_cost([CallProfile("bad", -1.0, 10.0)])

    def test_incremental_ratio_and_degenerate_baseline(self) -> None:
        baseline = m8e3_self_consistency_cost(self.ALPHA, 5)
        panel = m8e3_panel_cost([self.ALPHA, self.BETA], [self.CRITIC])
        assert m8e3_incremental_cost_ratio(panel, baseline) == pytest.approx(0.6)
        free = PanelCost("free", 0.0, 0.0)
        with pytest.raises(ValueError, match="positive"):
            m8e3_incremental_cost_ratio(panel, free)

    def test_fixture_comparison_costs_are_quantified_not_asserted(self) -> None:
        # The cost side of the leaf's comparison, measured with the fixture's
        # strategy shapes: heterogeneity replaces sample count, it does not
        # add to it. The ratio itself is a measurement; whether it is worth
        # it depends on the discrimination the panel adds, measured elsewhere.
        baseline = m8e3_self_consistency_cost(CallProfile("alpha", 2.0, 400.0), 5)
        panel = m8e3_panel_cost(
            [CallProfile("alpha", 2.0, 400.0), CallProfile("beta", 3.0, 600.0)],
            [CallProfile("critic", 1.0, 200.0)],
        )
        ratio = m8e3_incremental_cost_ratio(panel, baseline)
        assert 0.0 < ratio < 1.0  # cheaper than 5 samples, but not free
        assert panel.latency_ms < baseline.latency_ms  # and concurrently served


# ---------------------------------------------------------------------------
# Tests: model-upgrade robustness
# ---------------------------------------------------------------------------


class TestUpgradeRobustness:
    def test_upgrade_fixes_only_the_target_family(self) -> None:
        corpus = m8e3_synthetic_panel(seed=932, n=60)
        upgraded = m8e3_apply_family_upgrade(corpus, "beta", 1.0, random.Random(11))
        assert len(upgraded) == len(corpus)
        for before, after in zip(corpus, upgraded, strict=True):
            assert after.expected == before.expected
            assert after.answers[PRIMARY] == before.answers[PRIMARY]  # alpha untouched
            assert after.primary_correct == before.primary_correct
            assert after.family_correct("beta") is True  # every beta error fixed
        # Overlap collapses to exactly zero: beta's error set is empty, so no
        # co-failure remains — a measured result, distinct from the undefined
        # case where neither family ever errs (tested in
        # TestCorrelatedErrors.test_perfectly_correlated_and_independent_extremes).
        assert m8e3_error_overlap(upgraded, PRIMARY, "beta") == pytest.approx(0.0)

    def test_upgrade_is_deterministic_under_a_seed(self) -> None:
        corpus = m8e3_synthetic_panel(seed=932, n=80)
        first = m8e3_apply_family_upgrade(corpus, "beta", 0.5, random.Random(4))
        second = m8e3_apply_family_upgrade(corpus, "beta", 0.5, random.Random(4))
        assert first == second
        other = m8e3_apply_family_upgrade(corpus, "beta", 0.5, random.Random(5))
        assert first != other
        with pytest.raises(ValueError, match="fix_fraction"):
            m8e3_apply_family_upgrade(corpus, "beta", 1.5, random.Random(1))
        with pytest.raises(KeyError, match="did not answer"):
            m8e3_apply_family_upgrade(corpus, "gamma", 0.5, random.Random(1))

    def test_partial_upgrade_reduces_correlation_and_is_measurable(self) -> None:
        # Upgrading beta removes its trap-mimicking errors, so the families'
        # error sets decorrelate and the joint (both-wrong) rate falls — the
        # quantities a threshold tuned on the pre-upgrade panel silently
        # relied on. The harness must show the movement, which is exactly the
        # leaf's robustness-across-upgrades measurement.
        corpus = m8e3_synthetic_panel(seed=932, n=400)
        upgraded = m8e3_apply_family_upgrade(corpus, "beta", 1.0, random.Random(11))
        joint_before = m8e3_joint_error_rate(corpus, [PRIMARY, "beta"])
        joint_after = m8e3_joint_error_rate(upgraded, [PRIMARY, "beta"])
        assert joint_after < joint_before
        assert joint_after == pytest.approx(0.0)  # beta no longer co-fails at all
        # A partial upgrade moves the same dial part-way, measurably.
        partial = m8e3_joint_error_rate(
            m8e3_apply_family_upgrade(corpus, "beta", 0.5, random.Random(11)), [PRIMARY, "beta"]
        )
        assert 0.0 < partial < joint_before


# ---------------------------------------------------------------------------
# Tests: the comparative study the leaf demands, on the matched fixture
# ---------------------------------------------------------------------------


class TestComparativeStudy:
    @staticmethod
    def _score_holdout(observations: Sequence[object], signal: str) -> tuple[float, float]:
        # "claimed" is the observation's own self-report field; every other
        # signal lives in the signals map.
        select = (lambda o: o.claimed) if signal == "claimed" else (lambda o: o.signals[signal])
        return (
            m8e.m8e_auroc(observations, signal=select),
            m8e.m8e_auprc(observations, signal=select),
        )

    def test_every_baselined_signal_is_scored_on_matched_tasks(self) -> None:
        # The leaf's comparison: #930 self-consistency, #931 historical
        # calibration, #932 disagreement, the verifier, and raw self-report —
        # all scored against the same observed outcomes with one metric
        # implementation. A missing signal would raise KeyError here rather
        # than silently drop out of the ranking.
        corpus = m8e3_synthetic_panel()
        train, holdout = m8e.m8e_temporal_split(corpus, 0.5)
        historical = m8e.m8e_historical_calibration([m8e3_observation(t) for t in train])
        holdout_obs = [m8e3_observation(t, historical=historical) for t in holdout]
        for signal in (
            "claimed",
            "self_consistency",
            "family_agree",
            "verifier_approve",
            "historical",
        ):
            auroc, auprc = self._score_holdout(holdout_obs, signal)
            assert 0.5 < auroc < 1.0, signal  # informative, imperfect — as fixtures go
            assert auprc > 0.0, signal

    def test_disagreement_beats_self_report_on_the_matched_corpus(self) -> None:
        corpus = m8e3_synthetic_panel()
        train, holdout = m8e.m8e_temporal_split(corpus, 0.5)
        historical = m8e.m8e_historical_calibration([m8e3_observation(t) for t in train])
        holdout_obs = [m8e3_observation(t, historical=historical) for t in holdout]
        auroc = {
            name: m8e.m8e_auroc(
                holdout_obs,
                signal=(lambda o: o.claimed)
                if name == "claimed"
                else (lambda o, n=name: o.signals[n]),
            )
            for name in ("claimed", "family_agree", "verifier_approve")
        }
        # The leaf's hypothesis, in miniature: the panel's cross-family
        # agreement and the critic both rank errors better than the primary's
        # own confidence, which is overconfident exactly on the trap slice.
        assert auroc["family_agree"] > auroc["claimed"]
        assert auroc["verifier_approve"] > auroc["claimed"]

    def test_verifier_covers_the_disagreement_blind_spot(self) -> None:
        # Correlated traps rank at maximum family agreement while being wrong;
        # the critic detects most of them. On the agreeing slice (traps plus
        # fully-correct items) family agreement is a constant — it carries no
        # information, so its AUROC degenerates to chance — while the critic
        # still separates its catches. Measured, not assumed.
        corpus = m8e3_synthetic_panel()
        agreeing = [t for t in corpus if t.answers[PRIMARY] == t.answers["beta"]]
        assert agreeing, "fixture must plant the correlated-error slice"
        assert any(not t.primary_correct for t in agreeing)  # traps really are in here
        agreeing_obs = [m8e3_observation(t) for t in agreeing]
        auroc_agree = m8e.m8e_auroc(agreeing_obs, signal=lambda o: o.signals["family_agree"])
        auroc_verifier = m8e.m8e_auroc(agreeing_obs, signal=lambda o: o.signals["verifier_approve"])
        assert auroc_agree == pytest.approx(0.5)  # agreement is constant here: blind
        assert auroc_verifier > 0.7  # the critic separates correct from trapped

    def test_ensemble_adds_incremental_discrimination_over_each_signal_alone(self) -> None:
        corpus = m8e3_synthetic_panel()
        train, holdout = m8e.m8e_temporal_split(corpus, 0.5)
        historical = m8e.m8e_historical_calibration([m8e3_observation(t) for t in train])
        holdout_obs = [m8e3_observation(t, historical=historical) for t in holdout]

        def ensemble(o: object) -> float:
            return m8e3_combine(
                {
                    "family_agree": o.signals["family_agree"],
                    "verifier": o.signals["verifier_approve"],
                },
                {"family_agree": 0.5, "verifier": 0.5},
            )

        scores = {
            name: m8e.m8e_auroc(holdout_obs, signal=signal)
            for name, signal in (
                ("disagreement", lambda o: o.signals["family_agree"]),
                ("verifier", lambda o: o.signals["verifier_approve"]),
                ("ensemble", ensemble),
            )
        }
        # Each signal alone leaves the other's slice mis-ranked; the convex
        # combination must strictly dominate both single-signal AUROCs.
        assert scores["ensemble"] > scores["disagreement"]
        assert scores["ensemble"] > scores["verifier"]

    def test_selective_answering_improves_with_the_ensemble_signal(self) -> None:
        # Risk-coverage view of the same comparison: answering only on the
        # most ensemble-confident decisions must incur less risk than
        # answering on self-report at matched coverage.
        corpus = m8e3_synthetic_panel()
        holdout = m8e.m8e_temporal_split(corpus, 0.5)[1]
        holdout_obs = [m8e3_observation(t) for t in holdout]

        def ensemble(o: object) -> float:
            return 0.5 * o.signals["family_agree"] + 0.5 * o.signals["verifier_approve"]

        aurc_ensemble = m8e.m8e_risk_coverage(holdout_obs, signal=ensemble).aurc
        aurc_claimed = m8e.m8e_risk_coverage(holdout_obs).aurc
        assert aurc_ensemble < aurc_claimed


# ---------------------------------------------------------------------------
# Tests: the evidence-only trust boundary holds by construction
# ---------------------------------------------------------------------------


class TestEvidenceOnlyContract:
    def test_contract_marker_is_inherited_from_the_merged_harness(self) -> None:
        assert ADVISORY_ONLY_E3 is True
        assert m8e.ADVISORY_ONLY is True

    def test_module_imports_no_maistro_module(self) -> None:
        tree = ast.parse(inspect.getsource(sys.modules[__name__]))  # type: ignore[arg-type]
        imported = {
            node.names[0].name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        }
        assert "maistro" not in imported

    def test_records_are_frozen(self) -> None:
        task = PanelTask("t0", "c", "ok", PRIMARY, {PRIMARY: "ok"}, 0.5, verifiers={"critic": True})
        with pytest.raises(AttributeError):
            task.claimed = 0.99  # type: ignore[misc]
        shared = {"critic": True}
        confusion = m8e3_verifier_confusion(
            [
                PanelTask("t0", "c", "ok", PRIMARY, {PRIMARY: "ok"}, 0.5, verifiers=shared),
                PanelTask("t1", "c", "ok", PRIMARY, {PRIMARY: "x"}, 0.5, verifiers=shared),
            ],
            "critic",
        )
        with pytest.raises(AttributeError):
            confusion.false_approval_rate = 0.0  # type: ignore[misc]
        cost = PanelCost("panel", 1.0, 1.0)
        with pytest.raises(AttributeError):
            cost.total_cost = 0.0  # type: ignore[misc]

    def test_records_are_measurements_not_actions(self) -> None:
        for record in (VerifierConfusion, PanelCost, CallProfile):
            for f in record.__dataclass_fields__:
                assert isinstance(f, str)
            for verb in ("apply", "execute", "route", "escalate", "authorize"):
                assert not callable(getattr(record, verb, None))

    def test_claimed_confidence_is_range_validated_everywhere(self) -> None:
        with pytest.raises(ValueError, match="claimed"):
            PanelTask("t0", "c", "ok", PRIMARY, {PRIMARY: "ok"}, 1.5)
        with pytest.raises(ValueError, match="claimed"):
            m8e.UncertaintyObservation("c", 1.5, True)
