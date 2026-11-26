from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from ..types import EvalResult, PipelineGenome
from .datasets import GAIA_SAMPLES
from .prompt_builder import build_messages, build_model_config, build_system_prompt
from .scoring import judge_score

# Punctuation is not part of an answer; surrounding whitespace neither.
_PUNCTUATION_RE = re.compile(r"[^\w\s]+", re.UNICODE)


def _normalized_answer(text: str) -> str:
    return " ".join(_PUNCTUATION_RE.sub(" ", text.strip().lower()).split())


def _exact_match_score(response: str, expected: str) -> float:
    """Structural exact match only — no fuzzy fallback tiers (#384).

    1.0 iff the punctuation/whitespace-normalized response *is* the expected
    answer (or both parse as the same number). The historical fuzzy tiers are
    gone: raw-substring (0.9), equal digit-sets (0.85) and word-overlap (0.7)
    each awarded unjudged credit for a response that merely *contained* the
    expected text, and every tier could clear the old ``>= 0.7`` threshold
    that skipped the LLM judge — a narration quoting the answer scored 0.9
    without any verification. A response that does not exactly state the
    answer is unverified; ``run_gaia`` routes it to the judge, whose verdict
    the heuristic can no longer override.

    Fail-closed on empties: an empty expected answer is a broken sample, and
    an empty response says nothing — neither earns a point (the old code
    scored both-empty 1.0 and anything-vs-empty 0.9 via vacuous substring).
    """
    resp_norm = _normalized_answer(response)
    exp_norm = _normalized_answer(expected)
    if not resp_norm or not exp_norm:
        return 0.0
    if resp_norm == exp_norm:
        return 1.0
    # Numeric equality is decided on the raw values: "42.0" vs "42" is the
    # same number, but punctuation-normalizing first would mangle decimals
    # ("42.0" -> "42 0"). Both sides must parse as whole numbers to compare.
    try:
        return 1.0 if float(response.strip()) == float(expected.strip()) else 0.0
    except ValueError:
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


async def run_gaia(
    genome: PipelineGenome,
    llm_call: Any,
    judge_llm_call: Any = None,
) -> EvalResult:
    """Score Q&A responses: exact match, otherwise a verified judge verdict (#384).

    Proxy-tier (SPEC-202): the samples are a small handcrafted set, not the
    official GAIA corpus. Exactly two things can earn score: a structural
    exact match (``_exact_match_score`` — normalized equality, nothing fuzzy)
    or the LLM judge's verdict for every non-exact response. The historical
    fuzzy tiers (substring 0.9 / digit-set 0.85 / word-overlap 0.7) and the
    ``max(exact, judged)`` merge are gone: text similarity no longer
    substitutes for a verified outcome, and a heuristic score can never
    override — or excuse the candidate from — the judge.

    ``judge_llm_call`` optionally supplies a *different* verifier model than
    the candidate's ``llm_call`` (#384): when omitted the candidate's own
    channel judges, so calibration (``benchmarks/calibration.py``) can measure
    how much credit a self-judged narration leaks. Judge failure is
    fail-closed (0.0), never a floor.
    """
    if llm_call is None:
        raise ValueError(
            "run_gaia requires an llm_call — there is no stub/heuristic "
            "fallback (SPEC-202: never produce a fabricated score)"
        )
    judge = judge_llm_call if judge_llm_call is not None else llm_call

    start = time.monotonic()
    system_prompt = build_system_prompt(genome)
    model_config = build_model_config(genome)

    total_score = 0.0
    evaluated = 0
    total_cost = 0.0
    exact_matches = 0
    judge_verified = 0
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
            if exact >= 1.0:
                total_score += exact
                exact_matches += 1
            else:
                # Non-exact responses are unverified by construction: only the
                # judge's verdict can earn them score, and a judge failure is
                # 0.0 — never the heuristic, never a floor (#384).
                judged = await _judge_answer(sample["question"], response, sample["answer"], judge)
                total_score += judged
                judge_verified += 1
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
        metadata={
            "total_samples": samples,
            "fidelity": "proxy",
            # Champion-selection provenance (#384): where every point came
            # from — structural equality counts vs judge-verified counts.
            "evidence": {
                "method": "exact-match+llm-judge",
                "exact_matches": exact_matches,
                "judge_verified": judge_verified,
            },
        },
    )
