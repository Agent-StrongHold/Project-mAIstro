"""In-memory learning store — self-improving corrections (ADR-015).

Ported from Stronghold's battle-tested InMemoryLearningStore with dedup,
FIFO eviction, org-scoped isolation, and outcome tracking.
"""

from __future__ import annotations

import logging

from maistro.memory.types import Learning

logger = logging.getLogger(__name__)

MAX_LEARNINGS = 10_000


class InMemoryLearningStore:
    """In-memory learning store with dedup, FIFO cap, and org-scoped queries."""

    def __init__(self, max_learnings: int = MAX_LEARNINGS) -> None:
        self._learnings: list[Learning] = []
        self._next_id = 1
        self._max = max_learnings

    async def store(self, learning: Learning) -> int:
        """Store a learning, dedup against existing within same org."""
        new_keys = set(learning.trigger_keys)
        for existing in self._learnings:
            if existing.tool_name != learning.tool_name:
                continue
            if existing.agent_id != learning.agent_id:
                continue
            if existing.org_id != learning.org_id:
                continue
            if existing.status != "active":
                continue
            existing_keys = set(existing.trigger_keys)
            overlap = len(existing_keys & new_keys) / max(len(existing_keys | new_keys), 1)
            if overlap >= 0.5:
                logger.info(
                    "Learning dedup overwrite: id=%s, old_keys=%s, new_keys=%s, overlap=%.2f",
                    existing.id,
                    existing.trigger_keys,
                    learning.trigger_keys,
                    overlap,
                )
                existing.learning = learning.learning
                existing.trigger_keys = learning.trigger_keys
                return existing.id or 0

        if len(self._learnings) >= self._max:
            self._learnings.pop(0)

        learning.id = self._next_id
        self._next_id += 1
        self._learnings.append(learning)
        return learning.id

    async def find_relevant(
        self,
        user_text: str,
        *,
        agent_id: str | None = None,
        org_id: str = "",
        max_results: int = 10,
    ) -> list[Learning]:
        """Find learnings relevant to user text, scoped by org."""
        text_lower = user_text.lower()
        scored: list[tuple[float, Learning]] = []

        for learning in self._learnings:
            if learning.status != "active":
                continue
            if agent_id and learning.agent_id != agent_id:
                continue
            if org_id and learning.org_id != org_id:
                continue
            if not org_id and learning.org_id:
                continue

            score = sum(1 for k in learning.trigger_keys if k and k in text_lower)
            if score > 0:
                scored.append((score, learning))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s[1] for s in scored[:max_results]]

    async def mark_used(self, learning_ids: list[int]) -> None:
        """Increment hit_count for used learnings."""
        id_set = set(learning_ids)
        for learning in self._learnings:
            if learning.id in id_set:
                learning.hit_count += 1

    async def mark_outcome(
        self, learning_ids: list[int], success: bool, *, org_id: str = ""
    ) -> None:
        """Increment success_after_use or failure_after_use per injected learning."""
        if not learning_ids:
            return
        id_set = set(learning_ids)
        for learning in self._learnings:
            if learning.id not in id_set:
                continue
            if org_id and learning.org_id != org_id:
                continue
            if success:
                learning.success_after_use += 1
            else:
                learning.failure_after_use += 1

    async def check_auto_promotions(
        self,
        threshold: int = 5,
        org_id: str = "",
    ) -> list[Learning]:
        """Promote learnings that hit threshold, scoped by org."""
        promoted: list[Learning] = []
        for learning in self._learnings:
            if learning.status != "active" or learning.hit_count < threshold:
                continue
            if org_id and learning.org_id != org_id:
                continue
            if not org_id and learning.org_id:
                continue
            learning.status = "promoted"
            promoted.append(learning)
        return promoted

    async def get_promoted(
        self,
        task_type: str | None = None,
        org_id: str = "",
    ) -> list[Learning]:
        """Get promoted learnings, scoped by org."""
        results: list[Learning] = []
        for lr in self._learnings:
            if lr.status != "promoted":
                continue
            if org_id and lr.org_id != org_id:
                continue
            if not org_id and lr.org_id:
                continue
            results.append(lr)
        return results

    async def list_ineffective(self, min_uses: int) -> list[Learning]:
        """Return learnings whose failure count strictly exceeds successes.

        Only includes learnings with at least min_uses total outcomes.
        Read-only helper — no demotion is performed here.
        """
        results: list[Learning] = []
        for lr in self._learnings:
            total = lr.success_after_use + lr.failure_after_use
            if total >= min_uses and lr.failure_after_use > lr.success_after_use:
                results.append(lr)
        return results

    async def list_all(self, org_id: str = "", limit: int = 200) -> list[Learning]:
        """List all learnings for an org (admin endpoint)."""
        results: list[Learning] = []
        for lr in self._learnings:
            if org_id and org_id != "__system__" and lr.org_id != org_id:
                continue
            results.append(lr)
            if len(results) >= limit:
                break
        return results
