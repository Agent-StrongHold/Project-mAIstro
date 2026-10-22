from __future__ import annotations

from typing import Any

import pytest

from maistro_evolve.benchmarks.gaia import (
    _exact_match_score,
    _judge_answer,
    run_gaia,
)

from .conftest import make_genome


class TestExactMatchScore:
    """#384: structural exact match only — every fuzzy tier is gone.

    The pre-#384 scorer awarded 0.9 for a raw substring, 0.85 for equal
    digit-sets and up to 0.7 for word overlap — any of which cleared the old
    >=0.7 threshold that skipped the judge. These tests pin the replacement:
    only a normalized-equal (or numerically equal) response earns the point;
    everything else is 0.0 and must go to the judge.
    """

    def test_exact_match_case_insensitive_and_stripped(self):
        assert _exact_match_score("  Au  ", "au") == 1.0

    def test_punctuation_and_whitespace_normalization_still_exact(self):
        # Formatting-only differences are not substance: punctuation and
        # whitespace collapse away, so these remain verified exact answers.
        assert _exact_match_score("Au.", "au") == 1.0
        assert _exact_match_score("the  berlin  wall", "The Berlin Wall") == 1.0

    def test_numeric_equivalence_is_exact(self):
        # Both sides parse as the same number — equality of value, not of a
        # substring, so this is verified rather than narrated.
        assert _exact_match_score("42.0", "42") == 1.0

    def test_substring_quoted_in_prose_earns_nothing(self):
        # The old 0.9 tier: "the answer is au" contains "au". Now it is
        # unverified narration — 0.0, routed to the judge by run_gaia.
        assert _exact_match_score("the answer is au", "au") == 0.0

    def test_digit_set_match_earns_nothing(self):
        # The old 0.85 tier: same digit-set {"90"} without the answer itself.
        assert _exact_match_score("the value is 90, confirmed 90", "90 90") == 0.0

    def test_word_overlap_earns_nothing(self):
        # The old 0.35 (1/2 overlap * 0.7): sharing a word is not answering.
        assert _exact_match_score("george smith wrote it", "george orwell") == 0.0

    def test_word_overlap_zero(self):
        assert _exact_match_score("completely unrelated text", "george orwell") == 0.0

    def test_empty_expected_earns_nothing(self):
        # A broken sample (empty expected answer) fails closed — the old code
        # scored 0.9 here via a vacuous substring match.
        assert _exact_match_score("some response", "") == 0.0

    def test_both_empty_earns_nothing(self):
        # Saying nothing is not answering: 0.0, not the old free 1.0.
        assert _exact_match_score("", "") == 0.0


class TestJudgeAnswer:
    async def test_returns_judge_score_on_success(self) -> None:
        async def fake_llm_call(messages: list[dict[str, str]], **kwargs: Any) -> str:
            return "Score: 8"

        score = await _judge_answer("Q?", "resp", "expected", fake_llm_call)
        assert score == 0.8

    async def test_returns_zero_when_llm_call_raises(self) -> None:
        async def fake_llm_call(messages: list[dict[str, str]], **kwargs: Any) -> str:
            raise ValueError("boom")

        score = await _judge_answer("Q?", "resp", "expected", fake_llm_call)
        assert score == 0.0


