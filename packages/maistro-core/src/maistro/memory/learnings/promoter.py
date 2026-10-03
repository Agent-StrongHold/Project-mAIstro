"""Auto-promotion logic for learnings.

When a learning's hit_count crosses the promotion threshold,
it graduates to 'promoted' status and optionally triggers
skill mutation via the SkillForge protocol.

Ported from Stronghold. Since ADR-100126-8c2d (M4-B #118), a configured Gauntlet
stands between the threshold and the repertoire: hit_count alone only makes a
learning a *candidate* -- it joins the collective repertoire when the
Gauntlet accepts the outcome evidence later Runs recorded, and is left in
place otherwise.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from maistro.memory.learnings.gauntlet import evidence_of
from maistro.memory.learnings.lifecycle import (
    advance_stage,
    commit_to_repertoire,
)
from maistro.persistence.learning_scope import matches_learning_scope
from maistro.protocols.memory import AntiPatternSink, IneffectiveLearningSource
from maistro.types.memory import (
    ANTI_PATTERN_CONFIDENCE_FLOOR,
    EpistemicType,
    LearningStage,
)

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

    Precedence when several gates are configured: the Gauntlet first -- machine
    validation of recorded evidence -- then, when no Gauntlet is configured,
    the human approval gate. A learning never reaches the collective
    repertoire unvalidated while a Gauntlet is wired (#118).
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

        With a Gauntlet: only Gauntlet-validated learnings join the repertoire
        (#118). With an approval gate (and no Gauntlet): creates approval
        requests (pending state). With neither: auto-promotes immediately
        (legacy behavior).

        Returns the list of newly promoted learnings.
        """
        if self._gauntlet:
            return await self._check_with_gauntlet(org_id)
        if self._approval_gate:
            return await self._check_with_gate(org_id)
        return await self._check_auto(org_id)

    async def _check_with_gauntlet(self, org_id: str = "") -> list[Learning]:
        """Gauntlet-gated promotion: threshold makes a candidate, evidence decides.

        The store's ``check_auto_promotions`` is deliberately not used here: it
        flips status to promoted on hit_count alone, which is the exact
        promotion-without-validation this path exists to prevent. The row is
        validated first (LEARNING -> VALIDATED, recording Gauntlet
        provenance), then committed to the repertoire (VALIDATED ->
        REPERTOIRE, status promoted). A learning the Gauntlet rejects stays
        active and local, untouched, still promotable once later Runs have
        recorded better evidence.
        """
        assert self._gauntlet is not None

        all_rows = await self._store.list_all(org_id=org_id, limit=10_000)
        promoted: list[Learning] = []
        for lr in self._gauntlet_candidates(all_rows, org_id):
            verdict = await self._gauntlet.evaluate(lr, evidence=evidence_of(lr))
            if not verdict.ok:
                logger.info(
                    "Gauntlet held learning #%s: %s",
                    lr.id,
                    verdict.reason,
                )
                continue
            self._admit_validated(lr, verdict)
            if lr.tool_name and self._forge:
                await self._try_mutate_skill(lr)
            promoted.append(lr)

        return promoted

    def _gauntlet_candidates(self, all_rows: list[Learning], org_id: str) -> list[Learning]:
        """Rows past the hit_count threshold in scope for this sweep.

        Admin-operation scoping, like ``list_all``: a blank ``org_id`` sweeps
        every org; otherwise only that org's active rows are candidates.
        """
        assert self._gauntlet is not None
        return [
            lr
            for lr in all_rows
            if (org_id or not lr.org_id)
            and lr.status == "active"
            and lr.hit_count >= self._threshold
        ]

    def _admit_validated(self, lr: Learning, verdict: GauntletVerdict) -> None:
        """Move a Gauntlet-validated learning into the repertoire.

        LEARNING -> VALIDATED records the Gauntlet provenance; VALIDATED ->
        REPERTOIRE is the commit. Split from the sweep so the promotion
        semantics stay readable apart from the candidate iteration.
        """
        assert self._gauntlet is not None
        advance_stage(
            lr,
            LearningStage.VALIDATED,
            gauntlet_name=self._gauntlet.name,
        )
        commit_to_repertoire(lr)
        logger.info(
            "Gauntlet-validated learning #%s joined the repertoire (%s)",
            lr.id,
            verdict.reason,
        )

    async def capture_anti_patterns(
        self,
        org_id: str = "",
        *,
        min_uses: int = 3,
    ) -> list[Learning]:
        """Turn repeatedly-followed-into-failure learnings into anti-patterns (#121).

        Failure knowledge is retained, not discarded: the learning is
        reclassified ``ANTI_PATTERN`` and its confidence is lifted to the
        anti-pattern floor, because it cost real failures to learn and a later
        Run must not re-buy them. The row stays ``active`` at stage LEARNING --
        reclassification is not validation; joining the repertoire still
        requires the Gauntlet like any other learning.

        Requires a store that can name its ineffective learnings; one that
        cannot simply yields nothing to capture. A store that also implements
        :class:`AntiPatternSink` has the reclassification written back: the
        SQL twins return detached row copies, so without the write the
        decision would evaporate with the copy and the next process would
        re-learn the anti-pattern by re-buying the failure.
        """
        source = self._store if isinstance(self._store, IneffectiveLearningSource) else None
        if source is None:
            return []
        sink = self._store if isinstance(self._store, AntiPatternSink) else None
        captured: list[Learning] = []
        for lr in await source.list_ineffective(min_uses):
            if not matches_learning_scope(lr, org_id=org_id):
                continue
            if lr.epistemic_type is EpistemicType.ANTI_PATTERN:
                continue
            lr.epistemic_type = EpistemicType.ANTI_PATTERN
            lr.confidence = max(lr.confidence, ANTI_PATTERN_CONFIDENCE_FLOOR)
            if sink is not None and lr.id is not None:
                await sink.mark_anti_pattern(lr.id, ANTI_PATTERN_CONFIDENCE_FLOOR, org_id=lr.org_id)
            captured.append(lr)
        return captured

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
