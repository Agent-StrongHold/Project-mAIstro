"""Scorer adapters over the maistro.protocols.Scorer protocol (ADR-060 §3).

- :class:`RubricScorer` — always available; wraps a :class:`RubricEval`
  (deterministic, auditable, no network). The primary signal.
- :class:`DeepEvalScorer` — strictly-optional LLM judge over DeepEval G-Eval.
  Raises ImportError at construction when deepeval is not installed.
- :func:`create_judge_scorer` — factory with graceful fallback: returns a
  DeepEvalScorer when deepeval is importable, otherwise the supplied
  RubricScorer fallback. Importing this module never requires deepeval.
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.personas.rubric import RubricEval, load_evals
from maistro.protocols.scorer import Score, Scorer

logger = logging.getLogger(__name__)


class RubricScorer:
    """Scorer adapter over a single RubricEval dimension."""

    provider = "rubric"

    def __init__(self, rubric: RubricEval) -> None:
        self._rubric = rubric

    @property
    def eval_name(self) -> str:
        return self._rubric.eval_name

    async def score(self, output: str, context: dict[str, Any] | None = None) -> Score:
        try:
            result = await self._rubric.score(output, context or {})
        except Exception as exc:  # contract: never raise on bad input
            return Score(
                value=0.0,
                passed=False,
                rationale=f"rubric scoring failed: {exc}",
                provider=self.provider,
            )
        value = result.score / 100.0
        passed_criteria = [
            str(detail["name"])
            for detail in result.details.get("criteria", [])
            if detail.get("passed")
        ]
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
        """Convenience constructor: load a template YAML and wrap the Nth eval."""
        return cls(load_evals(path)[eval_index])


class DeepEvalScorer:
    """Scorer adapter wrapping DeepEval G-Eval (optional dependency).

    Construction raises ImportError when deepeval is absent; use
    :func:`create_judge_scorer` for the graceful-fallback path.
    """

    provider = "deepeval"

    def __init__(
        self,
        eval_name: str,
        criteria: str,
        *,
        model: Any,
        threshold: float = 0.5,
    ) -> None:
        try:
            from deepeval.metrics import GEval  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "deepeval is not installed; pip install deepeval or fall back to RubricScorer."
            ) from exc
        self._eval_name = eval_name
        self._criteria = criteria
        self._model = model
        self._threshold = threshold

    async def score(self, output: str, context: dict[str, Any] | None = None) -> Score:
        from deepeval.metrics import GEval
        from deepeval.test_case import (  # type: ignore[import-not-found]
            LLMTestCase,
            SingleTurnParams,
        )

        additional_context: str | None = None
        if context:
            additional_context = "; ".join(f"{k}={v}" for k, v in context.items())

        metric = GEval(
            name=self._eval_name,
            criteria=self._criteria,
            evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT],
            model=self._model,
            threshold=self._threshold,
            async_mode=True,
            verbose_mode=False,
        )
        test_case = LLMTestCase(actual_output=output)
        await metric.a_measure(
            test_case,
            _show_indicator=False,
            _additional_context=additional_context,
        )
        value = float(metric.score or 0.0)
        return Score(
            value=value,
            passed=bool(metric.success),
            rationale=metric.reason or f"{self._eval_name}: {value:.2f}",
            provider=self.provider,
            details={"threshold": self._threshold, "raw_score": metric.score},
        )


def deepeval_available() -> bool:
    """True when the optional deepeval package is importable."""
    try:
        import deepeval  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


def create_judge_scorer(
    eval_name: str,
    criteria: str,
    *,
    fallback: RubricScorer,
    model: Any = None,
    threshold: float = 0.5,
) -> Scorer:
    """Return a DeepEvalScorer when deepeval (and a model) is available, else ``fallback``.

    Removing deepeval from the environment degrades gracefully to
    RubricScorer-only — no import error at startup (SPEC-192 acceptance).
    """
    if model is not None and deepeval_available():
        try:
            return DeepEvalScorer(eval_name, criteria, model=model, threshold=threshold)
        except ImportError:  # pragma: no cover — race with the availability check
            pass
    logger.debug(
        "deepeval unavailable (or no judge model supplied); falling back to RubricScorer for %s",
        eval_name,
    )
    return fallback
