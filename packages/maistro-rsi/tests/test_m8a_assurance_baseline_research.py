"""M8-A research harness — the assurance-matrix rubric and its measured baseline.

Issue #880 (epic M8-A), initiative #879, milestone tracker #878. Leaves:
#881-#894, #896, #897 (each leaf owns its own experiment and terminal
disposition; this module owns the comparative machinery the epic promises).

This module is a RESEARCH ARTIFACT, not product code. It implements the
scoring rubric for the epic's required "ranked assurance matrix" — eight
criteria (defect-finding yield, confidence strength, applicability breadth,
implementation effort, ongoing maintenance, CI/runtime cost, trustworthiness
of the oracle, fit for asynchronous/distributed MAIstro semantics) over
evidence-carrying candidates — so the epic's comparative output is
reproducible machinery rather than prose, and each leaf appends a row instead
of reinventing a scoring scheme.

Trust boundary (the epic contract, enforced by construction):

- Every number produced here is ADVISORY EVIDENCE. Nothing in this module
  reads or writes a Goal, Run, NodeRun, Attempt, routing decision, or any
  Warden/HITL/delegation control, and it imports nothing from ``maistro`` at
  all, so it cannot become an authority by accident (M8 guardrails 1-2).
- A candidate that lacks a complete, per-axis evidenced score is EXCLUDED
  from ranking, never scored as zero — an unmeasured axis must not masquerade
  as a bad measurement (the epic's non-goal: do not claim evidence from
  randomized or missing testing).
- A ``technique`` candidate cannot be ranked without exactly one terminal
  disposition (GRADUATE / INCUBATE / REJECT / WATCH, per #878's contract);
  ``baseline`` rows (the already-shipped gates) are exempt because they are
  the reference, not a candidate.
- Dataclasses are frozen: recorded evidence cannot be mutated into a better
  ranking after the fact.

The experiment record and the measured baseline facts live in
``docs/research/880-advanced-verification-assurance.md``. The baseline rows
below cite this head's evidence (files and one executed run); they are
reference points for the matrix, not proof that a technique works.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

import pytest

#: Explicit evidence-only contract marker, asserted by a test so it cannot
#: silently rot. Nothing outside this module may treat M8-A matrix output as
#: authorization or as a gate; the canonical quality ratchets in
#: ``quality/*.json`` and ``scripts/check-*.py`` remain the only enforcement
#: surfaces (M8 guardrail 1).
ADVISORY_ONLY = True

#: The eight criteria the epic fixes for the comparative output, split into
#: benefit axes (higher is better) and cost axes (higher is worse). The epic
#: text names all eight; this vocabulary is closed so a row cannot invent an
#: axis the comparative output never promised.
BENEFIT_AXES: Final[tuple[str, ...]] = (
    "defect_yield",
    "confidence_strength",
    "applicability_breadth",
    "oracle_trustworthiness",
)
COST_AXES: Final[tuple[str, ...]] = (
    "implementation_effort",
    "maintenance_burden",
    "ci_runtime_cost",
    "async_distributed_friction",
)
ALL_AXES: Final[tuple[str, ...]] = BENEFIT_AXES + COST_AXES

#: Terminal dispositions per #878 ("every M8 research leaf must finish with
#: exactly one disposition"). Closed vocabulary; a candidate is either
#: un-dispositioned (not rankable as a technique) or carries exactly one of
#: these strings.
DISPOSITIONS: Final[tuple[str, ...]] = (
    "GRADUATE",
    "INCUBATE",
    "REJECT",
    "WATCH",
)

CandidateKind = Literal["baseline", "technique"]

#: Score floor/ceiling per axis. 0 = no evidence of value on this axis;
#: 3 = strong, measured evidence. Bounds are inclusive.
SCORE_MIN = 0
SCORE_MAX = 3


@dataclass(frozen=True)
class Evidence:
    """One citation backing a score: where the number came from.

    ``source`` names a repository artifact or an executed command; ``note``
    records what the source actually shows. A score without an evidence
    citation is the exact "benchmark theater" the M8 guardrails forbid, so
    the rubric refuses to rank one.
    """

    source: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.source or not self.source.strip():
            raise ValueError("evidence source must be a non-empty citation")


@dataclass(frozen=True)
class AssuranceCandidate:
    """One row of the epic's assurance matrix.

    ``scores`` must cover every axis in :data:`ALL_AXES` and every score must
    have a matching entry in ``evidence`` (keyed by the same axis name).
    Missing axes or missing citations make the candidate *unevidenced*: it is
    excluded from ranking rather than scored as zero, so the matrix can never
    silently present an unmeasured judgment as a measurement.
    """

    name: str
    kind: CandidateKind
    scores: Mapping[str, int]
    evidence: Mapping[str, Evidence]
    #: Required for ``technique`` rows before ranking (#878); ``baseline``
    #: rows ship without one because they are the reference, not a candidate.
    disposition: str | None = None
    #: The failure class this candidate targets, per the epic's experiment
    #: contract item 5 ("state what failure class the technique catches that
    #: existing gates do not"). Free text; unchecked here, checked by review.
    failure_class: str | None = None

    def __post_init__(self) -> None:
        # A frozen dataclass does not freeze caller-owned dictionaries. Copy
        # before validating, then expose read-only views of the recorded data.
        object.__setattr__(self, "scores", MappingProxyType(dict(self.scores)))
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))
        if not self.name or not self.name.strip():
            raise ValueError("candidate name must be non-empty")
        if self.kind not in ("baseline", "technique"):
            raise ValueError(f"unknown candidate kind: {self.kind!r}")
        if self.disposition is not None and self.disposition not in DISPOSITIONS:
            raise ValueError(
                f"disposition {self.disposition!r} outside the #878 vocabulary {DISPOSITIONS}"
            )
        for axis, score in self.scores.items():
            if axis not in ALL_AXES:
                raise ValueError(f"unknown axis {axis!r}; axes are fixed by the epic")
            if not SCORE_MIN <= score <= SCORE_MAX:
                raise ValueError(
                    f"score for {axis!r} out of bounds [{SCORE_MIN}, {SCORE_MAX}]: {score}"
                )
        for axis, ev in self.evidence.items():
            if axis not in ALL_AXES:
                raise ValueError(f"evidence keyed by unknown axis {axis!r}")
            if not isinstance(ev, Evidence):
                raise ValueError(f"evidence for {axis!r} is not an Evidence citation")

    @property
    def missing_axes(self) -> tuple[str, ...]:
        """Axes with no score, ordered canonically (the exclusion reason)."""
        return tuple(axis for axis in ALL_AXES if axis not in self.scores)

    @property
    def uncited_axes(self) -> tuple[str, ...]:
        """Scored axes with no matching evidence citation, canonically ordered."""
        return tuple(axis for axis in ALL_AXES if axis in self.scores and axis not in self.evidence)

    @property
    def is_evidenced(self) -> bool:
        """True when every axis is scored and every score is cited."""
        return not self.missing_axes and not self.uncited_axes

    @property
    def rankable(self) -> bool:
        """Evidenced rows only; techniques additionally need a disposition."""
        return self.is_evidenced and (self.kind == "baseline" or self.disposition is not None)

    @property
    def benefit(self) -> float:
        """Mean of the four benefit axes. Only meaningful when evidenced."""
        return sum(self.scores[axis] for axis in BENEFIT_AXES) / len(BENEFIT_AXES)

    @property
    def cost(self) -> float:
        """Mean of the four cost axes. Only meaningful when evidenced."""
        return sum(self.scores[axis] for axis in COST_AXES) / len(COST_AXES)

    @property
    def net(self) -> float:
        """Transparent composite: mean benefit minus mean cost.

        Deliberately not weighted: any weighting is a judgment the matrix
        must show, not hide inside the scorer. Consumers can reweight from
        the frozen row; the default ranking is the unweighted one.
        """
        return self.benefit - self.cost


def rank_candidates(candidates: Sequence[AssuranceCandidate]) -> tuple[AssuranceCandidate, ...]:
    """Rank the evidenced candidates; unevidenced ones are excluded, not zeroed.

    Ordering: descending net score, ties broken by name so the output is
    deterministic regardless of input order. Baselines and techniques are
    ranked in one list — the epic's question is comparative, and a technique
    that cannot beat the shipped gates on net evidence has not made its case.
    """
    rankable = [candidate for candidate in candidates if candidate.rankable]
    return tuple(sorted(rankable, key=lambda c: (-c.net, c.name)))


# ---------------------------------------------------------------------------
# Historical baseline rows measured at feb19affc (not the current CI state)
# ---------------------------------------------------------------------------
#
# These rows record the state of the *existing* quality stack the epic text
# names, each score citing where the number comes from. They are the
# reference every leaf's technique must be compared against. Scores are the
# note's judgment on the 0-3 scale; the evidence citations are the checkable
# part and are pinned by the tests below.


def _baseline_rows() -> tuple[AssuranceCandidate, ...]:
    """The existing-gates reference rows, with this head's evidence."""
    return (
        AssuranceCandidate(
            name="formal/ Hypothesis suite",
            kind="baseline",
            scores={
                "defect_yield": 2,
                "confidence_strength": 2,
                "applicability_breadth": 1,
                "oracle_trustworthiness": 3,
                "implementation_effort": 1,
                "maintenance_burden": 2,
                "ci_runtime_cost": 1,
                "async_distributed_friction": 1,
            },
            evidence={
                "defect_yield": Evidence(
                    "formal/README.md", "invariants I1-I29 over real maistro code"
                ),
                "confidence_strength": Evidence(
                    "executed at feb19affc: uv run pytest formal -q",
                    "663 passed, 1 skipped (I29 without PG DSN), ~56s local wall clock",
                ),
                "applicability_breadth": Evidence(
                    "formal/README.md",
                    "security invariants only; execution lifecycle (#881) not modeled",
                ),
                "oracle_trustworthiness": Evidence(
                    "formal/README.md",
                    "models import the real maistro.security/auth modules, not a reimplementation",
                ),
                "implementation_effort": Evidence(
                    "formal/README.md", "suite exists and is PR-gated (formal-conformance.yml)"
                ),
                "maintenance_burden": Evidence(
                    "scripts/check-formal-oracle-independence.py",
                    "oracle changes gated separately from candidates",
                ),
                "ci_runtime_cost": Evidence(
                    ".github/workflows/formal-conformance.yml", "timeout-minutes: 15"
                ),
                "async_distributed_friction": Evidence(
                    "formal/models/test_run_lease_fence.py",
                    "concurrency modeled only by I29 against real PostgreSQL",
                ),
            },
        ),
        AssuranceCandidate(
            name="diff coverage gate",
            kind="baseline",
            scores={
                "defect_yield": 1,
                "confidence_strength": 1,
                "applicability_breadth": 3,
                "oracle_trustworthiness": 2,
                "implementation_effort": 0,
                "maintenance_burden": 1,
                "ci_runtime_cost": 1,
                "async_distributed_friction": 0,
            },
            evidence={
                "defect_yield": Evidence(
                    "scripts/check-diff-coverage.py:1-30",
                    "pools changed lines per file; catches untested changed lines, not behavior",
                ),
                "confidence_strength": Evidence(
                    "scripts/check-diff-coverage.py:320-322",
                    "floors are per-file 90% lines / 80% branch arcs — not the 95% the "
                    "quality.yml:1 header claims",
                ),
                "applicability_breadth": Evidence(
                    ".github/workflows/quality.yml:695", "runs on every PR and merge-group entry"
                ),
                "oracle_trustworthiness": Evidence(
                    "scripts/check-diff-coverage.py", "coverage is measured, not asserted"
                ),
                "implementation_effort": Evidence(
                    "scripts/check-diff-coverage.py", "shipped and PR-blocking"
                ),
                "maintenance_burden": Evidence(
                    "quality.yml:690-696",
                    "floors sit under measured worst files; raise as sample grows",
                ),
                "ci_runtime_cost": Evidence(
                    ".github/workflows/quality.yml:701", "one coverage report comparison step"
                ),
                "async_distributed_friction": Evidence(
                    "scripts/check-diff-coverage.py", "line-based; no concurrency semantics"
                ),
            },
        ),
        AssuranceCandidate(
            name="mutation testing (cosmic-ray)",
            kind="baseline",
            scores={
                "defect_yield": 0,
                "confidence_strength": 0,
                "applicability_breadth": 0,
                "oracle_trustworthiness": 0,
                "implementation_effort": 0,
                "maintenance_burden": 0,
                "ci_runtime_cost": 0,
                "async_distributed_friction": 0,
            },
            evidence={
                "defect_yield": Evidence(
                    ".github/workflows/mutation.yml:1-12",
                    "parked: workflow_dispatch-only, self-hosted, echo job — no workload "
                    "executes on PRs or schedules",
                ),
                "confidence_strength": Evidence(
                    ".github/workflows/mutation.yml:1-12",
                    "not executing; machinery (scripts/mutation_*.py, "
                    "quality/mutation-baseline.json) is present but idle",
                ),
                "applicability_breadth": Evidence(
                    "quality/mutation-baseline.json", "recorded baseline exists from prior runs"
                ),
                "oracle_trustworthiness": Evidence(
                    "scripts/mutation_ratchet.py",
                    "surviving-mutant counting is a real oracle when run",
                ),
                "implementation_effort": Evidence(
                    "scripts/mutation_scheduler.py", "scheduler/checkpoint/resume tooling shipped"
                ),
                "maintenance_burden": Evidence(
                    "scripts/mutation_history.py", "history/baseline tooling shipped"
                ),
                "ci_runtime_cost": Evidence(
                    ".github/workflows/mutation.yml:26-33",
                    "zero while parked; historically runner-bound when active",
                ),
                "async_distributed_friction": Evidence(
                    "quality.yml:8", "'changed files only' in the PR gate comment; nightly deferred"
                ),
            },
        ),
        AssuranceCandidate(
            name="OpenAPI contract fuzzing (schemathesis)",
            kind="baseline",
            scores={
                "defect_yield": 0,
                "confidence_strength": 0,
                "applicability_breadth": 0,
                "oracle_trustworthiness": 0,
                "implementation_effort": 0,
                "maintenance_burden": 0,
                "ci_runtime_cost": 0,
                "async_distributed_friction": 0,
            },
            evidence={
                "defect_yield": Evidence(
                    "grep: schemathesis appears only at quality.yml:9",
                    "a header comment; no dependency, step, script, or config exists in the tree",
                ),
                "confidence_strength": Evidence(
                    ".github/workflows/quality.yml:9",
                    "the claimed control is documentation, not an executing gate",
                ),
                "applicability_breadth": Evidence(
                    ".github/workflows/quality.yml",
                    "quality-gate job is 'Pillars 1-4, 7, 8' — pillar 6 absent",
                ),
                "oracle_trustworthiness": Evidence(
                    ".github/workflows/quality.yml:9", "no schema oracle executes"
                ),
                "implementation_effort": Evidence(
                    "docs/research/880-advanced-verification-assurance.md",
                    "establishing the leg is leaf #893's experiment, not a shipped baseline",
                ),
                "maintenance_burden": Evidence(
                    "packages/maistro-server", "OpenAPI spec exists; no fuzzing config to maintain"
                ),
                "ci_runtime_cost": Evidence(".github/workflows/quality.yml", "zero: nothing runs"),
                "async_distributed_friction": Evidence(
                    ".github/workflows/quality.yml", "no workflow semantics exercised"
                ),
            },
        ),
        AssuranceCandidate(
            name="architecture fitness functions",
            kind="baseline",
            scores={
                "defect_yield": 2,
                "confidence_strength": 2,
                "applicability_breadth": 2,
                "oracle_trustworthiness": 3,
                "implementation_effort": 1,
                "maintenance_burden": 2,
                "ci_runtime_cost": 1,
                "async_distributed_friction": 1,
            },
            evidence={
                "defect_yield": Evidence(
                    "scripts/",
                    "75 check-*.py gates incl. cross-package imports, owned store "
                    "access, execution lifecycles, model egress",
                ),
                "confidence_strength": Evidence(
                    "quality/",
                    "40 per-identity ratchet ledgers (vulture, radon, reachability, "
                    "promotion surface, direct effects) with grant provenance",
                ),
                "applicability_breadth": Evidence(
                    ".github/workflows/quality.yml", "PR-blocking across the tree"
                ),
                "oracle_trustworthiness": Evidence(
                    "scripts/ratchet_provenance.py",
                    "grants read from the merge base, so a ledger edit cannot self-authorize",
                ),
                "implementation_effort": Evidence("scripts/check-*.py", "shipped and PR-blocking"),
                "maintenance_burden": Evidence(
                    "AGENTS.md quality section",
                    "floor raises need a two-merge grant dance; ledgers merge-lossy by design",
                ),
                "ci_runtime_cost": Evidence(
                    ".github/workflows/quality.yml", "static scans; the fast PR bag bounds minutes"
                ),
                "async_distributed_friction": Evidence(
                    "scripts/check-execution-lifecycles.py",
                    "static lifecycle-shape checks; no runtime interleaving explored",
                ),
            },
        ),
        AssuranceCandidate(
            name="real PostgreSQL / S3 integration legs",
            kind="baseline",
            scores={
                "defect_yield": 2,
                "confidence_strength": 3,
                "applicability_breadth": 1,
                "oracle_trustworthiness": 3,
                "implementation_effort": 1,
                "maintenance_burden": 2,
                "ci_runtime_cost": 2,
                "async_distributed_friction": 1,
            },
            evidence={
                "defect_yield": Evidence(
                    ".github/workflows/ci.yml:304", "postgres service matrix (17, 18)"
                ),
                "confidence_strength": Evidence(
                    ".github/workflows/ci.yml:404-424",
                    "real MinIO S3 leg; ac_outcome_plugin counts skips as no evidence",
                ),
                "applicability_breadth": Evidence(
                    "formal/models/test_run_lease_fence.py:114",
                    "I29 skips without a DSN locally — the real-store leg is CI-scoped",
                ),
                "oracle_trustworthiness": Evidence(
                    "packages/maistro-core/src/maistro/persistence/",
                    "assertions run against the real engines, not fakes",
                ),
                "implementation_effort": Evidence(".github/workflows/ci.yml", "shipped services"),
                "maintenance_burden": Evidence(
                    ".github/workflows/ci.yml:405-424",
                    "MinIO leg needs a vendored toolchain after upstream archive",
                ),
                "ci_runtime_cost": Evidence(
                    ".github/workflows/integration-scope.yml:31", "125-minute evidence window"
                ),
                "async_distributed_friction": Evidence(
                    "formal/models/test_run_lease_fence.py",
                    "only I29 drives a concurrent-writer invariant so far",
                ),
            },
        ),
    )


