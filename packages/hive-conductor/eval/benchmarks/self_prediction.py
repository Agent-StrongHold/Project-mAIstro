"""Self-prediction eval — agent predicts its own score, then we measure calibration.

A well-calibrated agent knows what it knows and what it doesn't.
Score = 100 - abs(predicted - actual) for each task.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

CALIBRATION_TASKS = [
    {"id": "sp1", "question": "What is 17 * 23?", "answer": "391", "difficulty": "easy"},
    {
        "id": "sp2",
        "question": "What is the 20th prime number?",
        "answer": "71",
        "difficulty": "medium",
    },
    {
        "id": "sp3",
        "question": "Translate 'The cat sat on the mat' to Latin.",
        "answer": "feles",
        "difficulty": "hard",
    },
    {
        "id": "sp4",
        "question": "What year was the Treaty of Westphalia signed?",
        "answer": "1648",
        "difficulty": "medium",
    },
    {
        "id": "sp5",
        "question": "Name the capital of Burkina Faso.",
        "answer": "ouagadougou",
        "difficulty": "medium",
    },
]


@dataclass(frozen=True)
class EvalResult:
    score: int
    details: dict[str, Any]


def _extract_confidence(text: str) -> int:
    nums = re.findall(r"\b(\d{1,3})\b", text)
    for n in nums:
        v = int(n)
        if 0 <= v <= 100:
            return v
    return 50  # default if can't parse


async def run(llm_call: Callable[[str, str], Awaitable[str]], n_tasks: int = 5) -> EvalResult:
    tasks = CALIBRATION_TASKS[:n_tasks]
    total = 0
    details: dict[str, Any] = {"tasks": []}

    for t in tasks:
        # Ask for confidence first
        conf_resp = await llm_call(
            "You will be asked a question. Before answering, predict how confident you are (0-100) that you'll get it right. Reply with ONLY a number.",
            f"How confident are you that you can correctly answer: {t['question']}",
        )
        predicted = _extract_confidence(conf_resp)

        # Now ask the actual question
        answer_resp = await llm_call("Answer concisely.", t["question"])
        correct = t["answer"].lower() in answer_resp.lower()
        actual = 100 if correct else 0

        calibration_error = abs(predicted - actual)
        score = max(0, 100 - calibration_error)
        total += score
        details["tasks"].append(
            {
                "id": t["id"],
                "predicted": predicted,
                "actual": actual,
                "correct": correct,
                "score": score,
            }
        )

    return EvalResult(score=total // len(tasks), details=details)
