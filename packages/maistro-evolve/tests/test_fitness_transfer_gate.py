"""Transfer inversion as a hard fitness gate (#104 M4-G / SPEC-281 §2).

A harness that helps a weak model but *damages* a frontier model is not a
better harness; it is a harness that is unsafe to promote. The gate is
fail-closed in two directions: a measured inversion disqualifies, and a
promotion candidate with no transfer evidence at all is blocked (stale
evidence passes; absent evidence does not).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro_evolve.cycle import EvolutionCycle
from maistro_evolve.fitness import compute_fitness
from maistro_evolve.lift_matrix import TRANSFER_EPSILON
from maistro_evolve.population import PopulationStore
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome

PASSING_SCORES = {"proxy_ifeval": 0.9, "proxy_bfcl": 0.9}


def _genome(
    eval_scores=None,
    harness_params=None,
    *,
    approved: bool = False,
) -> PipelineGenome:
    return PipelineGenome(
        id="test-g1",
        name="test",
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="gpt-4",
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
        eval_scores=eval_scores if eval_scores is not None else PASSING_SCORES,
        harness_params=harness_params or {},
        approved_for_promotion=approved,
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def _transfer(value: float, *, stale: bool = False) -> dict:
    return {"transfer": value, "transfer_stale": stale}


class TestInversionGate:
    def test_a_measured_inversion_disqualifies_the_genome(self) -> None:
        genome = _genome(
            harness_params={"transfer_by_benchmark": {"proxy_ifeval": _transfer(-0.5)}}
        )
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is False
        assert any("inverts on the frontier model" in f for f in fitness.gate_failures)

    def test_a_small_loss_inside_the_epsilon_is_not_an_inversion(self) -> None:
        genome = _genome(
            harness_params={
                "transfer_by_benchmark": {
                    "proxy_ifeval": _transfer(-TRANSFER_EPSILON / 2),
                }
            }
        )
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is True
        assert fitness.gate_failures == []

    def test_a_stale_inversion_still_disqualifies(self) -> None:
        """Stale evidence is evidence: a carried-forward inversion counts."""
        genome = _genome(
            harness_params={"transfer_by_benchmark": {"proxy_ifeval": _transfer(-0.4, stale=True)}}
        )
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is False
        assert any("stale measurement" in f for f in fitness.gate_failures)

    def test_a_positive_transfer_passes(self) -> None:
        genome = _genome(harness_params={"transfer_by_benchmark": {"proxy_ifeval": _transfer(0.2)}})
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is True


class TestAbsentEvidence:
    def test_a_promotion_candidate_without_transfer_evidence_is_blocked(self) -> None:
        genome = _genome(approved=True)
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is False
        assert any("lacks transfer evidence" in f for f in fitness.gate_failures)

    def test_a_promotion_candidate_with_stale_transfer_evidence_passes(self) -> None:
        genome = _genome(
            approved=True,
            harness_params={
                "transfer_by_benchmark": {
                    "proxy_ifeval": _transfer(0.1, stale=True),
                    "proxy_bfcl": _transfer(0.1, stale=True),
                }
            },
        )
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is True

    def test_a_promotion_candidate_missing_one_benchmark_is_blocked(self) -> None:
        genome = _genome(
            approved=True,
            harness_params={"transfer_by_benchmark": {"proxy_ifeval": _transfer(0.1)}},
        )
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is False
        assert any("proxy_bfcl" in f for f in fitness.gate_failures)

    def test_a_non_promotion_genome_is_not_blocked_for_missing_evidence(self) -> None:
        """Only promotion candidates need the evidence to exist."""
        genome = _genome(approved=False)
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is True


class TestMalformedEvidence:
    def test_a_malformed_transfer_map_is_refused(self) -> None:
        genome = _genome(harness_params={"transfer_by_benchmark": [0.1]})
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is False
        assert any("must be a mapping" in f for f in fitness.gate_failures)

    def test_a_transfer_entry_without_a_value_is_refused(self) -> None:
        genome = _genome(
            harness_params={"transfer_by_benchmark": {"proxy_ifeval": {"transfer_stale": True}}}
        )
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is False
        assert any("no 'transfer' value" in f for f in fitness.gate_failures)

    def test_a_non_numeric_transfer_is_refused(self) -> None:
        genome = _genome(
            harness_params={"transfer_by_benchmark": {"proxy_ifeval": {"transfer": "good"}}}
        )
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is False
        assert any("not a number" in f for f in fitness.gate_failures)

    @pytest.mark.parametrize(
        "epsilon",
        [0.5, float("nan"), float("inf"), -0.1, True, None, "invalid"],
    )
    def test_a_candidate_cannot_relax_or_corrupt_the_transfer_tolerance(self, epsilon) -> None:
        genome = _genome(
            harness_params={
                "transfer_by_benchmark": {"proxy_ifeval": _transfer(-0.4)},
                "transfer_epsilon": epsilon,
            }
        )
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is False
        assert fitness.total == 0.0
        assert any("transfer_epsilon" in failure for failure in fitness.gate_failures)

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 1.1, -1.1])
    def test_non_finite_or_impossible_transfer_is_not_evidence(self, value) -> None:
        genome = _genome(
            harness_params={"transfer_by_benchmark": {"proxy_ifeval": _transfer(value)}}
        )
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is False
        assert fitness.total == 0.0
        assert any("transfer" in failure for failure in fitness.gate_failures)

    def test_the_epsilon_can_be_tightened_per_genome(self) -> None:
        genome = _genome(
            harness_params={
                "transfer_by_benchmark": {"proxy_ifeval": _transfer(-0.01)},
                "transfer_epsilon": 0.005,
            }
        )
        fitness = compute_fitness(genome, [genome])
        assert fitness.passed_hard_gate is False
        assert any("inverts on the frontier model" in f for f in fitness.gate_failures)


class TestTransferEvidenceIdentity:
    @pytest.mark.parametrize("changed_input", ["transfer", "epsilon", "approval"])
    def test_gate_inputs_participate_in_the_evidence_hash(self, changed_input) -> None:
        genome = _genome(
            harness_params={"transfer_by_benchmark": {"proxy_ifeval": _transfer(-0.01)}}
        )
        before = compute_fitness(genome, [genome])
        assert before.passed_hard_gate is True
        if changed_input == "transfer":
            genome.harness_params["transfer_by_benchmark"]["proxy_ifeval"] = _transfer(-0.5)
        elif changed_input == "epsilon":
            genome.harness_params["transfer_epsilon"] = 0.005
        else:
            genome.approved_for_promotion = True
        after = compute_fitness(genome, [genome])
        assert after.passed_hard_gate is False
        assert after.total == 0.0
        assert after.evidence_hash != before.evidence_hash

    def test_refreshing_transfer_is_not_unexplained_fitness_drift(self) -> None:
        genome = _genome(harness_params={"transfer_by_benchmark": {"proxy_ifeval": _transfer(0.2)}})
        population = PopulationStore()
        population.add(genome)
        cycle = EvolutionCycle()
        cycle._compute_all_fitness(population)
        before = population.get(genome.id)
        assert before is not None and before.fitness_score > 0
        before.harness_params["transfer_by_benchmark"]["proxy_ifeval"] = _transfer(-0.5)
        population.add(before)
        cycle._compute_all_fitness(population)
        after = population.get(genome.id)
        assert after is not None and after.fitness_score == 0.0
