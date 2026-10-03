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

from maistro_evolve.benchmarks import calibration as calibration_module
from maistro_evolve.benchmarks.bfcl import _score_tool_call
from maistro_evolve.benchmarks.calibration import (
    _bfcl_narration,
    _gaia_narration,
    _ragas_narration,
    _tau_narration,
    calibrate_proxy_scorers,
    strict_judge,
)
from maistro_evolve.benchmarks.datasets import (
    BFCL_SAMPLES,
    GAIA_SAMPLES,
    RAGAS_SAMPLES,
    TAU_BENCH_SAMPLES,
)
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


#: Every query the calibration responders match on, across all four runners.
#: A message carrying none of these is what the responder fallbacks exist for.
_KNOWN_QUERIES = frozenset(
    [s["query"] for s in BFCL_SAMPLES]
    + [s["conversation"][-1]["content"] for s in TAU_BENCH_SAMPLES]
    + [s["question"] for s in GAIA_SAMPLES]
    + [s["question"] for s in RAGAS_SAMPLES]
)

#: An unmatched message exercises the closures' total-function fallback.
_UNMATCHED = "follow-up: also email me a carrier pigeon"


def _scrub_fixture_queries(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rewrite every known fixture query out of the outgoing user turns.

    The calibration responders substring-match fixture queries in the
    conversation; scrubbing them is what sends a runner's real message
    stream down the fallback arc, without guessing runner internals.
    """
    return [
        {
            **message,
            "content": _UNMATCHED,
        }
        if message.get("role") == "user"
        and any(query in (message.get("content") or "") for query in _KNOWN_QUERIES)
        else message
        for message in messages
    ]


class TestResponderFallbacksAreTotal:
    """A runner message matching no fixture query gets the safe default
    reply — not a KeyError and not a partial match — and the calibration
    report still completes over the real runners."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("scorer", "runner_name"),
        [
            ("proxy_bfcl", "run_bfcl"),
            ("proxy_tau_bench", "run_tau_bench"),
            ("proxy_gaia", "run_gaia"),
            ("proxy_ragas", "run_ragas"),
        ],
    )
    async def test_unmatched_message_earns_the_fallback_reply(
        self, monkeypatch: pytest.MonkeyPatch, scorer: str, runner_name: str
    ) -> None:
        genome = make_genome()
        replies: list[str] = []

        real_runner = getattr(calibration_module, runner_name)

        async def scrubbing_runner(genome: Any, llm_call: Any, **kwargs: Any) -> Any:
            async def probing(messages: list[dict[str, Any]], **kw: Any) -> str:
                reply = await llm_call(_scrub_fixture_queries(messages), **kw)
                replies.append(reply)
                return reply

            return await real_runner(genome, probing, **kwargs)

        monkeypatch.setattr(
            f"maistro_evolve.benchmarks.calibration.{runner_name}", scrubbing_runner
        )
        report = await calibrate_proxy_scorers(genome, None)

        # The fallback arc really executed: at least one reply came back as
        # the closure's safe default rather than a fixture response.
        assert replies, f"{runner_name} never invoked its candidate"
        assert any("not sure" in reply or "cannot proceed" in reply for reply in replies), (
            f"{runner_name} answered every scrubbed message without its fallback"
        )
        # A fallback answer is not a verified outcome: the scorer still
        # completes and reports over the whole sample set.
        assert report["scorers"][scorer]["narration_fixtures"] > 0
