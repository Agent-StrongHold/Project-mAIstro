"""Recall eval — plant facts in context, quiz later, score accuracy.

Tests working memory and context retention:
  - Plant 5 facts in system prompt
  - Ask 5 questions about those facts
  - Score: exact match (100), partial (50), wrong (0)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

FACT_SETS = [
    {
        "facts": [
            "The project codename is AURORA.",
            "The deadline is March 15, 2027.",
            "The budget is $2.4 million.",
            "The team lead is Dr. Sarah Chen.",
            "The primary language is Rust.",
        ],
        "questions": [
            ("What is the project codename?", "aurora"),
            ("When is the deadline?", "march 15"),
            ("What is the budget?", "2.4 million"),
            ("Who is the team lead?", "sarah chen"),
            ("What is the primary language?", "rust"),
        ],
    },
    {
        "facts": [
            "Server region is us-west-2.",
            "Max concurrent users: 10,000.",
            "Database engine: PostgreSQL 16.",
            "Backup schedule: every 6 hours.",
            "SLA target: 99.95% uptime.",
        ],
        "questions": [
            ("What AWS region are the servers in?", "us-west-2"),
            ("What is the max concurrent user count?", "10,000"),
            ("Which database engine is used?", "postgresql"),
            ("How often are backups taken?", "6 hours"),
            ("What is the SLA uptime target?", "99.95"),
        ],
    },
]


@dataclass(frozen=True)
class EvalResult:
    score: int
    details: dict[str, Any]


async def run(llm_call: Callable[[str, str], Awaitable[str]], fact_set_idx: int = 0) -> EvalResult:
    fs = FACT_SETS[fact_set_idx % len(FACT_SETS)]
    system = "Remember these facts:\n" + "\n".join(f"- {f}" for f in fs["facts"])
    total = 0
    results = []

    for question, expected in fs["questions"]:
        response = await llm_call(system, question)
        response_lower = response.lower()
        if expected.lower() in response_lower:
            score = 100
        elif any(word in response_lower for word in expected.lower().split()):
            score = 50
        else:
            score = 0
        total += score
        results.append({"question": question, "expected": expected, "score": score})

    return EvalResult(score=total // len(fs["questions"]), details={"results": results})
