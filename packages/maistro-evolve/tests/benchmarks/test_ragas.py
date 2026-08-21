from __future__ import annotations

from typing import Any

import pytest

from maistro_evolve.benchmarks.datasets import RAGAS_SAMPLES
from maistro_evolve.benchmarks.ragas import (
    _judge_rag_quality,
    _score_faithfulness,
    _score_relevance,
    run_ragas,
)

# ---------------------------------------------------------------------------
# _score_faithfulness
# ---------------------------------------------------------------------------


class TestScoreFaithfulness:
    def test_empty_expected_answer_returns_half(self):
        assert _score_faithfulness("anything", "anything", "") == 0.5

    def test_full_coverage_partial_support_exact_value(self):
        response = "cats are small mammals that purr"
        context = "cats are small mammals that purr a lot. dogs bark loudly outside"
        expected_answer = "cats mammals"
        # exp_words = {"cats", "mammals"}; both found in response -> coverage = 1.0
        # ctx_claims = ["cats are small mammals that purr a lot", "dogs bark loudly outside"]
        # claim 1 overlap = 6/8 = 0.75 > 0.3 -> supported
        # claim 2 overlap = 0/4 = 0.0 -> not supported
        # support_ratio = 1/2 = 0.5
        # score = 1.0*0.6 + 0.5*0.4 = 0.8
        assert _score_faithfulness(response, context, expected_answer) == pytest.approx(0.8)

    def test_no_claims_long_enough_support_ratio_defaults_to_one(self):
        # every sentence fragment is <=15 chars after strip -> ctx_claims is empty
        context = "yes. ok. no."
        response = "cats mammals"
        expected_answer = "cats mammals"
        # exp_words = {"cats", "mammals"}, both found -> coverage = 1.0
        # ctx_claims empty -> support_ratio = 1.0 (falsy branch)
        # score = 1.0*0.6 + 1.0*0.4 = 1.0
        assert _score_faithfulness(response, context, expected_answer) == pytest.approx(1.0)

    def test_partial_coverage_mixed_support_exact_value(self):
        response = "cats are small mammals that purr a lot indeed"
        context = (
            "cats are small mammals that purr a lot. dogs are loud animals that bark constantly"
        )
        expected_answer = "cats mammals bark"
        # exp_words = {"cats", "mammals", "bark"}; found = {"cats", "mammals"} -> coverage = 2/3
        # ctx_claims = ["cats are small mammals that purr a lot", "dogs are loud animals that bark constantly"]
        # claim 1 overlap = 7/8 = 1.0 > 0.3 -> supported += 1
        # claim 2 overlap = 2/7 ~= 0.2857 <= 0.3 -> not supported (no increment)
        # support_ratio = 1/2 = 0.5
        # score = (2/3)*0.6 + 0.5*0.4 = 0.6
        assert _score_faithfulness(response, context, expected_answer) == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# _score_relevance
# ---------------------------------------------------------------------------


