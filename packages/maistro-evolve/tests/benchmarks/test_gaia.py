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
    def test_exact_match_case_insensitive_and_stripped(self):
        assert _exact_match_score("  Au  ", "au") == 1.0

    def test_substring_match_after_failed_exact_match(self):
        # "the answer is au" != "au" (exact fails), but "au" is a substring of it.
        assert _exact_match_score("the answer is au", "au") == 0.9

    def test_numeric_extraction_equal_sets_match(self):
        # expected "90 90" is never a literal substring of the response (so the
        # 0.9 substring branch is skipped), but both digit-sets reduce to {"90"}.
        assert _exact_match_score("the value is 90, confirmed 90", "90 90") == 0.85

    def test_word_overlap_partial(self):
        # expected "george orwell" -> exp_words = {"george", "orwell"}.
        # response contains "george" only -> overlap 1/2 * 0.7 = 0.35
        assert _exact_match_score("george smith wrote it", "george orwell") == 0.35

    def test_word_overlap_zero(self):
        assert _exact_match_score("completely unrelated text", "george orwell") == 0.0

    def test_empty_expected_hits_substring_branch_not_word_overlap(self):
        # exp_clean == "" -> the `exp_clean in resp_clean` check is vacuously
        # True for any response, so this always lands on the 0.9 substring
        # branch. The `if exp_words:` False path (return 0.0 at line 35) is
        # therefore unreachable dead code: an empty exp_clean always short
        # circuits via substring match before exp_words is even computed.
        assert _exact_match_score("some response", "") == 0.9

    def test_truly_empty_expected_and_response_hits_exact_match(self):
        # both empty -> resp_clean == exp_clean == "" -> exact match branch (1.0).
        assert _exact_match_score("", "") == 1.0


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

    async def test_low_exact_match_triggers_judge_call(self) -> None:
        genome = make_genome()

        async def fake_llm_call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            content = messages[-1]["content"]
            if "Rate the answer" in content:
                return "Score: 8"
            return "totally unrelated nonsense answer"

        result = await run_gaia(genome, fake_llm_call)

        assert result.samples_evaluated == 15
        # judged score is 0.8 for every sample via max(exact, judged), except
        # where the nonsense response's incidental word-overlap with the
        # expected answer's exact-match score exceeds 0.8 (e.g. multi-word
        # answers sharing a stray word with "totally unrelated nonsense
        # answer"), so the true average is slightly above 0.8.
        assert result.score == 0.8067
        # 0.001 always; +0.0005 judge surcharge per sample EXCEPT gaia_13
        # ("A"), where the single-letter expected answer is an incidental
        # substring of "...answer" -> exact=0.9 >= 0.7, skipping the judge.
        assert result.cost_usd == round(0.001 * 15 + 0.0005 * 14, 4)

    async def test_llm_call_exception_path_counts_evaluated_without_score(self) -> None:
        genome = make_genome()

        async def failing_llm_call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            raise TimeoutError("timed out")

        result = await run_gaia(genome, failing_llm_call)

        assert result.samples_evaluated == 15
        assert result.score == 0.0
        assert result.cost_usd == 0.0