#: Module-level constant so the note and any consumer rank one fixed
#: population; tests validate the structure of every row.
MEASURED_BASELINE: Final = _baseline_rows()


#: Technique rows for leaves that have reported experiments.
#: Each row must be fully evidenced and carry a disposition.
def _technique_rows() -> tuple[AssuranceCandidate, ...]:
    """Technique rows for leaves that have reported experiments."""
    return (
        AssuranceCandidate(
            name="linear Run transition helper (#881 precursor)",
            kind="technique",
            scores={
                "defect_yield": 0,
                "confidence_strength": 2,
                "applicability_breadth": 1,
                "oracle_trustworthiness": 1,
                "implementation_effort": 1,
                "maintenance_burden": 1,
                "ci_runtime_cost": 1,
                "async_distributed_friction": 1,
            },
            evidence={
                "defect_yield": Evidence(
                    "formal/models/test_execution_lifecycle.py",
                    "state machine now collected via TestCase and runs in the formal suite; "
                    "no counterexamples found across the explored transition sequences",
                ),
                "confidence_strength": Evidence(
                    "formal/models/test_execution_lifecycle.py",
                    "every step calls the production transition_run from "
                    "maistro.runs.lifecycle; 100 CI-profile examples pass",
                ),
                "applicability_breadth": Evidence(
                    "docs/research/880-advanced-verification-assurance.md",
                    "only the in-memory Run helper; no NodeRun, Attempt, or store exercise",
                ),
                "oracle_trustworthiness": Evidence(
                    "docs/research/880-advanced-verification-assurance.md",
                    "model and implementation read the same RUN_TRANSITIONS table; "
                    "cannot detect an incorrect table entry",
                ),
                "implementation_effort": Evidence(
                    "docs/research/880-advanced-verification-assurance.md",
                    "state machine is straightforward to write",
                ),
                "maintenance_burden": Evidence(
                    "docs/research/880-advanced-verification-assurance.md",
                    "minimal; depends on the documented lifecycle",
                ),
                "ci_runtime_cost": Evidence(
                    "formal/models/test_execution_lifecycle.py",
                    "collected and runs in formal-conformance (timeout-minutes: 15)",
                ),
                "async_distributed_friction": Evidence(
                    "docs/research/880-advanced-verification-assurance.md",
                    "model does not capture concurrency; only linear transitions",
                ),
            },
            disposition="INCUBATE",
            failure_class="sequential Run helper enforcement diverging from its transition table",
        ),
    )