class TestScoreRelevance:
    def test_expected_answer_all_stopwords_returns_half(self):
        assert _score_relevance("anything", "what?", "the a is") == 0.5

    def test_basic_term_coverage_capped_with_min(self):
        response = "cats purr loudly"
        question = "tell me about cats"
        expected_answer = "cats purr"
        # exp_key_terms = {"cats", "purr"}; both found -> term_coverage = 1.0
        assert _score_relevance(response, question, expected_answer) == pytest.approx(1.0)

    def test_basic_term_coverage_partial_ratio(self):
        response = "cats purr"
        question = "tell me about animals"
        expected_answer = "cats dogs birds"
        # exp_key_terms = {"cats", "dogs", "birds"}; found = {"cats"} -> 1/3
        assert _score_relevance(response, question, expected_answer) == pytest.approx(1 / 3)

    def test_difference_question_with_contrast_words(self):
        response = "cats differ from dogs, however cats purr"
        question = "what is the difference between cats and dogs?"
        expected_answer = "cats purr dogs bark"
        # NOTE: this question also contains "what is", so both the "difference" and
        # "relationship/what is" blocks fire (they are independent `if`s, not elif).
        # exp_key_terms = {"cats", "purr", "dogs", "bark"}; found = {"cats", "purr", "dogs"} -> 3/4
        # has_contrast: "however" in response -> True
        # term_coverage = 0.75*0.7 + 0.3 = 0.825
        # has_explanation: len(response) > 30 -> True (len==41)
        # term_coverage = 0.825*0.8 + 0.2 = 0.86
        result = _score_relevance(response, question, expected_answer)
        assert result == pytest.approx(0.86)

    def test_difference_question_without_contrast_words(self):
        response = "cats purr dogs bark"
        question = "how do cats differ from dogs in difference of sound?"
        expected_answer = "cats purr dogs bark"
        # "difference" present, no "relationship"/"what is" -> only first block fires
        # exp_key_terms = {"cats", "purr", "dogs", "bark"}; all found -> term_coverage = 1.0
        # has_contrast: none of the contrast words appear in response -> False
        # term_coverage = 1.0*0.7 + 0.0 = 0.7
        assert _score_relevance(response, question, expected_answer) == pytest.approx(0.7)

    def test_relationship_question_with_long_explanation(self):
        response = "cats and dogs are both popular pets that people love deeply"
        question = "what is the relationship between cats and dogs?"
        expected_answer = "cats dogs pets"
        # exp_key_terms = {"cats", "dogs", "pets"}; all found -> term_coverage = 1.0
        # "relationship" present -> has_explanation: len(response) > 30 -> True
        # term_coverage = 1.0*0.8 + 0.2 = 1.0 (clamped by min, value already == 1.0)
        assert _score_relevance(response, question, expected_answer) == pytest.approx(1.0)

    def test_relationship_question_with_short_explanation(self):
        response = "pets"
        question = "what is the relationship between cats and dogs?"
        expected_answer = "cats dogs pets"
        # exp_key_terms = {"cats", "dogs", "pets"}; found = {"pets"} -> 1/3
        # "relationship" + "what is" both present -> has_explanation: len("pets")=4 not > 30 -> False
        # term_coverage = (1/3)*0.8 + 0.0 = 0.2666...
        assert _score_relevance(response, question, expected_answer) == pytest.approx((1 / 3) * 0.8)

    def test_min_clamp_at_exact_ceiling(self):
        # Demonstrates the min(1.0, ...) clamp boundary: with full term coverage and
        # both bonus blocks satisfied, term_coverage reaches exactly 1.0, never exceeding it
        # (the clamp is structurally unreachable past 1.0 given the formula, since
        # term_coverage <= 1.0 going in and every transform is a convex combination).
        response = "cats differ from dogs, however they are both wonderful pets indeed"
        question = "what is the difference between cats and dogs?"
        expected_answer = "cats dogs"
        result = _score_relevance(response, question, expected_answer)
        assert result == pytest.approx(1.0)
        assert result <= 1.0


# ---------------------------------------------------------------------------
# _judge_rag_quality
# ---------------------------------------------------------------------------


class TestJudgeRagQuality:
    @pytest.mark.asyncio
    async def test_faithfulness_criteria_in_prompt(self):
        captured: list[dict[str, Any]] = []

        async def fake_llm_call(messages, **kwargs):
            captured.append({"messages": messages, "kwargs": kwargs})
            return "score: 8"

        result = await _judge_rag_quality(
            "q?", "some context", "some response", "faithfulness", fake_llm_call
        )
        assert result == pytest.approx(0.8)
        prompt = captured[0]["messages"][1]["content"]
        assert "Is the answer faithful to the provided context?" in prompt
        assert "Rate 0-10. Respond with ONLY a number." in prompt
        assert captured[0]["kwargs"]["temperature"] == 0.0
        assert captured[0]["kwargs"]["max_tokens"] == 10

    @pytest.mark.asyncio
    async def test_relevance_criteria_in_prompt(self):
        captured: list[dict[str, Any]] = []

        async def fake_llm_call(messages, **kwargs):
            captured.append({"messages": messages, "kwargs": kwargs})
            return "score: 5"

        result = await _judge_rag_quality(
            "q?", "some context", "some response", "relevance", fake_llm_call
        )
        assert result == pytest.approx(0.5)
        prompt = captured[0]["messages"][1]["content"]
        assert "Is the answer relevant to the question?" in prompt

    @pytest.mark.asyncio
    async def test_exception_in_llm_call_returns_zero(self):
        async def failing_llm_call(messages, **kwargs):
            raise RuntimeError("boom")

        result = await _judge_rag_quality("q?", "ctx", "resp", "faithfulness", failing_llm_call)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_timeout_returns_zero(self):
        import asyncio

        async def slow_llm_call(messages, **kwargs):
            await asyncio.sleep(10)
            return "score: 9"

        # Patch wait_for's timeout indirectly isn't needed: we directly trigger the
        # except branch via a call that raises asyncio.TimeoutError synchronously instead,
        # since waiting 10s in tests is undesirable.
        async def timeout_llm_call(messages, **kwargs):
            raise TimeoutError("simulated timeout")

        result = await _judge_rag_quality("q?", "ctx", "resp", "relevance", timeout_llm_call)
        assert result == 0.0


