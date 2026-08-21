from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from ..types import EvalResult, PipelineGenome
from .datasets import GAIA_SAMPLES
from .prompt_builder import build_messages, build_model_config, build_system_prompt
from .scoring import judge_score


def _exact_match_score(response: str, expected: str) -> float:
    resp_clean = response.strip().lower()
    exp_clean = expected.strip().lower()

    if resp_clean == exp_clean:
        return 1.0

    if exp_clean in resp_clean:
        return 0.9

    resp_nums = set(re.findall(r"\d+", resp_clean))
    exp_nums = set(re.findall(r"\d+", exp_clean))
    if exp_nums and resp_nums == exp_nums:
        return 0.85

    resp_words = set(resp_clean.split())
    exp_words = set(exp_clean.split())
    if exp_words:
        overlap = resp_words & exp_words
        return len(overlap) / len(exp_words) * 0.7

    return 0.0


async def _judge_answer(
    question: str,
    response: str,
    expected: str,
    llm_call: Any,
) -> float:
    judge_prompt = (
        f"Judge if the following answer is correct. Question: {question}\n"
        f"Expected answer: {expected}\n"
        f"Given answer: {response}\n\n"
        f"Rate the answer on a scale of 0 to 10 where:\n"
        f"- 10: Completely correct\n"
        f"- 5: Partially correct\n"
        f"- 0: Completely wrong\n\n"
        f"Respond with ONLY a number from 0 to 10, nothing else."
    )

    try:
        judge_response = await asyncio.wait_for(
            llm_call(
                [
                    {
                        "role": "system",
                        "content": "You are a strict answer judge. Respond with only a number.",
                    },
                    {"role": "user", "content": judge_prompt},
                ],
                temperature=0.0,
                max_tokens=10,
            ),
            timeout=15.0,
        )
        score = judge_score(judge_response)
        return score
    except (TimeoutError, Exception):
        return 0.0


async def run_gaia(genome: PipelineGenome, llm_call: Any) -> EvalResult:
    """Score Q&A responses with a fuzzy heuristic that gates a real LLM-judge fallback.

    Proxy-tier (SPEC-202): the samples are a small handcrafted set, not the
    official GAIA corpus. Despite the name, ``_exact_match_score`` is NOT
    exact-match: it awards 1.0 for exact equality, but also 0.9 for the
    expected answer appearing anywhere as a raw substring of the response,
    0.85 for the same set of digit-sequences appearing in both, and up to
    0.7 for plain word-set overlap. Any of those non-exact tiers can reach
    the 0.7 threshold that skips the LLM-as-judge call (``_judge_answer``)
    entirely — so a short expected answer (e.g. a single letter) can be
    trivially satisfied by an unrelated response that happens to contain
    that substring, without the judge ever running.
    """
    if llm_call is None:
        raise ValueError(
            "run_gaia requires an llm_call — there is no stub/heuristic "
            "fallback (SPEC-202: never produce a fabricated score)"
        )

    start = time.monotonic()
    system_prompt = build_system_prompt(genome)
    model_config = build_model_config(genome)

    total_score = 0.0
    evaluated = 0
    total_cost = 0.0
    samples = len(GAIA_SAMPLES)

    for sample in GAIA_SAMPLES:
        user_msg = (
            f"{sample['question']}\n\n"
            f"Provide a concise, direct answer. If it's a number, give only the number. "
            f"If it's a name, give only the name."
        )
        messages = build_messages(system_prompt, user_msg)

        try:
            response = await asyncio.wait_for(
                llm_call(
                    messages,
                    temperature=model_config.get("temperature", 0.1),
                    max_tokens=model_config.get("max_tokens", 256),
                ),
                timeout=30.0,
            )

            exact = _exact_match_score(response, sample["answer"])
            if exact >= 0.7:
                total_score += exact
            else:
                judged = await _judge_answer(
                    sample["question"], response, sample["answer"], llm_call
                )
                total_score += max(exact, judged)
                total_cost += 0.0005

            total_cost += 0.001
            evaluated += 1
        except (TimeoutError, Exception):
            evaluated += 1

    avg_score = total_score / max(evaluated, 1)
    elapsed = time.monotonic() - start

    return EvalResult(
        benchmark="proxy_gaia",
        score=round(avg_score, 4),
        cost_usd=round(total_cost, 4),
        duration_seconds=round(elapsed, 3),
        samples_evaluated=evaluated,
        metadata={"total_samples": samples, "fidelity": "proxy"},
    )