#: All candidates (baseline + technique) for the assurance matrix.
ALL_CANDIDATES: Final = MEASURED_BASELINE + _technique_rows()


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


def test_advisory_only_marker_is_true() -> None:
    """The evidence-only contract marker must be explicit and asserted."""
    assert ADVISORY_ONLY is True


@pytest.mark.parametrize("field", ("scores", "evidence"))
def test_candidate_snapshots_caller_owned_mappings(field: str) -> None:
    """Clearing input dictionaries must not erase a recorded row or its rank."""
    scores = dict.fromkeys(ALL_AXES, 1)
    evidence = {axis: Evidence(f"recorded/{axis}") for axis in ALL_AXES}
    row = AssuranceCandidate(
        name="recorded", kind="technique", scores=scores, evidence=evidence, disposition="WATCH"
    )
    recorded_scores = dict(scores)
    recorded_evidence = dict(evidence)
    inputs = {"scores": scores, "evidence": evidence}

    inputs[field].clear()

    assert dict(row.scores) == recorded_scores
    assert dict(row.evidence) == recorded_evidence
    assert row.rankable
    assert rank_candidates([row]) == (row,)


@pytest.mark.parametrize("field", ("scores", "evidence"))
def test_candidate_exposes_read_only_mappings(field: str) -> None:
    """A consumer cannot rewrite a recorded score or citation through the row."""
    row = _candidate()
    mapping = getattr(row, field)
    original = dict(mapping)
    replacement = 3 if field == "scores" else Evidence("replacement")

    with pytest.raises(TypeError):
        mapping["defect_yield"] = replacement

    assert dict(mapping) == original
    assert row.rankable


