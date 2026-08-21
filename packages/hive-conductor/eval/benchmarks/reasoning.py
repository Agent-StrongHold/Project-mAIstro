"""Reasoning eval — MATH/logic problems with deterministic scoring.

Presents multi-step logic/math problems. Scores based on:
  - Correct final answer (60 pts)
  - Valid intermediate steps shown (20 pts)
  - No logical contradictions (20 pts)
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

PROBLEMS = [
    {
        "id": "r1",
        "prompt": "A train travels 60 km/h for 2.5 hours, then 80 km/h for 1.5 hours. What is the total distance?",
        "answer": 270,
        "unit": "km",
    },
    {"id": "r2", "prompt": "If 3x + 7 = 22, what is x?", "answer": 5, "unit": ""},
    {
        "id": "r3",
        "prompt": "A store offers 20% off, then an additional 10% off the discounted price. What is the total percentage discount?",
        "answer": 28,
        "unit": "%",
    },
    {
        "id": "r4",
        "prompt": "How many ways can you arrange 4 books on a shelf?",
        "answer": 24,
        "unit": "ways",
    },
    {
        "id": "r5",
        "prompt": "If a rectangle has perimeter 30 and width 5, what is its area?",
        "answer": 50,
        "unit": "sq units",
    },
]


@dataclass(frozen=True)
class EvalResult:
    score: int  # 0-100
    details: dict[str, Any]


def _extract_number(text: str) -> float | None:
    nums = re.findall(r"-?\d+\.?\d*", text)
    return float(nums[-1]) if nums else None


async def run(llm_call: Callable[[str, str], Awaitable[str]], n_problems: int = 5) -> EvalResult:
    """Run reasoning eval. llm_call(system, user) -> str."""
    problems = PROBLEMS[:n_problems]
    total = 0
    details: dict[str, Any] = {"problems": []}

    for p in problems:
        response = await llm_call(
            "You are a math tutor. Show your work step by step, then give the final numeric answer.",
            p["prompt"],
        )
        extracted = _extract_number(response)
        correct = extracted is not None and abs(extracted - p["answer"]) < 0.01
        has_steps = len(response.split("\n")) > 2 or "step" in response.lower() or "=" in response
        no_contradictions = (
            "but actually" not in response.lower() and "wait, no" not in response.lower()
        )

        score = (60 if correct else 0) + (20 if has_steps else 0) + (20 if no_contradictions else 0)
        total += score
        details["problems"].append(
            {"id": p["id"], "correct": correct, "score": score, "extracted": extracted}
        )

    return EvalResult(score=total // len(problems), details=details)
