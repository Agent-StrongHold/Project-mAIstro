"""CONNECT proof: ClassifierEngine roots maistro.classifier.logging (ADR-089)."""

from __future__ import annotations

from maistro.classifier.engine import _UNROUTED_AGENT, ClassifierEngine
from maistro.classifier.logging import ClassifierLogger
from maistro.types.config import TaskTypeConfig


def _messages(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


class TestClassifierLoggingConnect:
    async def test_classify_records_decision_on_default_logger(self) -> None:
        engine = ClassifierEngine()
        task_types = {"code": TaskTypeConfig(keywords=["python", "debug", "code"])}
        intent = await engine.classify(
            _messages("please debug this python code"),
            task_types=task_types,
        )
        decisions = engine.decision_logger.get_decisions()
        assert len(decisions) == 1
        decision = decisions[0]
        assert decision.classified_intent == intent.task_type == "code"
        assert decision.reason == "keywords"
        assert decision.selected_agent == _UNROUTED_AGENT
        assert decision.confidence == intent.keyword_score
        assert decision.complexity == intent.complexity

    async def test_classify_uses_injected_decision_logger(self) -> None:
        log = ClassifierLogger()
        engine = ClassifierEngine(decision_logger=log)
        await engine.classify(_messages("hello"), task_types={})
        assert len(log.get_decisions()) == 1
        assert engine.decision_logger is log