def test_axis_vocabulary_matches_the_epic_exactly() -> None:
    """The eight axes are the epic's criteria, split 4 benefit / 4 cost."""
    assert len(ALL_AXES) == 8
    assert len(set(ALL_AXES)) == 8, "axes must be distinct"
    assert set(BENEFIT_AXES) & set(COST_AXES) == set(), "benefit and cost must not overlap"
    assert set(ALL_AXES) == set(BENEFIT_AXES) | set(COST_AXES)
    assert "async_distributed_friction" in COST_AXES, "epic: fit for async/distributed semantics"


def test_disposition_vocabulary_is_the_878_set() -> None:
    """Exactly the four terminal dispositions #878 mandates."""
    assert DISPOSITIONS == ("GRADUATE", "INCUBATE", "REJECT", "WATCH")


def test_score_above_ceiling_is_rejected() -> None:
    with pytest.raises(ValueError, match="out of bounds"):
        _candidate(scores=dict.fromkeys(ALL_AXES, 3) | {"defect_yield": 4})


def test_negative_score_is_rejected() -> None:
    with pytest.raises(ValueError, match="out of bounds"):
        _candidate(scores=dict.fromkeys(ALL_AXES, 0) | {"oracle_trustworthiness": -1})


def test_unknown_axis_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown axis"):
        _candidate(scores=dict.fromkeys(ALL_AXES, 1) | {"vibes": 2})


