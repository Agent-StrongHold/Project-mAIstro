"""SPEC-282 AC-10: the measured curriculum-vs-external lane comparison.

M4-D (#24) exit evidence: compare the bounded curriculum-enabled lane with the
same external evaluation without generated curriculum, and report measured
capability, cost and failure results — including no improvement. These tests
run the real harness (``lane_comparison.compare_lanes``) over a deterministic
reference scenario and pin the exact measured numbers recorded in
docs/specs/SPEC-282-self-generated-curriculum.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import maistro_evolve.lane_comparison as lane_comparison
from maistro_evolve.curriculum import ChallengeDraft
from maistro_evolve.fitness import compute_fitness
from maistro_evolve.lane_comparison import (
    CURRICULUM_ENABLED_LANE,
    EXTERNAL_ONLY_LANE,
    LaneBudget,
    compare_lanes,
)
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome

# SPEC-282's behavioral contract (ADR-032): every test here exercises the
# measured-comparison behavior the spec declares as its contract kind.
pytestmark = [pytest.mark.contract("behavioral")]

#: The exact measured numbers this scenario produces, recorded in SPEC-282's
#: "Measured lane comparison" section. If the harness changes, this test and
#: that section move together — the recorded artifact cannot silently rot.
RECORDED = {
    "generation_rounds": 5,
    "admitted": 1,
    "rejected": 3,
    "proposer_errors": 1,
    "admission_yield": 0.2,
    "generator_proposals": 5,
    "solver_attempts": 4,
    "gate_probes": 16,
}


def _genome(eval_scores: dict[str, float] | None = None) -> PipelineGenome:
    return PipelineGenome(
        id="lane-cmp-g1",
        name="lane-cmp",
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="test-model",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt="test",
                    max_tool_rounds=5,
                )
            ],
            edges=[],
            entry_node="q1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        eval_scores=eval_scores or {},
        harness_params={},
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def _good_draft() -> ChallengeDraft:
    return ChallengeDraft(
        statement="What is 2+2?",
        acceptance="the answer is 4",
        verify=lambda a: a.strip() == "4",
        reference_solution="4",
        proposer="reference-scenario",
    )


def _scenario_proposer():
    """Deterministic reference scenario: one of each degenerate strategy.

    Round 1 admits a well-formed challenge; rounds 2-4 are refused by one
    distinct gate each (unsatisfiable reference, independent solver fails,
    vacuous verifier); round 5 is a proposer crash. This is the exact shape
    the measured artifact in SPEC-282 records.
    """
    drafts = [
        _good_draft(),
        # Unsatisfiable on paper: its own reference solution fails its verifier.
        ChallengeDraft(
            statement="What is 2+2?",
            acceptance="the answer is 4",
            verify=lambda a: a.strip() == "4",
            reference_solution="5",
            proposer="reference-scenario",
        ),
        # Vacuous verifier: a trivial baseline passes it.
        ChallengeDraft(
            statement="Say anything.",
            acceptance="any answer counts",
            verify=lambda a: True,
            reference_solution="4",
            proposer="reference-scenario",
        ),
        # Unsolvable in practice: the independent solver cannot solve it.
        ChallengeDraft(
            statement="What is 2+3?",
            acceptance="the answer is 5",
            verify=lambda a: a.strip() == "5",
            reference_solution="5",
            proposer="reference-scenario",
        ),
    ]

    def propose() -> ChallengeDraft:
        if not drafts:
            raise RuntimeError("proposer exhausted")
        return drafts.pop(0)

    return propose


async def _reference_solver(draft: ChallengeDraft) -> str:
    """Independent solver: answers '4' to everything."""
    return "4"


async def _measure(genome: PipelineGenome):
    return await compare_lanes(
        genome,
        [genome],
        propose=_scenario_proposer(),
        solver=_reference_solver,
        baseline_answer="",
        budget=LaneBudget(generation_rounds=RECORDED["generation_rounds"]),
    )


class TestMeasuredLaneComparison:
    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-10")
    async def test_external_capability_is_measured_unchanged(self):
        """AC-10: identical external evidence measures an identical capability —
        the curriculum lane reports 'no improvement' as a measured result."""
        report = await _measure(_genome({"proxy_ifeval": 0.9}))
        assert report.external_only.lane == EXTERNAL_ONLY_LANE
        assert report.curriculum_enabled.lane == CURRICULUM_ENABLED_LANE
        assert report.capability_delta == 0.0
        assert report.capability_verdict == "no improvement"
        assert report.external_only.capability == report.curriculum_enabled.capability
        assert report.external_only.fitness_total == report.curriculum_enabled.fitness_total
        # External evaluation remains the promotion gate on both lanes.
        assert report.external_only.passed_hard_gate
        assert report.curriculum_enabled.passed_hard_gate

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-10")
    async def test_measured_numbers_match_the_recorded_artifact(self):
        """AC-10: cost and admission numbers equal SPEC-282's recorded run."""
        report = await _measure(_genome({"proxy_ifeval": 0.9}))
        cur = report.curriculum_enabled
        assert report.admission_yield == pytest.approx(RECORDED["admission_yield"])
        assert cur.cost_probes["generator_proposals"] == RECORDED["generator_proposals"]
        assert cur.cost_probes["solver_attempts"] == RECORDED["solver_attempts"]
        assert cur.cost_probes["gate_probes"] == RECORDED["gate_probes"]
        assert cur.cost_probes["external_evaluations"] == 1
        assert cur.failures["refused_by/reference_solves"] == 1
        assert cur.failures["refused_by/solver_solves"] == 1
        assert cur.failures["refused_by/baseline_fails"] == 1
        assert cur.failures["proposer_errors"] == RECORDED["proposer_errors"]

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-10")
    async def test_accepted_challenges_are_retained_in_the_report(self):
        """AC-10: the report carries each accepted challenge's provenance record."""
        report = await _measure(_genome({"proxy_ifeval": 0.9}))
        assert len(report.curriculum_records) == RECORDED["admitted"]
        record = report.curriculum_records[0]
        assert record["generator_version"]
        assert record["validator_version"]
        assert record["content_hash"].startswith("sha256:")
        assert len(record["validation"]) == 4
        assert all(g["executed"] and g["passed"] for g in record["validation"])

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-10")
    async def test_summary_renders_the_measured_numbers(self):
        """AC-10: the rendered summary states the delta and the verdict."""
        report = await _measure(_genome({"proxy_ifeval": 0.9}))
        assert "capability_delta   : +0.000000 (no improvement)" in report.summary
        assert "external evaluation remains the promotion gate" in report.summary
        assert "generator_proposals: external_only=0 curriculum_enabled=5" in (report.summary)
        assert "accepted challenges retained: 1" in report.summary

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-10")
    async def test_verdict_is_measured_not_assumed(self, monkeypatch):
        """AC-10: an external capability movement flips the verdict — the
        harness measures the delta, it does not hardcode 'no improvement'."""
        real = compute_fitness
        calls = {"n": 0}

        def shifting(genome, population, objective):
            calls["n"] += 1
            comps = real(genome, population, objective)
            if calls["n"] == 2:  # the curriculum lane's re-measurement
                return comps.model_copy(update={"capability_score": comps.capability_score + 0.25})
            return comps

        monkeypatch.setattr(lane_comparison, "compute_fitness", shifting)
        report = await _measure(_genome({"proxy_ifeval": 0.9}))
        assert report.capability_delta == pytest.approx(0.25)
        assert report.capability_verdict == "improvement"

        calls["n"] = 0

        def dropping(genome, population, objective):
            calls["n"] += 1
            comps = real(genome, population, objective)
            if calls["n"] == 2:
                return comps.model_copy(update={"capability_score": comps.capability_score - 0.1})
            return comps

        monkeypatch.setattr(lane_comparison, "compute_fitness", dropping)
        report = await _measure(_genome({"proxy_ifeval": 0.9}))
        assert report.capability_delta == pytest.approx(-0.1)
        assert report.capability_verdict == "regression"

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-10")
    async def test_unchanged_evidence_measures_identically(self):
        """AC-10: with no degenerate drafts the lanes still cost differently —
        the curriculum lane spends the generation budget, the control does not."""

        async def only_good() -> ChallengeDraft:
            return _good_draft()

        genome = _genome({"proxy_ifeval": 0.9})
        report = await compare_lanes(
            genome,
            [genome],
            propose=only_good,
            solver=_reference_solver,
            baseline_answer="",
            budget=LaneBudget(generation_rounds=3),
        )
        assert report.admission_yield == pytest.approx(1.0)
        assert report.curriculum_enabled.failures == {}
        assert report.external_only.cost_probes == {"external_evaluations": 1}
        assert report.curriculum_enabled.cost_probes["generator_proposals"] == 3
        assert report.curriculum_enabled.cost_probes["solver_attempts"] == 3
        assert report.curriculum_enabled.cost_probes["gate_probes"] == 12


class TestLaneBudget:
    @pytest.mark.ac("SPEC-282/AC-10")
    def test_zero_rounds_is_refused(self):
        """AC-10: an unbudgeted (or negatively budgeted) lane is not a run."""
        with pytest.raises(ValueError, match="generation_rounds"):
            LaneBudget(generation_rounds=0)
        with pytest.raises(ValueError, match="generation_rounds"):
            LaneBudget(generation_rounds=-2)
