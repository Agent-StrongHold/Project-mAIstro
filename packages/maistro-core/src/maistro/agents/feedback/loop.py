"""FeedbackLoop -- orchestrates the RLHF cycle."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maistro.protocols.feedback import FeedbackExtractor, ViolationStore
    from maistro.protocols.memory import LearningStore
    from maistro.types.feedback import ReviewResult

logger = logging.getLogger("maistro.feedback")


class FeedbackLoop:
    """Orchestrates the RLHF cycle between Auditor and Mason."""

    def __init__(
        self,
        extractor: FeedbackExtractor,
        learning_store: LearningStore,
        violation_store: ViolationStore,
    ) -> None:
        self._extractor = extractor
        self._learning_store = learning_store
        self._violation_store = violation_store

    async def process_review(self, result: ReviewResult) -> int:
        self._violation_store.record_review(result)

        learnings = self._extractor.extract_learnings(result)

        stored_count = 0
        for learning in learnings:
            learning_id = await self._learning_store.store(learning)
            if learning_id > 0:
                stored_count += 1
                logger.debug(
                    "Stored learning %d for agent %s: %s",
                    learning_id,
                    result.agent_id,
                    learning.learning[:80],
                )

        metrics = self._violation_store.get_metrics(result.agent_id)
        logger.info(
            "RLHF cycle for PR #%d (agent=%s): %d findings, %d learnings stored, "
            "trend=%s, avg=%.1f findings/PR",
            result.pr_number,
            result.agent_id,
            len(result.findings),
            stored_count,
            metrics.trend,
            metrics.findings_per_pr,
        )

        return stored_count