def test_missing_axis_makes_candidate_unevidenced() -> None:
    scores = {axis: 1 for axis in ALL_AXES if axis != "ci_runtime_cost"}
    candidate = _candidate(scores=scores, evidence_for=scores)
    assert candidate.missing_axes == ("ci_runtime_cost",)
    assert candidate.is_evidenced is False
    assert candidate.rankable is False


def test_scored_but_uncited_axis_makes_candidate_unevidenced() -> None:
    scores = dict.fromkeys(ALL_AXES, 1)
    evidence = {axis: Evidence(f"src/{axis}") for axis in ALL_AXES if axis != "defect_yield"}
    candidate = AssuranceCandidate(
        name="half-cited", kind="technique", scores=scores, evidence=evidence, disposition="WATCH"
    )
    assert candidate.uncited_axes == ("defect_yield",)
    assert candidate.rankable is False


def test_empty_evidence_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty citation"):
        Evidence(source="   ")


def test_unevidenced_candidates_are_excluded_not_zeroed() -> None:
    """An unmeasured axis must not rank as a bad measurement."""
    evidenced = _candidate(name="evidenced", scores=dict.fromkeys(ALL_AXES, 1))
    unevidenced = _candidate(
        name="unevidenced", scores={axis: 3 for axis in ALL_AXES if axis != "defect_yield"}
    )
    ranked = rank_candidates([unevidenced, evidenced])
    assert [c.name for c in ranked] == ["evidenced"], "unevidenced rows must not appear"


