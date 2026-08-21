"""Creativity eval — divergent thinking and novelty scoring.

Measures:
  - Fluency: number of distinct ideas generated (30 pts)
  - Flexibility: number of categories covered (30 pts)
  - Originality: uniqueness vs common answers (40 pts)
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

PROMPTS = [
    {
        "id": "cr1",
        "prompt": "List 10 unusual uses for a paperclip.",
        "common_answers": {"bookmark", "lock pick", "earring", "zipper pull", "reset button"},
    },
    {"id": "cr2", "prompt": "Invent 5 new words and define them.", "common_answers": set()},
    {
        "id": "cr3",
        "prompt": "Describe 5 ways the world would be different if humans could fly.",
        "common_answers": {"no cars", "no roads", "tall buildings", "no airports"},
    },
]


@dataclass(frozen=True)
class EvalResult:
    score: int
    details: dict[str, Any]


def _count_items(text: str) -> list[str]:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    items = [line for line in lines if re.match(r"^[\d\-\*\•]", line) or len(line) > 10]
    return items if items else lines


async def run(llm_call: Callable[[str, str], Awaitable[str]], n_prompts: int = 3) -> EvalResult:
    prompts = PROMPTS[:n_prompts]
    total = 0
    details: dict[str, Any] = {"prompts": []}

    for p in prompts:
        response = await llm_call("Be creative and original. Think outside the box.", p["prompt"])
        items = _count_items(response)

        # Fluency: did they generate enough items?
        fluency = min(30, len(items) * 6)

        # Flexibility: how many distinct first words (proxy for categories)
        first_words = {
            item.split()[1] if len(item.split()) > 1 else item.split()[0] for item in items
        }
        flexibility = min(30, len(first_words) * 8)

        # Originality: how many items are NOT in common answers
        common = p["common_answers"]
        if common:
            novel = sum(1 for item in items if not any(c in item.lower() for c in common))
            originality = min(40, int(40 * novel / max(len(items), 1)))
        else:
            originality = 30 if len(items) >= 3 else 15

        score = fluency + flexibility + originality
        total += score
        details["prompts"].append({"id": p["id"], "n_items": len(items), "score": score})

    return EvalResult(score=total // len(prompts), details=details)
