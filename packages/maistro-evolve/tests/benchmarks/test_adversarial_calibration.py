"""Adversarial narration fixtures + calibration report (#384).

The acceptance criteria for #384 require that adversarial fixtures which
maximize narration while doing no work score zero for execution, and that
proxy scores are calibrated against held-out real outcomes with a reported
false-positive rate. ``benchmarks/calibration.py`` implements the harness;
this module pins its guarantees with deterministic stubs:

- narration-only responses earn nothing on the execution scorers
  (``proxy_bfcl``, ``proxy_tau_bench``) — structured calls only;
- narration quoting the expected answer earns nothing unjudged on the
  judge-mediated scorers (``proxy_gaia``, ``proxy_ragas``) and a strict
  judge verifies the rest;
- verified fixtures (real structured calls, exact answers, grounded answers)
  still score — calibration against held-out real outcomes, not just
  universal zeroing;
- the report exposes ``narration_false_positive_rate`` per scorer.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro_evolve.benchmarks.bfcl import _score_tool_call
from maistro_evolve.benchmarks.calibration import (
    _bfcl_narration,
    _gaia_narration,
    _ragas_narration,
    _tau_narration,
    calibrate_proxy_scorers,
    strict_judge,
)
from maistro_evolve.benchmarks.datasets import BFCL_SAMPLES, GAIA_SAMPLES
from maistro_evolve.benchmarks.gaia import _exact_match_score
from maistro_evolve.benchmarks.tau_bench import _score_tool_usage

from .conftest import make_genome


class TestNarrationFixturesAreMaximallyGameable:
    """The fixtures really do contain everything the old fallbacks matched
    on — so a zero score is a property of the new scorers, not weak fixtures."""

    def test_gaia_narration_quotes_expected_answer_but_is_not_exact(self):
        # Old scorer: 0.9 raw-substring, above the old 0.7 judge-skip.
        for sample in GAIA_SAMPLES:
            narration = _gaia_narration(sample["answer"])
            assert sample["answer"] in narration
            assert _exact_match_score(narration, sample["answer"]) == 0.0

    def test_bfcl_narration_names_tool_and_params_without_a_call(self):
        sample = BFCL_SAMPLES[0]
        narration = _bfcl_narration(sample["expected_name"], sample["expected_params"])
        assert sample["expected_name"] in narration
        # No JSON object anywhere in it — nothing to verify as a call.
        assert "{" not in narration
        assert _score_tool_call(narration, sample) == 0.0

    def test_ragas_narration_carries_every_expected_word(self):
        narration = _ragas_narration("Gustave Eiffel designed the tower")
        for word in ["gustave", "eiffel", "designed", "the", "tower"]:
            assert word in narration.lower()

    def test_tau_narration_mentions_tools_affirmatively_and_negated(self):
        narration = _tau_narration(["refund_order", "get_order_details"])
        assert "refund_order" in narration
        assert "cannot invoke refund_order" in narration


class TestStrictJudge:
    async def test_reject_mode_rejects_everything(self) -> None:
        judge = strict_judge(False)
        assert await judge([{"role": "user", "content": "anything"}]) == "0"

    async def test_approve_mode_approves(self) -> None:
        judge = strict_judge(True)
        assert await judge([{"role": "user", "content": "grounded answer"}]) == "10"


class TestCalibrationReport:
    @pytest.mark.asyncio
    async def test_all_scorers_report_zero_narration_fpr_and_full_verified_rate(
        self,
    ) -> None:
        """The #384 headline: narration doing no work scores zero, verified
        real outcomes still score, and the false-positive rate is reported."""
        genome = make_genome()
        report = await calibrate_proxy_scorers(genome, None)

        assert report["calibration"] == "adversarial-narration-v1"
        assert set(report["scorers"]) == {
            "proxy_bfcl",
            "proxy_tau_bench",
            "proxy_gaia",
            "proxy_ragas",
        }
        for name, scorer in report["scorers"].items():
            assert scorer["narration_false_positive_rate"] == 0.0, (
                f"{name} credited narration-only output"
            )
            assert scorer["narration_false_positives_implied"] == 0
            assert scorer["verified_positive_rate"] == 1.0, (
                f"{name} stopped crediting verified real outcomes"
            )
            assert scorer["verified_failures_implied"] == 0
            assert scorer["narration_fixtures"] > 0

    @pytest.mark.asyncio
    async def test_execution_scorer_fpr_reported_per_benchmark(self) -> None:
        """The bfcl entry of the report is a real measurement over the real
        sample set, not a hardcoded zero: the fixture count tracks the
        dataset it probed."""
        genome = make_genome()
        report = await calibrate_proxy_scorers(genome, None)
        bfcl = report["scorers"]["proxy_bfcl"]
        assert bfcl["narration_fixtures"] == len(BFCL_SAMPLES)
        assert bfcl["verified_fixtures"] == len(BFCL_SAMPLES)

    @pytest.mark.asyncio
    async def test_report_surfaces_a_reintroduced_mention_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard the guard: the report measures the runners — it does not
        hardcode zeros. A scorer that regains a mention fallback (simulated
        here by a runner that pays 0.25 for any narration) shows up as a
        nonzero ``narration_false_positive_rate``."""
        genome = make_genome()

        async def gameable_runner(genome: Any, llm_call: Any) -> Any:
            from maistro_evolve.types import EvalResult

            return EvalResult(
                benchmark="proxy_bfcl",
                score=0.25,  # the old prose-mention fallback's exact bounty
                cost_usd=0.0,
                duration_seconds=0.0,
                samples_evaluated=1,
                metadata={"fidelity": "proxy"},
            )

        monkeypatch.setattr("maistro_evolve.benchmarks.calibration.run_bfcl", gameable_runner)
        report = await calibrate_proxy_scorers(genome, None)

        bfcl = report["scorers"]["proxy_bfcl"]
        assert bfcl["narration_false_positive_rate"] == 0.25
        assert bfcl["narration_false_positives_implied"] > 0
        # The other scorers remain measured, not tarred by the regression.
        assert report["scorers"]["proxy_gaia"]["narration_false_positive_rate"] == 0.0


class TestTauNarrationZeroAtUnitLevel:
    """Direct pins over the tau_bench scoring unit for the fixture shapes."""

    def test_affirmative_and_negated_prose_is_zero(self):
        sample = {
            "expected_tool_calls": ["refund_order"],
        }
        narration = (
            "I will use refund_order. Actually, I cannot invoke refund_order, "
            "so let me explain what it would return."
        )
        assert _score_tool_usage(narration, sample) == 0.0

    def test_structured_call_still_scores(self):
        sample = {"expected_tool_calls": ["refund_order"]}
        response = '{"name": "refund_order", "parameters": {"order_id": "1"}}'
        assert _score_tool_usage(response, sample) == 1.0
