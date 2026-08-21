"""RubricScorer — Scorer protocol adapter wrapping the declarative vocabulary (ADR-060).

Converts a RubricEval instance into a Scorer-protocol object.  The rubric is
always the primary signal: deterministic, auditable, no network required.
"""

from __future__ import annotations

from typing import Any

from eval.departments import RubricEval


class RubricScorer:
    """Scorer adapter over a single RubricEval dimension.

    Usage
    -----
        evals = load_department("eval/departments/yaml/marketing.yaml")
        scorer = RubricScorer(evals[0])
        score = await scorer.score(my_output)
        print(score.value, score.passed)
    """

    provider = "rubric"

    def __init__(self, rubric: RubricEval) -> None:
        self._rubric = rubric

    async def score(self, output: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        result = await self._rubric.score(output, ctx)
        value = result.score / 100.0

        passed_criteria = [
            c["name"]
            for c, detail in zip(
                self._rubric.criteria, result.details.get("criteria", []), strict=False
            )
            if detail.get("passed")
        ]

        # import lazily so hive-conductor works without maistro-core on PYTHONPATH
        try:
            from maistro.protocols.scorer import Score
        except ImportError:
            from dataclasses import dataclass
            from dataclasses import field as _field

            @dataclass(frozen=True)  # type: ignore[no-redef]
            class Score:  # type: ignore[no-redef]
                value: float
                passed: bool
                rationale: str
                evidence: list[str] = _field(default_factory=list)
                provider: str = "rubric"
                details: dict = _field(default_factory=dict)

        return Score(
            value=value,
            passed=value >= 0.5,
            rationale=f"{result.department}/{result.eval_name}: {result.score}/100",
            evidence=passed_criteria,
            provider=self.provider,
            details=result.details,
        )

    @classmethod
    def from_yaml(cls, path: str, eval_index: int = 0) -> RubricScorer:
        """Convenience constructor: load a YAML template and wrap the Nth eval."""
        from eval.loader import load_department

        evals = load_department(path)
        return cls(evals[eval_index])
