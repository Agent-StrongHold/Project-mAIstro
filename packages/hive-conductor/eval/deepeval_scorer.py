"""DeepEvalScorer — Scorer protocol adapter wrapping DeepEval G-Eval (ADR-060).

Optional integration: raises ImportError at construction if deepeval is not
installed.  Callers should catch and fall back to RubricScorer:

    try:
        scorer = DeepEvalScorer("voice_quality", criteria, model=my_model)
    except ImportError:
        scorer = RubricScorer(rubric_eval)

The model must be supplied — a ``DeepEvalBaseLLM`` subclass or a model-name
string supported by deepeval.  No model is defaulted here so there is no
implicit dependency on OpenAI or any other provider.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deepeval.models.base_model import DeepEvalBaseLLM


class DeepEvalScorer:
    provider = "deepeval"

    def __init__(
        self,
        eval_name: str,
        criteria: str,
        *,
        model: str | DeepEvalBaseLLM,
        threshold: float = 0.5,
    ) -> None:
        try:
            from deepeval.metrics import GEval  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "deepeval is not installed. pip install deepeval  or fall back to RubricScorer."
            ) from exc
        self._eval_name = eval_name
        self._criteria = criteria
        self._model = model
        self._threshold = threshold

    async def score(self, output: str, context: dict[str, Any] | None = None) -> Any:
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase, SingleTurnParams

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
                provider: str = "deepeval"
                details: dict = _field(default_factory=dict)

        return Score(
            value=value,
            passed=bool(metric.success),
            rationale=metric.reason or f"{self._eval_name}: {value:.2f}",
            provider=self.provider,
            details={"threshold": self._threshold, "raw_score": metric.score},
        )