# ---------------------------------------------------------------------------
# run_ragas
# ---------------------------------------------------------------------------


class TestRunRagas:
    @pytest.mark.asyncio
    async def test_llm_call_none_raises(self, genome):
        with pytest.raises(ValueError, match="requires an llm_call"):
            await run_ragas(genome, None)

    @pytest.mark.asyncio
    async def test_faithfulness_sample_high_static_score_no_judge_call(self, genome):
        judge_calls: list[str] = []

        async def fake_llm_call(messages, **kwargs):
            prompt = messages[-1]["content"]
            if "Rate 0-10" in prompt:
                judge_calls.append(prompt)
                return "score: 9"
            # Identify which sample this call is for (by its unique context substring)
            # and echo back its own expected_answer + context, which always yields a
            # high static score (>= 0.6) for both eval types, so the judge is never
            # invoked for any sample.
            sample = next(s for s in RAGAS_SAMPLES if s["context"] in prompt)
            return sample["expected_answer"] + " " + sample["context"]

        result = await run_ragas(genome, fake_llm_call)
        assert result.samples_evaluated == 12
        assert judge_calls == []
        # cost: 0.001 per sample (12 samples), no judge calls since all statics are high
        assert result.cost_usd == pytest.approx(round(0.001 * 12, 4))
        assert result.score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_relevance_sample_high_static_score_no_judge_call(self, genome):
        judge_calls: list[str] = []

        async def fake_llm_call(messages, **kwargs):
            prompt = messages[-1]["content"]
            if "Rate 0-10" in prompt:
                judge_calls.append(prompt)
                return "score: 9"
            sample = next(s for s in RAGAS_SAMPLES if s["context"] in prompt)
            return sample["expected_answer"] + " " + sample["context"]

        result = await run_ragas(genome, fake_llm_call)
        assert judge_calls == []
        assert result.cost_usd == pytest.approx(round(0.001 * 12, 4))
        assert result.score == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_low_static_score_triggers_judge_and_extra_cost(self, genome):
        judge_calls: list[str] = []

        async def fake_llm_call(messages, **kwargs):
            prompt = messages[-1]["content"]
            if "Rate 0-10" in prompt:
                judge_calls.append(prompt)
                return "score: 7"
            # A response sharing no words with any sample's expected_answer/context
            # guarantees a low static score (well below 0.6) for every sample.
            return "zzz qqq xxx yyy completely unrelated gibberish"

        result = await run_ragas(genome, fake_llm_call)
        assert result.samples_evaluated == 12
        # every sample's static score should be low enough to trigger the judge
        assert len(judge_calls) == 12
        # cost: 0.001 (main call) + 0.0005 (judge call) per sample = 0.0015 * 12
        assert result.cost_usd == pytest.approx(round(0.0015 * 12, 4))
        # judge always returns 0.7 -> avg_score should be 0.7 (since judged >= static)
        assert result.score == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_llm_call_exception_increments_evaluated_without_score(self, genome):
        async def failing_llm_call(messages, **kwargs):
            raise RuntimeError("network error")

        result = await run_ragas(genome, failing_llm_call)
        assert result.samples_evaluated == 12
        assert result.score == 0.0
        assert result.cost_usd == 0.0
