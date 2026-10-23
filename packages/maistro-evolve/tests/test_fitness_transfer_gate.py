"""Transfer inversion as a hard fitness gate (#104 M4-G / SPEC-281 §2).

A harness that helps a weak model but *damages* a frontier model is not a
better harness; it is a harness that is unsafe to promote. The gate is
fail-closed in two directions: a measured inversion disqualifies, and a
promotion candidate with no transfer evidence at all is blocked (stale
evidence passes; absent evidence does not).
"""

from __future__ import annotations

from datetime import UTC, datetime

from maistro_evolve.fitness import compute_fitness
from maistro_evolve.lift_matrix import TRANSFER_EPSILON
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
