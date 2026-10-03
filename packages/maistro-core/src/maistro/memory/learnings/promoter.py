"""Auto-promotion logic for learnings.

When a learning's hit_count crosses the promotion threshold,
it graduates to 'promoted' status and optionally triggers
skill mutation via the SkillForge protocol.

Ported from Stronghold.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from maistro.memory.learnings.evidence import DEFAULT_MIN_PROMOTION_CONFIDENCE, promotion_blockers

if TYPE_CHECKING:
    from maistro.memory.learnings.approval import LearningApprovalGate
    from maistro.memory.mutations import InMemorySkillMutationStore
    from maistro.protocols.memory import LearningStore
    from maistro.protocols.skills import SkillForge
    from maistro.types.memory import Learning

logger = logging.getLogger(__name__)


class LearningPromoter:
    """Checks and executes promotions with an optional approval gate.

    If an approval_gate is configured, learnings enter 'pending_approval'
    instead of auto-promoting. An admin must approve before mutation fires.
    """

    def __init__(
        self,
        learning_store: LearningStore,
        *,
        threshold: int = 5,
        min_confidence: float = DEFAULT_MIN_PROMOTION_CONFIDENCE,
        skill_forge: SkillForge | None = None,
        mutation_store: InMemorySkillMutationStore | None = None,
        approval_gate: LearningApprovalGate | None = None,
    ) -> None:
        self._store = learning_store
        self._threshold = threshold
        self._min_confidence = min_confidence
        self._forge = skill_forge
        self._mutation_store = mutation_store
        self._approval_gate = approval_gate

    async def check_and_promote(self, org_id: str = "") -> list[Learning]:
        """Check for learnings that should be promoted.

        With approval gate: creates approval requests (pending state).
        Without approval gate: auto-promotes immediately (legacy behavior).

        Returns the list of newly promoted learnings.
        """
        if self._approval_gate:
            return await self._check_with_gate(org_id)
        return await self._check_auto(org_id)

    async def _check_auto(self, org_id: str = "") -> list[Learning]:
        """Legacy auto-promotion (no gate)."""
        promoted = await self._store.check_auto_promotions(
            self._threshold, org_id=org_id, min_confidence=self._min_confidence
        )
        for learning in promoted:
            logger.info(
                "Auto-promoted learning #%s (hits=%d): %s",
                learning.id,
                learning.hit_count,
                learning.learning[:80],
            )
            if learning.tool_name and self._forge:
                await self._try_mutate_skill(learning)
        return promoted

    async def _check_with_gate(self, org_id: str = "") -> list[Learning]:
        """Gate-aware promotion: queue for approval + process approved."""
        assert self._approval_gate is not None
        promoted: list[Learning] = []

        # Enumerate real candidates. find_relevant("") scores 0 for every
        # learning (no trigger key can match an empty query), so it returns an
        # empty list and nothing ever reaches pending_approval. Use list_all and
        # apply the same org scoping as check_auto_promotions: an empty org_id
        # means "only learnings without an org".
        all_candidates = await self._store.list_all(org_id=org_id, limit=10_000)
        candidates = [lr for lr in all_candidates if org_id or not lr.org_id]
        for lr in candidates:
            # The threshold is this promoter's knob; the evidence half is the
            # shared verdict (M4-B3): a learning without validation evidence
            # never reaches the queue, however often it was hit.
            if lr.hit_count >= self._threshold and self._promotable_candidate(lr):
                self._approval_gate.request_approval(
                    learning_id=lr.id or 0,
                    org_id=lr.org_id,
                    learning_preview=lr.learning[:200],
                    tool_name=lr.tool_name,
                    hit_count=lr.hit_count,
                )

        approved_ids = self._approval_gate.get_approved_ids()
        for lid in approved_ids:
            for lr in candidates:
                # The evidence verdict is re-evaluated at consumption time, not
                # only when the request was queued: outcomes recorded while an
                # approval sat pending can sink confidence below the floor, and
                # a stale approval must not bypass the rule the queue enforces.
                # Candidates were re-enumerated from the store this pass, so
                # _promotable_candidate sees the current measured confidence.
                if lr.id == lid and self._promotable_candidate(lr):
                    logger.info(
                        "Gate-approved promotion: learning #%d (hits=%d)",
                        lid,
                        lr.hit_count,
                    )
                    if lr.tool_name and self._forge:
                        await self._try_mutate_skill(lr)
                    self._approval_gate.mark_promoted(lid)
                    promoted.append(lr)

        return promoted

    def _promotable_candidate(self, lr: Learning) -> bool:
        """Whether the learning may reach the approval queue at all.

        Status first, then the shared evidence verdict: the gate queues
        candidates for a human, but the human is the second check, not the
        only one (M4-B3).
        """
        return lr.status == "active" and not promotion_blockers(
            lr, min_confidence=self._min_confidence
        )

    async def _try_mutate_skill(self, learning: Learning) -> None:
        """Attempt to mutate a skill based on a promoted learning."""
        if not self._forge:
            return

        try:
            result = await self._forge.mutate(learning.tool_name, learning)
            if result.get("status") == "mutated" and self._mutation_store:
                from maistro.types.memory import SkillMutation

                mutation = SkillMutation(
                    skill_name=learning.tool_name,
                    learning_id=learning.id or 0,
                    old_prompt_hash=result.get("old_hash", ""),
                    new_prompt_hash=result.get("new_hash", ""),
                )
                await self._mutation_store.record(mutation)
                logger.info(
                    "Skill mutated: %s from learning #%s (%s -> %s)",
                    learning.tool_name,
                    learning.id,
                    result.get("old_hash", ""),
                    result.get("new_hash", ""),
                )
            elif result.get("status") == "error":
                logger.warning(
                    "Skill mutation failed for %s: %s",
                    learning.tool_name,
                    result.get("error"),
                )
        except Exception as e:
            logger.warning("Skill mutation exception for %s: %s", learning.tool_name, e)
