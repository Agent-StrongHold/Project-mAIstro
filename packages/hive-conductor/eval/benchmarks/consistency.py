"""Consistency eval — ask the same question multiple ways, measure variance.

A consistent agent gives the same factual answer regardless of phrasing.
Score = 100 - (variance_penalty). High variance = low score.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

QUESTION_SETS = [
    {
        "topic": "capital_of_france",
        "variants": [
            "What is the capital of France?",
            "Name France's capital city.",
            "Which city serves as the capital of France?",
            "France's capital is what city?",
            "Tell me the capital of France.",
        ],
        "expected_keyword": "paris",
    },
    {
        "topic": "water_formula",
        "variants": [
            "What is the chemical formula for water?",
            "Write the molecular formula of water.",
            "H2O is the formula for what?",
            "What molecule has the formula H2O?",
            "Chemical composition of water?",
        ],
        "expected_keyword": "h2o",
    },
    {
        "topic": "speed_of_light",
        "variants": [
            "What is the speed of light in a vacuum?",
            "How fast does light travel?",
            "Speed of light in m/s?",
            "What velocity does light have in vacuum?",
            "Light speed value?",
        ],
        "expected_keyword": "300",
    },
]


@dataclass(frozen=True)
class EvalResult:
    score: int
    details: dict[str, Any]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())[:200]


async def run(llm_call: Callable[[str, str], Awaitable[str]], n_sets: int = 3) -> EvalResult:
    sets = QUESTION_SETS[:n_sets]
    total = 0
    details: dict[str, Any] = {"sets": []}

    for qs in sets:
        answers = []
        for variant in qs["variants"]:
            resp = await llm_call("Answer concisely in one sentence.", variant)
            answers.append(_normalize(resp))

        # Check if expected keyword appears in all answers
        keyword_hits = sum(1 for a in answers if qs["expected_keyword"] in a)
        keyword_score = int(50 * keyword_hits / len(answers))

        # Check answer similarity (unique normalized answers = inconsistency)
        unique = len(set(answers))
        consistency_score = max(0, 50 - (unique - 1) * 12)

        score = keyword_score + consistency_score
        total += score
        details["sets"].append(
            {
                "topic": qs["topic"],
                "unique_answers": unique,
                "keyword_hits": keyword_hits,
                "score": score,
            }
        )

    return EvalResult(score=total // len(sets), details=details)