def test_technique_without_disposition_is_not_rankable() -> None:
    """#878: a technique finishes with exactly one disposition or none at all."""
    scores = dict.fromkeys(ALL_AXES, 1)
    candidate = AssuranceCandidate(  # direct construction: no auto-disposition
        name="no-disposition",
        kind="technique",
        scores=scores,
        evidence={axis: Evidence(f"src-for-{axis}") for axis in ALL_AXES},
    )
    assert candidate.is_evidenced is True
    assert candidate.rankable is False
    assert rank_candidates([candidate]) == ()


def test_baseline_row_may_rank_without_disposition() -> None:
    """Baseline gates are the reference, not candidates; no disposition needed."""
    for row in MEASURED_BASELINE:
        assert row.kind == "baseline"
        assert row.rankable is True, row.name


def test_disposition_outside_vocabulary_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside the #878 vocabulary"):
        _candidate(name="x", kind="technique", disposition="MAYBE")


def test_benefit_improvement_raises_rank() -> None:
    low = _candidate(name="low", scores=dict.fromkeys(ALL_AXES, 1))
    high_scores = dict.fromkeys(ALL_AXES, 1) | {"confidence_strength": 3}
    high = _candidate(name="high", scores=high_scores)
    ranked = rank_candidates([low, high])
    assert [c.name for c in ranked] == ["high", "low"]
    assert high.net > low.net


