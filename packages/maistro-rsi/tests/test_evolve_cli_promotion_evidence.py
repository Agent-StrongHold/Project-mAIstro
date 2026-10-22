"""The live-evolution run summary surfaces promotion evidence (#384/#853).

After ``maistro_rsi run`` finishes, the champion it would promote is
reported with two evidence surfaces, both operator-facing and neither
gating:

1. the per-benchmark verified-evidence trail from
   ``PopulationStore.champion_provenance()`` — a score without an evidence
   record reads "unverified", never silently trusted;
2. the offline adversarial calibration of the proxy scorers (narration
   false-positive rate / verified positive rate) — deterministic, no live
   model contacted.

A calibration failure is reported and the summary still completes: the
promotion semantics stay in fitness.py (#853), so evidence collection must
never fail the run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from maistro_evolve.population import PopulationStore
from maistro_evolve.promotion import objective_version
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome
from maistro_rsi import __main__ as entry


def _genome(name: str = "champ") -> PipelineGenome:
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


def _scored_store() -> tuple[PopulationStore, PipelineGenome]:
    store = PopulationStore()
    champ = _genome("champ")
    champ.fitness_score = 91.0
    champ.eval_scores = {"code_rsi": 0.9, "proxy_bfcl": 0.95}
    champ.eval_evidence = {
        "code_rsi": "patch-test-cycle",
        "proxy_bfcl": "structured-call-match",
    }
    # #854 selection eligibility: champion_provenance only names champions the
    # shared eligibility contract would select, so the fixture carries the
    # complete evidence legs (samples, objective stamp, currency) — same
    # pattern as test_champion_provenance.py.
    benchmarks = sorted(champ.eval_scores)
    champ.harness_params.update(
        {
            "eval_samples": dict.fromkeys(benchmarks, 2),
            "eval_history": {b: [champ.eval_scores[b], champ.eval_scores[b]] for b in benchmarks},
            "objective_version": objective_version(benchmarks),
            "evidence_cycle": 1,
        }
    )
    store.add(champ)
    return store, champ


class TestChampionEvidencePrint:
    def test_names_score_and_evidence_per_benchmark(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store, champ = _scored_store()

        entry._print_promotion_evidence(store, champ)

        out = capsys.readouterr().out
        assert "champion evidence:" in out
        assert "code_rsi: score=0.9 evidence=patch-test-cycle" in out
        assert "proxy_bfcl: score=0.95 evidence=structured-call-match" in out

    def test_score_without_evidence_record_reads_unverified(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store, champ = _scored_store()
        champ.eval_evidence = {}
        store.add(champ)  # same id: overwrites the stored copy

        entry._print_promotion_evidence(store, champ)

        out = capsys.readouterr().out
        assert "code_rsi: score=0.9 evidence=unverified" in out
        assert "proxy_bfcl: score=0.95 evidence=unverified" in out

    def test_no_provenance_skips_the_block_calibration_still_prints(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Defensive arc: a store with no scored genomes has no provenance
        # section (the caller only reaches here via a scored champion), but
        # the calibration evidence is champion-independent enough to print.
        store = PopulationStore()
        champ = _genome("unscored")

        entry._print_promotion_evidence(store, champ)

        out = capsys.readouterr().out
        assert "champion evidence:" not in out
        assert "proxy-scorer calibration (adversarial-narration-v1):" in out


class TestCalibrationEvidencePrint:
    def test_report_is_printed_per_scorer(self, capsys: pytest.CaptureFixture[str]) -> None:
        store, champ = _scored_store()

        entry._print_promotion_evidence(store, champ)

        out = capsys.readouterr().out
        assert "proxy-scorer calibration (adversarial-narration-v1):" in out
        for scorer in ("proxy_bfcl", "proxy_tau_bench", "proxy_gaia", "proxy_ragas"):
            assert f"  {scorer}: narration_fpr=" in out
        # The deterministic fixtures pin the no-leak property end to end.
        assert "narration_fpr=0.0" in out

    def test_calibration_failure_is_reported_and_never_raises(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(genome: Any, llm_call: Any) -> dict[str, Any]:
            raise RuntimeError("gateway down")

        monkeypatch.setattr("maistro_evolve.benchmarks.calibration.calibrate_proxy_scorers", _boom)
        store, champ = _scored_store()

        entry._print_promotion_evidence(store, champ)  # must not raise

        out = capsys.readouterr().out
        assert "calibration evidence: unavailable (gateway down)" in out
