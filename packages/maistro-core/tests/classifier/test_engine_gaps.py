"""Gap-filling coverage for classifier/engine.py not exercised by
test_engine_priority.py: is_ambiguous, the keyword-scoring truthy branch,
the LLM-fallback branch, the complexity tier-bump branch, the automation
tier-sizing branch, and detect_multi_intent's delegation."""

from __future__ import annotations

from typing import Any

from maistro.classifier.engine import ClassifierEngine, is_ambiguous
from maistro.types.config import TaskTypeConfig


class _StubLLMClient:
    def __init__(self, task: str | None) -> None:
        self._task = task
        self.calls = 0

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return {"choices": [{"message": {"content": self._task or ""}}]}


def _messages(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


class TestIsAmbiguous:
    def test_fewer_than_two_positive_scores_is_not_ambiguous(self) -> None:
        assert is_ambiguous({"chat": 1.0, "code": 0.0}) is False

    def test_two_positive_scores_below_threshold_is_ambiguous(self) -> None:
        assert is_ambiguous({"chat": 1.0, "code": 2.0}) is True

    def test_two_positive_scores_at_or_above_threshold_is_not_ambiguous(self) -> None:
        assert is_ambiguous({"chat": 1.0, "code": 3.0}) is False


class TestKeywordScoringBranch:
    async def test_strong_keyword_match_selects_best_task_directly(self) -> None:
        engine = ClassifierEngine()
        task_types = {"code": TaskTypeConfig(keywords=["python", "debug", "code"])}
        intent = await engine.classify(
            _messages("please debug this python code"),
            task_types=task_types,
        )
        assert intent.task_type == "code"
        assert intent.classified_by == "keywords"


class TestLlmFallbackBranch:
    async def test_low_keyword_score_with_llm_client_uses_llm_result(self) -> None:
        llm = _StubLLMClient(task="code")
        engine = ClassifierEngine(llm_client=llm)
        task_types = {"code": TaskTypeConfig(keywords=["python"])}
        intent = await engine.classify(
            _messages("something totally unrelated to keywords"),
            task_types=task_types,
        )
        assert intent.task_type == "code"
        assert intent.classified_by == "llm"
        assert llm.calls == 1

    async def test_llm_result_not_in_task_types_keeps_keyword_result(self) -> None:
        llm = _StubLLMClient(task="not_a_real_task")
        engine = ClassifierEngine(llm_client=llm)
        task_types = {"code": TaskTypeConfig(keywords=["python"])}
        intent = await engine.classify(
            _messages("something totally unrelated to keywords"),
            task_types=task_types,
        )
        assert intent.task_type == "chat"
        assert intent.classified_by == "keywords"


class TestComplexityTierBump:
    async def test_complex_task_bumps_min_tier_to_large(self) -> None:
        engine = ClassifierEngine()
        task_types = {
            "reasoning": TaskTypeConfig(
                keywords=["refactor", "optimize", "thorough", "comprehensive", "code"],
                min_tier="small",
            )
        }
        intent = await engine.classify(
            _messages(
                "please refactor and optimize this code step by step in a "
                "thorough and comprehensive way across the whole project"
            ),
            task_types=task_types,
        )
        assert intent.min_tier == "large"


class TestAutomationTierSizing:
    async def test_automation_task_type_runs_automation_min_tier(self) -> None:
        engine = ClassifierEngine()
        task_types = {
            "automation": TaskTypeConfig(
                keywords=["turn", "lights", "thermostat", "automation"],
                min_tier="small",
            )
        }
        intent = await engine.classify(
            _messages("turn on the lights and adjust the thermostat automation"),
            task_types=task_types,
        )
        assert intent.task_type == "automation"


class TestDetectMultiIntentDelegation:
    def test_delegates_to_module_level_function(self) -> None:
        engine = ClassifierEngine()
        task_types = {"code": TaskTypeConfig(keywords=["code"])}
        result = engine.detect_multi_intent("write some code", task_types)
        assert isinstance(result, list)