def test_cost_increase_lowers_rank_at_equal_benefit() -> None:
    """Cost axes are inverted by construction, not by sign-flipped inputs."""
    cheap = _candidate(name="cheap", scores=dict.fromkeys(ALL_AXES, 1))
    dear_scores = dict.fromkeys(ALL_AXES, 1) | {"ci_runtime_cost": 3}
    dear = _candidate(name="dear", scores=dear_scores)
    assert dear.benefit == cheap.benefit
    ranked = rank_candidates([cheap, dear])
    assert [c.name for c in ranked] == ["cheap", "dear"]


def test_ranking_is_deterministic_across_repeated_calls() -> None:
    population = list(ALL_CANDIDATES)
    first = rank_candidates(population)
    for _ in range(3):
        assert rank_candidates(population) == first


def test_ties_break_by_name_stably() -> None:
    """Two identical rows must order by name, never by input order or luck."""
    a = _candidate(name="alpha", scores=dict.fromkeys(ALL_AXES, 2))
    b = _candidate(name="beta", scores=dict.fromkeys(ALL_AXES, 2))
    assert [c.name for c in rank_candidates([b, a])] == ["alpha", "beta"]
    assert [c.name for c in rank_candidates([a, b])] == ["alpha", "beta"]


def test_empty_population_ranks_empty() -> None:
    assert rank_candidates([]) == ()


