"""Department evals — shared scoring infrastructure.

Each department eval is a rubric-based scorer that takes output text
and returns 0-100 based on criteria specific to that department.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class EvalResult:
    score: int  # 0-100
    department: str
    eval_name: str
    details: dict[str, Any]


class RubricEval:
    """Base class for rubric-based department evals."""

    department: str = ""
    eval_name: str = ""
    criteria: ClassVar[list[dict[str, Any]]] = []  # [{"name", "weight", "check": callable}]

    async def score(self, output: str, context: dict[str, Any] | None = None) -> EvalResult:
        total_weight = sum(c["weight"] for c in self.criteria)
        earned = 0
        details: dict[str, Any] = {"criteria": []}

        for c in self.criteria:
            passed = c["check"](output, context or {})
            points = c["weight"] if passed else 0
            earned += points
            details["criteria"].append(
                {"name": c["name"], "passed": passed, "points": points, "max": c["weight"]}
            )

        score = int(100 * earned / total_weight) if total_weight else 0
        return EvalResult(
            score=score, department=self.department, eval_name=self.eval_name, details=details
        )
