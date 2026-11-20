"""Classifier engine: orchestrates keyword -> LLM fallback pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.classifier.complexity import (
    automation_min_tier,
    coerce_priority,
    estimate_complexity,
    infer_priority,
)
from maistro.classifier.keyword import score_keywords
from maistro.classifier.logging import ClassifierLogger
from maistro.classifier.multi_intent import detect_multi_intent
from maistro.types.intent import TIER_ORDER, Intent

LLM_FALLBACK_THRESHOLD = 3.0

# Agent selection is the router's job; classify records this placeholder until
# a later observability join can fill the chosen Provider/agent (ADR-089).
_UNROUTED_AGENT = "unrouted"


def is_ambiguous(scores: dict[str, float]) -> bool:
    """Check if intent scores indicate ambiguity.

    Ambiguous = 2+ intents scored > 0 AND none scored >= 3.0 (strong indicator).
    """
    above_zero = {k: v for k, v in scores.items() if v > 0}
    if len(above_zero) < 2:
        return False
    max_score = max(above_zero.values())
    return max_score < LLM_FALLBACK_THRESHOLD


if TYPE_CHECKING:
    from maistro.protocols.llm import LLMClient
    from maistro.types.config import TaskTypeConfig


class ClassifierEngine:
    """Implements IntentClassifier protocol.

    Three-phase classification:
    1. Keyword scoring (instant)
    2. LLM fallback if score < threshold (async, costs tokens)
    3. Complexity and priority estimation

    Every decision is recorded on ``decision_logger`` (ADR-089 auditability).
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        classifier_model: str = "auto",
        decision_logger: ClassifierLogger | None = None,
    ) -> None:
        self._llm = llm_client
        self._model = classifier_model
        self.decision_logger = (
            decision_logger if decision_logger is not None else ClassifierLogger()
        )

    async def classify(
        self,
        messages: list[dict[str, str]],
        task_types: dict[str, TaskTypeConfig],
        explicit_priority: str | None = None,
    ) -> Intent:
        """Classify the user's intent."""
        # Extract user text from last user message
        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    user_text = content
                break

        # Phase 1: Keyword scoring
        scores = score_keywords(user_text, task_types)

        # Select best task type
        if scores:
            best_task = max(scores, key=lambda k: scores[k])
            best_score = scores[best_task]
        else:
            best_task = "chat"
            best_score = 0.0

        task_type = best_task if best_score >= LLM_FALLBACK_THRESHOLD else "chat"
        classified_by = "keywords"

        # Phase 2: LLM fallback for ambiguous queries
        if best_score < LLM_FALLBACK_THRESHOLD and self._llm and user_text:
            from maistro.classifier.llm_fallback import llm_classify

            llm_task = await llm_classify(user_text, self._llm, self._model)
            if llm_task and llm_task in task_types:
                task_type = llm_task
                classified_by = "llm"

        # Phase 3: Complexity and priority
        task_cfg = task_types.get(task_type)
        min_tier = task_cfg.min_tier if task_cfg else "small"
        preferred = tuple(task_cfg.preferred_strengths) if task_cfg else ("chat",)
        complexity = estimate_complexity(user_text, task_type)
        priority = coerce_priority(explicit_priority) or infer_priority(user_text)

        # Bump tier for complex tasks
        if complexity == "complex" and TIER_ORDER.get(min_tier, 0) < TIER_ORDER["large"]:
            min_tier = "large"

        # Smart home tier sizing
        if task_type == "automation":
            min_tier = automation_min_tier(user_text, min_tier)

        intent = Intent(
            task_type=task_type,
            complexity=complexity,
            tier=priority,
            min_tier=min_tier,
            preferred_strengths=preferred,
            classified_by=classified_by,
            keyword_score=best_score,
            user_text=user_text,
        )
        self.decision_logger.log_decision(
            input_text=user_text,
            intent_hint=None,
            classified_intent=task_type,
            confidence=best_score,
            complexity=complexity,
            selected_agent=_UNROUTED_AGENT,
            reason=classified_by,
            metadata={"tier": priority, "min_tier": min_tier},
        )
        return intent

    def detect_multi_intent(
        self,
        user_text: str,
        task_types: dict[str, TaskTypeConfig],
    ) -> list[str]:
        """Detect compound intents."""
        return detect_multi_intent(user_text, task_types)
