from __future__ import annotations

import asyncio
import time
from typing import Any

from ..types import EvalResult, PipelineGenome
from .datasets import RAGAS_SAMPLES
from .prompt_builder import build_messages, build_model_config, build_system_prompt
from .scoring import judge_score


def _score_faithfulness(response: str, context: str, expected_answer: str) -> float:
    resp_lower = response.lower()
    ctx_lower = context.lower()
    exp_lower = expected_answer.lower()

    exp_words = set(exp_lower.split())
    if not exp_words:
        return 0.5

    found = sum(1 for w in exp_words if w in resp_lower)
    coverage = found / len(exp_words)

    ctx_claims = [s.strip() for s in ctx_lower.split(".") if len(s.strip()) > 15]
    supported = 0
    resp_words_set = set(resp_lower.split())
    for claim in ctx_claims:
        claim_words = set(claim.split())
        if len(claim_words) == 0:
            continue
        overlap = len(claim_words & resp_words_set) / len(claim_words)
        if overlap > 0.3:
            supported += 1

    support_ratio = supported / max(len(ctx_claims), 1) if ctx_claims else 1.0

    return coverage * 0.6 + support_ratio * 0.4


def _score_relevance(response: str, question: str, expected_answer: str) -> float:
    resp_lower = response.lower()
    exp_lower = expected_answer.lower()

    exp_key_terms = set(exp_lower.split()) - {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "and",
        "or",
        "but",
    }
    if not exp_key_terms:
        return 0.5

    found = sum(1 for term in exp_key_terms if term in resp_lower)
    term_coverage = found / len(exp_key_terms)

    q_lower = question.lower()
    if "difference" in q_lower:
        has_contrast = any(
            w in resp_lower
            for w in [
                "while",
                "whereas",
                "unlike",
                "however",
                "but",
                "compared",
                "versus",
                "difference",
            ]
        )
        term_coverage = term_coverage * 0.7 + (0.3 if has_contrast else 0.0)

    if "relationship" in q_lower or "what is" in q_lower:
        has_explanation = len(resp_lower) > 30
        term_coverage = term_coverage * 0.8 + (0.2 if has_explanation else 0.0)

    return min(1.0, term_coverage)


async def _judge_rag_quality(
    question: str,
    context: str,
    response: str,
    eval_type: str,
    llm_call: Any,
) -> float:
    if eval_type == "faithfulness":
        criteria = "Is the answer faithful to the provided context? Does it only use information from the context?"
    else:
        criteria = (
            "Is the answer relevant to the question? Does it directly address what was asked?"
        )

    judge_prompt = (
        f"Context: {context}\n\n"
        f"Question: {question}\n\n"
        f"Answer: {response}\n\n"
        f"{criteria}\n\n"
        f"Rate 0-10. Respond with ONLY a number."
    )

    try:
        judge_response = await asyncio.wait_for(
            llm_call(
                [
                    {
                        "role": "system",
                        "content": "You are a strict RAG quality judge. Respond with only a number.",
                    },
                    {"role": "user", "content": judge_prompt},
                ],
                temperature=0.0,
                max_tokens=10,
            ),
            timeout=15.0,
        )
        return judge_score(judge_response)
    except (TimeoutError, Exception):
        return 0.0


async def run_ragas(genome: PipelineGenome, llm_call: Any) -> EvalResult:
    """Score RAG faithfulness/relevance — and be honest that this one IS keyword overlap.

    Proxy-tier (SPEC-202): the samples are a small handcrafted set, not the
    official RAGAS methodology. Unlike this package's other proxy scorers,
    the *primary* mechanism here (``_score_faithfulness`` / `_score_relevance`)
    genuinely is word-set overlap between the response and the expected
    answer/context — not a structural check. It escalates to a real
    LLM-as-judge call (``_judge_rag_quality``) only when that static score
    falls below 0.6, and even then takes ``max(static, judged)`` — so a
    response can score highly on word overlap alone without ever reaching
    the judge. Treat `proxy_ragas` scores as the least reliable proxy-tier signal
    in this package for exactly that reason.
    """
    if llm_call is None:
        raise ValueError(
            "run_ragas requires an llm_call — there is no stub/heuristic "
            "fallback (SPEC-202: never produce a fabricated score)"
        )

    start = time.monotonic()
    system_prompt = build_system_prompt(genome)
    model_config = build_model_config(genome)

    total_score = 0.0
    evaluated = 0
    total_cost = 0.0
    samples = len(RAGAS_SAMPLES)

    for sample in RAGAS_SAMPLES:
        user_msg = (
            f"Context:\n{sample['context']}\n\n"
            f"Question: {sample['question']}\n\n"
            f"Answer the question based only on the provided context. Be concise and accurate."
        )

        rag_system = (
            system_prompt
            + "\n\nAnswer questions using only the provided context. Do not add information not in the context."
        )
        messages = build_messages(rag_system, user_msg)

        try:
            response = await asyncio.wait_for(
                llm_call(
                    messages,
                    temperature=model_config.get("temperature", 0.1),
                    max_tokens=model_config.get("max_tokens", 512),
                ),
                timeout=30.0,
            )
            total_cost += 0.001

            eval_type = sample.get("eval_type", "faithfulness")
            if eval_type == "faithfulness":
                static = _score_faithfulness(response, sample["context"], sample["expected_answer"])
            else:
                static = _score_relevance(response, sample["question"], sample["expected_answer"])

            if static >= 0.6:
                total_score += static
            else:
                judged = await _judge_rag_quality(
                    sample["question"], sample["context"], response, eval_type, llm_call
                )
                total_score += max(static, judged)
                total_cost += 0.0005

            evaluated += 1
        except (TimeoutError, Exception):
            evaluated += 1

    avg_score = total_score / max(evaluated, 1)
    elapsed = time.monotonic() - start

    return EvalResult(
        benchmark="proxy_ragas",
        score=round(avg_score, 4),
        cost_usd=round(total_cost, 4),
        duration_seconds=round(elapsed, 3),
        samples_evaluated=evaluated,
        metadata={"total_samples": samples, "fidelity": "proxy"},
    )