class TestRunGaia:
    async def test_llm_call_none_raises(self) -> None:
        genome = make_genome()
        with pytest.raises(ValueError, match="requires an llm_call"):
            await run_gaia(genome, None)

    async def test_exact_match_path_no_judge_call(self) -> None:
        genome = make_genome()

        # Build a llm_call that looks up the expected answer for the given question,
        # so every sample scores an exact match.
        from maistro_evolve.benchmarks.datasets import GAIA_SAMPLES

        question_to_answer = {s["question"]: s["answer"] for s in GAIA_SAMPLES}

        async def exact_llm_call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            user_content = messages[-1]["content"]
            for question, answer in question_to_answer.items():
                if question in user_content:
                    return answer
            raise AssertionError("question not found in prompt")

        result = await run_gaia(genome, exact_llm_call)

        assert result.samples_evaluated == 15
        # Every sample scores 1.0 (exact match) -> avg 1.0.
        assert result.score == 1.0
        # 0.001 per sample, no judge surcharge.
        assert result.cost_usd == round(0.001 * 15, 4)

    async def test_narration_quoting_answer_goes_to_judge_and_scores_judged_only(self) -> None:
        """#384: the old 0.9 substring tier is gone AND max(exact, judged) is gone.

        A response that quotes the expected answer inside hedged narration is
        unverified prose: every sample takes the judge path, the score is
        exactly the judge's verdict (never inflated by the heuristic), and
        every sample pays the judge surcharge.
        """
        genome = make_genome()

        from maistro_evolve.benchmarks.datasets import GAIA_SAMPLES

        question_to_answer = {s["question"]: s["answer"] for s in GAIA_SAMPLES}

        async def narrating_llm_call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            user_content = messages[-1]["content"]
            if "Rate the answer" in user_content:
                return "Score: 8"
            for question, answer in question_to_answer.items():
                if question in user_content:
                    # Maximal narration, zero work: quotes the exact expected
                    # answer — the old scorer paid 0.9 for this, unjudged.
                    return f"After careful analysis, the answer is {answer}, though I cannot be fully certain."
            raise AssertionError("question not found in prompt")

        result = await run_gaia(genome, narrating_llm_call)

        assert result.samples_evaluated == 15
        # judged-only: 0.8 for every sample — no max() inflation from the
        # heuristic tier the old scorer merged in.
        assert result.score == 0.8
        # 0.001 per sample + 0.0005 judge surcharge on ALL 15 (no substring
        # short-circuit skips the judge any more).
        assert result.cost_usd == round(0.001 * 15 + 0.0005 * 15, 4)
        # Provenance (#384): all judge-verified, zero exact matches.
        assert result.metadata["evidence"]["method"] == "exact-match+llm-judge"
        assert result.metadata["evidence"]["exact_matches"] == 0
        assert result.metadata["evidence"]["judge_verified"] == 15

    async def test_judge_failure_is_fail_closed_not_heuristic(self) -> None:
        """#384: a failed judge scores 0.0 — the old code fell back to
        max(exact, judged) and could award the heuristic tier instead."""
        genome = make_genome()

        async def failing_judge(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            if "Rate the answer" in messages[-1]["content"]:
                raise RuntimeError("judge down")
            # Must not equal (or contain) any GAIA expected answer — the
            # candidate channel answers every question with the same string.
            return "mumblecore Waldensian yonderflats"

        result = await run_gaia(genome, failing_judge)

        assert result.samples_evaluated == 15
        # Non-exact responses got nothing: judge failed -> 0.0, never a floor.
        assert result.score == 0.0

    async def test_judge_llm_call_override_is_used_for_verification(self) -> None:
        """#384: judge_llm_call supplies the verifier channel, distinct from
        the candidate channel — the anti-self-judging hook calibration uses."""
        genome = make_genome()
        candidate_calls: list[int] = []
        judge_calls: list[int] = []

        async def candidate_llm(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            candidate_calls.append(1)
            return "totally unrelated nonsense"

        async def judge_llm(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            judge_calls.append(1)
            return "Score: 6"

        result = await run_gaia(genome, candidate_llm, judge_llm_call=judge_llm)

        assert len(judge_calls) == 15
        assert result.score == 0.6
        # Candidate channel served the answers only (15 calls); the judge
        # channel served every verdict.
        assert len(candidate_calls) == 15

    async def test_evidence_metadata_counts_exact_matches(self) -> None:
        genome = make_genome()

        from maistro_evolve.benchmarks.datasets import GAIA_SAMPLES

        question_to_answer = {s["question"]: s["answer"] for s in GAIA_SAMPLES}

        async def exact_llm_call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            user_content = messages[-1]["content"]
            for question, answer in question_to_answer.items():
                if question in user_content:
                    return answer
            raise AssertionError("question not found in prompt")

        result = await run_gaia(genome, exact_llm_call)

        assert result.metadata["evidence"]["exact_matches"] == 15
        assert result.metadata["evidence"]["judge_verified"] == 0

    async def test_llm_call_exception_path_counts_evaluated_without_score(self) -> None:
        genome = make_genome()

        async def failing_llm_call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            raise TimeoutError("timed out")

        result = await run_gaia(genome, failing_llm_call)

        assert result.samples_evaluated == 15
        assert result.score == 0.0
        assert result.cost_usd == 0.0
