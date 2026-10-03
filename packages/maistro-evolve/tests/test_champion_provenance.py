"""Champion-selection provenance over verified evidence (#384).

Definition of done for #384: champion selection provenance identifies
verified evidence for each score. Three links are pinned here:

1. ``harness.evidence_method`` extracts the runners' ``metadata["evidence"]``
   into the compact per-benchmark method string, defaulting to "unverified"
   (absence is provenance, never silently dropped);
2. ``EvolutionCycle`` folds that string into ``PipelineGenome.eval_evidence``
   alongside the score it describes;
3. ``PopulationStore.champion_provenance()`` exposes, for the max-fitness
   champion, every benchmark score with the verified method behind it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from maistro_evolve.cycle import EvolutionCycle
from maistro_evolve.harness import EvalHarness, evidence_method
from maistro_evolve.population import PopulationStore
from maistro_evolve.promotion import objective_version
from maistro_evolve.types import DAGTopology, EvalResult, EvalWeights, NodeGenome, PipelineGenome


def _genome(name: str = "test") -> PipelineGenome:
    return PipelineGenome(
        id=f"g-{name}",
        name=name,
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
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def _result(benchmark: str, score: float, evidence: dict[str, Any] | None) -> EvalResult:
    metadata: dict[str, Any] = {"fidelity": "proxy"}
    if evidence is not None:
        metadata["evidence"] = evidence
    return EvalResult(
        benchmark=benchmark,
        score=score,
        cost_usd=0.0,
        duration_seconds=0.0,
        samples_evaluated=1,
        metadata=metadata,
    )


class TestEvidenceMethod:
    def test_dict_evidence_extracts_method(self):
        assert (
            evidence_method(_result("proxy_bfcl", 1.0, {"method": "structured-call-match"}))
            == "structured-call-match"
        )

    def test_dict_evidence_without_method_is_unverified(self):
        assert evidence_method(_result("proxy_bfcl", 1.0, {"something": "else"})) == "unverified"

    def test_string_evidence_passes_through(self):
        assert evidence_method(_result("proxy_bfcl", 1.0, "llm-judge")) == "llm-judge"

    def test_missing_evidence_is_unverified_not_dropped(self):
        assert evidence_method(_result("proxy_bfcl", 1.0, None)) == "unverified"

    def test_empty_string_evidence_is_unverified(self):
        assert evidence_method(_result("proxy_bfcl", 1.0, "")) == "unverified"


class TestCycleFoldsEvidence:
    async def test_scores_and_evidence_fold_together(self):
        harness = EvalHarness()
        harness._benchmarks.clear()

        async def runner(genome: PipelineGenome, llm_call: object) -> EvalResult:
            return _result("proxy_bfcl", 0.9, {"method": "structured-call-match"})

        harness.register_benchmark("proxy_bfcl", runner)
        cycle = EvolutionCycle(harness=harness)
        genome = _genome()
        population = PopulationStore()
        population.add(genome)

        await cycle._evaluate_unevaluated(
            population,
            type(
                "_Cfg",
                (),
                {"eval_batch_size": 4, "eval_ema_alpha": 1.0, "target_benchmarks": ["proxy_bfcl"]},
            )(),
            llm_call=None,
        )

        stored = population.get("g-test")
        assert stored is not None
        assert stored.eval_scores["proxy_bfcl"] == 0.9
        assert stored.eval_evidence["proxy_bfcl"] == "structured-call-match"

    async def test_result_without_evidence_records_unverified(self):
        harness = EvalHarness()
        harness._benchmarks.clear()

        async def runner(genome: PipelineGenome, llm_call: object) -> EvalResult:
            return _result("proxy_bfcl", 0.9, None)

        harness.register_benchmark("proxy_bfcl", runner)
        cycle = EvolutionCycle(harness=harness)
        genome = _genome()
        population = PopulationStore()
        population.add(genome)

        await cycle._evaluate_unevaluated(
            population,
            type(
                "_Cfg",
                (),
                {"eval_batch_size": 4, "eval_ema_alpha": 1.0, "target_benchmarks": ["proxy_bfcl"]},
            )(),
            llm_call=None,
        )

        stored = population.get("g-test")
        assert stored is not None
        assert stored.eval_evidence["proxy_bfcl"] == "unverified"


class TestChampionProvenance:
    @staticmethod
    def _stamp_selection_evidence(genome: PipelineGenome) -> PipelineGenome:
        """Complete the #854 selection-evidence legs (samples, objective stamp,
        evidence currency). Since develop's #854 reconciliation,
        ``get_champion`` only selects ELIGIBLE genomes, so a provenance fixture
        must carry the evidence that makes it selectable — the same complete-
        evidence pattern ``test_rsi_safety.py`` uses for the promotion gate.
        The provenance assertions below stay about #384: per-score evidence
        naming on the genome that WAS selected.
        """
        benchmarks = sorted(genome.eval_scores)
        genome.harness_params.update(
            {
                "eval_samples": {b: 2 for b in benchmarks},
                "eval_history": {
                    b: [genome.eval_scores[b], genome.eval_scores[b]] for b in benchmarks
                },
                "objective_version": objective_version(benchmarks),
                "evidence_cycle": 1,
            }
        )
        return genome

    def test_none_when_no_scored_genomes(self):
        store = PopulationStore()
        assert store.champion_provenance() is None

    def test_champion_provenance_names_evidence_per_score(self):
        store = PopulationStore()

        champion = _genome("champ")
        champion.fitness_score = 91.0
        champion.eval_scores = {"proxy_bfcl": 0.95, "proxy_gaia": 0.9}
        champion.eval_evidence = {
            "proxy_bfcl": "structured-call-match",
            "proxy_gaia": "exact-match+llm-judge",
        }
        store.add(self._stamp_selection_evidence(champion))

        loser = _genome("loser")
        loser.fitness_score = 10.0
        loser.eval_scores = {"proxy_bfcl": 0.3}
        loser.eval_evidence = {"proxy_bfcl": "structured-call-match"}
        store.add(self._stamp_selection_evidence(loser))

        provenance = store.champion_provenance()
        assert provenance is not None
        assert provenance["genome_id"] == "g-champ"
        assert provenance["fitness_score"] == 91.0
        assert provenance["benchmarks"]["proxy_bfcl"] == {
            "score": 0.95,
            "evidence": "structured-call-match",
        }
        assert provenance["benchmarks"]["proxy_gaia"] == {
            "score": 0.9,
            "evidence": "exact-match+llm-judge",
        }
        # The loser's evidence never bleeds into the champion's record.
        assert set(provenance["benchmarks"]) == {"proxy_bfcl", "proxy_gaia"}

    def test_score_without_evidence_reads_unverified(self):
        store = PopulationStore()
        genome = _genome("legacy")
        genome.fitness_score = 50.0
        genome.eval_scores = {"proxy_ragas": 0.8}
        self._stamp_selection_evidence(genome)
        # Pre-#384 genome: folded before evidence existed — no record.
        store.add(genome)

        provenance = store.champion_provenance()
        assert provenance is not None
        assert provenance["benchmarks"]["proxy_ragas"] == {
            "score": 0.8,
            "evidence": "unverified",
        }