def test_dominated_candidate_does_not_disturb_existing_order() -> None:
    """Stable sort property: adding a strictly dominated row preserves the rest.

    A row of all-zero scores TIES a uniform row (net is symmetric), so the
    dominated row here pairs zero benefit with maximum cost: net -3.
    """
    strong_scores = dict.fromkeys(BENEFIT_AXES, 3) | dict.fromkeys(COST_AXES, 0)
    strong = _candidate(name="strong", scores=strong_scores)
    weak = _candidate(name="weak", scores=dict.fromkeys(ALL_AXES, 1))
    dominated_scores = dict.fromkeys(BENEFIT_AXES, 0) | dict.fromkeys(COST_AXES, 3)
    dominated = _candidate(name="ah-domin", scores=dominated_scores)
    assert dominated.net < weak.net < strong.net
    before = rank_candidates([strong, weak])
    after = rank_candidates([weak, dominated, strong])
    assert [c.name for c in after] == [c.name for c in before] + ["ah-domin"]


def test_every_measured_baseline_row_is_fully_evidenced() -> None:
    """The reference rows must themselves pass the rubric they anchor."""
    for row in MEASURED_BASELINE:
        assert row.is_evidenced, f"{row.name}: missing {row.missing_axes or row.uncited_axes}"
        assert row.rankable
        for axis in ALL_AXES:
            assert row.evidence[axis].source.strip(), f"{row.name}/{axis}: empty citation"


def test_baseline_records_the_documented_vs_actual_gaps() -> None:
    """Preserve the two historical gaps measured at feb19affc.

    This is an audit-trail assertion, not a probe of today's workflows. Mutation
    and Schemathesis have since gained executing jobs/tests; current acceptance
    must use fresh measurements rather than treating these rows as live facts.
    """
    by_name = {row.name: row for row in MEASURED_BASELINE}
    mutation = by_name["mutation testing (cosmic-ray)"]
    schemathesis = by_name["OpenAPI contract fuzzing (schemathesis)"]
    for row in (mutation, schemathesis):
        assert all(score == 0 for score in row.scores.values()), (
            f"{row.name}: a non-executing control must score 0 everywhere"
        )
    assert "parked" in mutation.evidence["defect_yield"].note
    assert "quality.yml:9" in schemathesis.evidence["defect_yield"].source


def test_baseline_and_executed_suite_row_carry_the_measured_run() -> None:
    """The formal-suite row must cite the executed run, not the header claim."""
    formal = {row.name: row for row in MEASURED_BASELINE}["formal/ Hypothesis suite"]
    executed = formal.evidence["confidence_strength"]
    assert "executed" in executed.source
    assert "663 passed" in executed.note


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate(
    name: str = "candidate",
    kind: CandidateKind = "technique",
    scores: Mapping[str, int] | None = None,
    evidence_for: Mapping[str, int] | None = None,
    disposition: str | None = None,
) -> AssuranceCandidate:
    """Build a candidate with default scores/citations for the given axes."""
    if disposition is None and kind == "technique":
        disposition = "WATCH"
    if scores is None:
        scores = dict.fromkeys(ALL_AXES, 1)
    if evidence_for is None:
        evidence_for = dict.fromkeys(scores, 1)
    evidence = {
        axis: Evidence(source=f"src-for-{axis}", note=f"score {score}")
        for axis, score in evidence_for.items()
    }
    return AssuranceCandidate(
        name=name, kind=kind, scores=dict(scores), evidence=evidence, disposition=disposition
    )
