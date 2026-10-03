"""Auto-promotion logic for learnings.

When a learning's hit_count crosses the promotion threshold,
it graduates to 'promoted' status and optionally triggers
skill mutation via the SkillForge protocol.

Three promotion postures, most-governed first:

- **Gauntlet** (`gauntlet=`): a threshold-crossing learning is only a
  *candidate*. An independent Gauntlet evaluates it across contexts other than
  the one that produced it, and only an accepted candidate promotes — with the
  exact evaluation Runs, evaluator version and frozen-content hash recorded on
  the promoted learning. Local success alone cannot create shared
  institutional knowledge (M4-B2). Rejected candidates stay active and local,
  evidence intact.
- **Approval gate** (`approval_gate=`): learnings queue for human approval.
- **Legacy**: threshold-crossing learnings auto-promote (unchanged behavior
  for existing callers).

Ported from Stronghold.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maistro.memory.learnings.approval import LearningApprovalGate
    from maistro.memory.learnings.gauntlet import GauntletVerdict, LearningGauntlet
    from maistro.memory.mutations import InMemorySkillMutationStore
    from maistro.protocols.memory import LearningStore
    from maistro.protocols.skills import SkillForge
    from maistro.types.memory import Learning

logger = logging.getLogger(__name__)


class LearningPromoter:
    """Checks and executes promotions with an optional approval gate or Gauntlet.

    A configured Gauntlet takes precedence over the approval gate: the
    question "has this measurably helped independent Runs?" decides
    promotion, and the human queue answers a different one. Without a
    Gauntlet, an approval gate (if configured) queues candidates for a
    human; with neither, promotion is automatic (legacy behavior).
    """

    def __init__(
        self,
        learning_store: LearningStore,
        *,
        threshold: int = 5,
        skill_forge: SkillForge | None = None,
        mutation_store: InMemorySkillMutationStore | None = None,
        approval_gate: LearningApprovalGate | None = None,
        gauntlet: LearningGauntlet | None = None,
    ) -> None:
        self._store = learning_store
        self._threshold = threshold
        self._forge = skill_forge
        self._mutation_store = mutation_store
        self._approval_gate = approval_gate
        self._gauntlet = gauntlet

    async def check_and_promote(self, org_id: str = "") -> list[Learning]:
        """Check for learnings that should be promoted.

        With a Gauntlet: only Gauntlet-accepted candidates promote, carrying
        their validation provenance.
        With an approval gate: creates approval requests (pending state).
        Without either: auto-promotes immediately (legacy behavior).

        Returns the list of newly promoted learnings.
        """
        if self._gauntlet:
            return await self._check_with_gauntlet(org_id)
        if self._approval_gate:
            return await self._check_with_gate(org_id)
        return await self._check_auto(org_id)

    async def _check_auto(self, org_id: str = "") -> list[Learning]:
        """Legacy auto-promotion (no gate)."""
        promoted = await self._store.check_auto_promotions(self._threshold, org_id=org_id)
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

    async def _check_with_gauntlet(self, org_id: str = "") -> list[Learning]:
        """Gauntlet-gated promotion: evaluate candidates, promote only the accepted.

        The threshold makes a learning a candidate; it does not promote. Each
        candidate is evaluated independently (the Gauntlet freezes the
        candidate and judges evaluation Runs the producer did not take part
        in). A rejected candidate's row is left exactly as it is — `active`,
        scoped where it was learned, outcome counters intact — so failure
        keeps its evidence while the collective repertoire stays closed to
        it. On acceptance, `promote_learning` flips the row and writes the
        verdict's provenance: the exact evaluation Run ids, the evaluator
        version, and the frozen-content hash that was validated.
        """
        assert self._gauntlet is not None
        promoted: list[Learning] = []

        # Same candidate enumeration as the gate path: find_relevant("")
        # scores nothing, so list_all plus the org scoping that
        # check_auto_promotions applies is the honest candidate set.
        all_candidates = await self._store.list_all(org_id=org_id, limit=10_000)
        candidates = [lr for lr in all_candidates if org_id or not lr.org_id]
        for lr in candidates:
            if lr.hit_count < self._threshold or lr.status != "active":
                continue
            # A candidate whose evaluation cannot complete (transient trial
            # Run or evaluator failure) is not a rejected candidate: it stays
            # active here and is re-evaluated on a later pass. The failure is
            # contained to this candidate so the remaining candidates are
            # still considered and promotion never breaks the caller, which
            # awaits this inline before persisting the Run.
            try:
                verdict = await self._gauntlet.evaluate(lr)
            except Exception:
                logger.exception(
                    "Gauntlet evaluation failed for learning #%s; "
                    "leaves it active for retry",
                    lr.id,
                )
                continue
            if not verdict.ok:
                logger.info(
                    "Gauntlet rejected learning #%s (%s): stays active and local",
                    lr.id,
                    verdict.reason,
                )
                continue
            updated = await self._promote_validated(lr, verdict)
            if updated is None:
                continue
            promoted.append(updated)

        return promoted

    async def _promote_validated(self, lr: Learning, verdict: GauntletVerdict) -> Learning | None:
        """Promote one Gauntlet-accepted candidate, stamping the verdict's provenance.

        Writes the verdict's audit trail onto the promoted row: the exact
        evaluation Run ids, the evaluator version, and the frozen-content
        hash that was validated. Returns None when the row raced away or
        left scope between enumeration and promotion — not ours to resurrect.
        """
        updated = await self._store.promote_learning(
            lr.id or 0,
            org_id=lr.org_id,
            validated_by=verdict.evaluator_name or verdict.gauntlet,
            evaluator_version=verdict.evaluator_version,
            validated_at=time.time(),
            validation_run_ids=verdict.evaluation_run_ids,
            validation_content_hash=verdict.content_hash,
        )
        if updated is None:
            return None
        logger.info(
            "Gauntlet-validated promotion: learning #%d (runs=%d, evaluator=%s@%s)",
            updated.id,
            len(verdict.evaluation_run_ids),
            verdict.evaluator_name,
            verdict.evaluator_version,
        )
        if updated.tool_name and self._forge:
            await self._try_mutate_skill(updated)
        return updated

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
            if lr.hit_count >= self._threshold and lr.status == "active":
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
                if lr.id == lid and lr.status == "active":
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
