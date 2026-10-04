"""In-memory learning store — self-improving corrections (ADR-015).

Ported from Stronghold's battle-tested InMemoryLearningStore with dedup,
FIFO eviction, org-scoped isolation, and outcome tracking.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from maistro.memory.learnings import lifecycle
from maistro.memory.learnings.evidence import (
    DEFAULT_MIN_PROMOTION_CONFIDENCE,
    merge_applicability,
    outcome_confidence,
    promotion_blockers,
)
from maistro.memory.learnings.lifecycle import StageTransition, plan_advance
from maistro.memory.types import Learning, LearningStage
from maistro.observability.correlation import observed_provenance
from maistro.persistence.learning_scope import matches_learning_scope
from maistro.types.memory import CONTRADICT_DELTA, EPISTEMIC_BONUS, REINFORCE_DELTA

logger = logging.getLogger(__name__)


def _consolidation_anchor(survivors: list[Learning], lr: Learning) -> Learning | None:
    """The already-kept duplicate ``lr`` should be absorbed into, if any.

    Duplicates share the tool and scope axes and overlap at least half of
    their trigger keys (the same rule the store's write-path dedup uses).
    Extracted from ``consolidate`` so the merge sweep reads as a sweep.
    """
    return next(
        (
            s
            for s in survivors
            if s.tool_name == lr.tool_name
            and s.org_id == lr.org_id
            and s.team_id == lr.team_id
            and s.user_id == lr.user_id
            and s.agent_id == lr.agent_id
            and lifecycle.trigger_key_overlap(s.trigger_keys, lr.trigger_keys) >= 0.5
        ),
        None,
    )


MAX_LEARNINGS = 10_000


class InMemoryLearningStore:
    """In-memory learning store with dedup, FIFO cap, and org-scoped queries."""

    def __init__(self, max_learnings: int = MAX_LEARNINGS) -> None:
        self._learnings: list[Learning] = []
        self._next_id = 1
        self._max = max_learnings
        # Append-only ladder audit trail (ADR-103). In-memory is the dev/test
        # backend, so the ledger lives here for the same reason provenance
        # does: a backend that skipped it would let every behavioural test
        # pass while only the durable ones did the work.
        self._stage_history: list[StageTransition] = []

    async def store(self, learning: Learning) -> int:
        """Store a learning, naming the execution that produced it.

        The in-memory store fills provenance too. It is the default backend in
        dev and test, so a store that skipped this would let every behavioural
        test pass while only the durable ones did the work -- which is how a
        claim ends up resting on the one implementation that cannot check it.

        Assigned onto the object rather than kept beside it: this store keeps
        the caller's `Learning` and hands the same instance back, so a
        provenance held anywhere else would not survive the read (#709).
        """
        provenance = observed_provenance(
            run_id=learning.run_id,
            node_run_id=learning.node_run_id,
            attempt_id=learning.attempt_id,
        )
        learning.run_id = provenance.run_id
        learning.node_run_id = provenance.node_run_id
        learning.attempt_id = provenance.attempt_id
        match = self._find_dedup_match(learning)
        if match is not None:
            existing, overlap = match
            logger.info(
                "Learning dedup overwrite: id=%s, old_keys=%s, new_keys=%s, overlap=%.2f",
                existing.id,
                existing.trigger_keys,
                learning.trigger_keys,
                overlap,
            )
            existing.learning = learning.learning
            existing.trigger_keys = learning.trigger_keys
            # The epistemic type moves with the text it qualifies. Keeping the
            # old row's type would let the reworded claim ride the stronger
            # ranking bonus and skip the counterfactual evaluation its new
            # type owes before promotion (M4-B3).
            existing.epistemic_type = learning.epistemic_type
            # The producer moves with the content it produced. Dedup
            # replaces what the row says, so leaving the old ids in place
            # would attribute the surviving text to the Run that no longer
            # wrote it, and `produced_by` would return nothing for the Run
            # that did (Codex, #709).
            # The outgoing producer is not lost with the move: it taught a
            # version of this claim, so it joins `evidence_run_ids` and stays
            # answerable from `produced_by` of the evidence, not just of the
            # text (M4-B3: provenance survives consolidation/rewording).
            if existing.run_id and existing.run_id != learning.run_id:
                learning.evidence_run_ids = list(
                    dict.fromkeys([*learning.evidence_run_ids, existing.run_id])
                )
            existing.run_id = learning.run_id
            existing.node_run_id = learning.node_run_id
            existing.attempt_id = learning.attempt_id
            # What the row *rests on* does not move: applicability and evidence
            # union across the consolidation, so a reworded claim stays
            # accountable to every Run that taught any of its versions and
            # keeps every context any version named (M4-B3). The old producer
            # survives in `evidence_run_ids` even though `run_id` moved.
            merge_applicability(existing, learning)
            return existing.id or 0

        if len(self._learnings) >= self._max:
            self._learnings.pop(0)

        learning.id = self._next_id
        self._next_id += 1
        self._learnings.append(learning)
        return learning.id

    def _find_dedup_match(self, learning: Learning) -> tuple[Learning, float] | None:
        """The active same-scope learning this one overlaps, with its overlap.

        The dedup probe shared by `store`'s early return: same tool name, org,
        team, user and agent (the same axes the SQL twins' SQL probe binds),
        `active` status, and at least half of the union of both trigger-key
        sets in common. Split out so `store` reads as probe-then-insert and
        this stays the one place the threshold and axes live.
        """
        for existing in self._learnings:
            if existing.tool_name != learning.tool_name:
                continue
            if existing.agent_id != learning.agent_id:
                continue
            if existing.org_id != learning.org_id:
                continue
            if existing.team_id != learning.team_id or existing.user_id != learning.user_id:
                continue
            if existing.status != "active":
                continue
            overlap = lifecycle.trigger_key_overlap(existing.trigger_keys, learning.trigger_keys)
            if overlap >= 0.5:
                return existing, overlap
        return None

    async def find_relevant(
        self,
        user_text: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        org_id: str = "",
        max_results: int = 10,
    ) -> list[Learning]:
        """Find learnings by keyword, applying the requested scope axes."""
        text_lower = user_text.lower()
        scored: list[tuple[float, Learning]] = []

        for learning in self._learnings:
            if learning.status != "active":
                continue
            if not matches_learning_scope(
                learning,
                org_id=org_id,
                team_id=team_id,
                user_id=user_id,
                agent_id=agent_id,
            ):
                continue

            score: float = sum(1 for k in learning.trigger_keys if k and k.lower() in text_lower)
            if score > 0:
                # Epistemic type is a tie-break, not a second gate (M4-B3):
                # every bonus is < 1.0, so it reorders keyword ties — a tested
                # claim ahead of a counterfactual one — without ever letting a
                # less relevant learning outrank a more relevant one.
                score += EPISTEMIC_BONUS.get(learning.epistemic_type, 0.0)
                scored.append((score, learning))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s[1] for s in scored[:max_results]]

    async def mark_used(self, learning_ids: list[int]) -> None:
        """Increment hit_count for used learnings."""
        id_set = set(learning_ids)
        for learning in self._learnings:
            if learning.id in id_set:
                learning.hit_count += 1

    async def produced_by(self, run_id: str, *, org_id: str = "") -> list[Learning]:
        """Return the learnings this Run produced, newest first.

        A blank `run_id` returns nothing rather than every learning with no
        producer — the same rule the durable stores follow, so a caller cannot
        tell the backends apart by getting a different answer (#709).
        """
        if not run_id:
            return []
        return [
            learning
            for learning in reversed(self._learnings)
            if learning.run_id == run_id and (learning.org_id or "") == org_id
        ]

    async def mark_outcome(
        self, learning_ids: list[int], success: bool, *, org_id: str = ""
    ) -> None:
        """Increment success_after_use or failure_after_use per injected learning.

        Recomputes `confidence` from the outcome counters (`evidence.`
        `outcome_confidence` is the normative rule the SQL twins restate in
        their UPDATE): a recorded outcome is a measurement, and a measurement
        replaces whatever prior an imported claim arrived with. Promotion reads
        that field, so this is where hits become evidence (M4-B3).
        """
        if not learning_ids:
            return
        id_set = set(learning_ids)
        for learning in self._learnings:
            if learning.id not in id_set:
                continue
            if not matches_learning_scope(learning, org_id=org_id):
                continue
            if success:
                learning.success_after_use += 1
            else:
                learning.failure_after_use += 1
            learning.confidence = outcome_confidence(
                learning.success_after_use, learning.failure_after_use
            )

    async def check_auto_promotions(
        self,
        threshold: int = 5,
        org_id: str = "",
        *,
        min_confidence: float = DEFAULT_MIN_PROMOTION_CONFIDENCE,
    ) -> list[Learning]:
        """Promote learnings that hit threshold *and* carry validation evidence.

        Hit_count alone stopped being enough in M4-B3: a learning promoted on
        retrieval frequency is a claim promoted on popularity. `promotion_blockers`
        is the one verdict — source Run/evaluation IDs plus measured confidence
        — and a learning failing it stays `active` however often it is hit.
        """
        promoted: list[Learning] = []
        for learning in self._learnings:
            if learning.status != "active" or learning.hit_count < threshold:
                continue
            if not matches_learning_scope(learning, org_id=org_id):
                continue
            if promotion_blockers(learning, min_confidence=min_confidence):
                continue
            learning.status = "promoted"
            promoted.append(learning)
        return promoted

    async def get_promoted(
        self,
        task_type: str | None = None,
        org_id: str = "",
        *,
        team_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[Learning]:
        """Get promoted learnings within the requested scope."""
        return [
            lr
            for lr in self._learnings
            if lr.status == "promoted"
            and (task_type is None or lr.category == task_type)
            and matches_learning_scope(
                lr,
                org_id=org_id,
                team_id=team_id,
                user_id=user_id,
                agent_id=agent_id,
            )
        ]

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

    async def get(self, learning_id: int, *, org_id: str = "") -> Learning | None:
        """Point read by id, or None.

        Unlike the scope queries on this store, a blank ``org_id`` here means
        "no org filter", not "only orgless rows": a point read by identity is
        not a scope query, and callers that need the scope rule pass an org.

        Callers that hold an id from `store` use this to get back the *store's*
        instance — after a dedup hit, `store` returns the surviving row's id
        and keeps the pre-existing object, so a caller that kept its own copy
        is holding an orphan. `InMemoryLearningLifecycle` leans on exactly that
        guarantee to track the store's row, not the caller's.
        """
        for lr in self._learnings:
            if lr.id != learning_id:
                continue
            if org_id and lr.org_id != org_id:
                continue
            return lr
        return None

    async def reinforce(
        self,
        learning_id: int,
        delta: float = REINFORCE_DELTA,
        *,
        org_id: str = "",
    ) -> Learning | None:
        """Reinforce one learning: a later Run confirmed it helped (#120)."""
        lr = await self.get(learning_id, org_id=org_id)
        if lr is None:
            return None
        return lifecycle.reinforce(lr, delta)

    async def contradict(
        self,
        learning_id: int,
        delta: float = CONTRADICT_DELTA,
        *,
        org_id: str = "",
    ) -> Learning | None:
        """Contradict one learning: a later Run showed it wrong (#120)."""
        lr = await self.get(learning_id, org_id=org_id)
        if lr is None:
            return None
        return lifecycle.contradict(lr, delta)

    async def supersede(
        self,
        old_id: int,
        replacement: Learning,
        *,
        org_id: str = "",
    ) -> int:
        """Retire ``old_id`` in favour of ``replacement``, keeping both rows (#120).

        The old row is retired **before** the replacement is stored so the
        dedup probe -- which only folds into ``active`` rows -- cannot merge
        the replacement into the very row it replaces. Raises ``KeyError``
        when the old id is not in scope: a silent no-op would leave both rows
        active and the lineage unrecorded.
        """
        old = await self.get(old_id, org_id=org_id)
        if old is None:
            raise KeyError(old_id)
        old.status = "superseded"
        new_id = await self.store(replacement)
        survivor = await self.get(new_id)
        if survivor is None:  # pragma: no cover - store() just returned this id
            raise RuntimeError(f"store returned id {new_id} that cannot be read back")
        lifecycle.supersede(old, survivor)
        return new_id

    async def apply_decay(
        self,
        *,
        now: datetime | None = None,
        half_life_days: float | None = None,
    ) -> int:
        """One sweep of time-based confidence decay over live rows (#120).

        Terminal rows (superseded/consolidated) are historical record and do
        not decay. Returns the count of rows whose confidence actually moved.
        """
        moment = now or datetime.now(UTC)
        decayed = 0
        for lr in self._learnings:
            if lr.status in lifecycle.TERMINAL_ROW_STATUSES:
                continue
            before = lr.confidence
            if before is None:
                continue  # unmeasured: no confidence to decay (and decay would need one)
            lifecycle.decay(lr, now=moment, half_life_days=half_life_days)
            if lr.confidence is not None and lr.confidence < before:
                decayed += 1
        return decayed

    async def consolidate(
        self,
        *,
        org_id: str = "",
        tool_name: str | None = None,
    ) -> list[Learning]:
        """Merge near-duplicate active learnings, folding their evidence (#120).

        Admin-operation scoping, like ``list_all``: a blank ``org_id`` sweeps
        every org. Duplicates share the tool and scope axes and overlap at
        least half of their trigger keys (the same rule ``store`` dedup uses);
        the earliest row survives and absorbs the rest. Returns the survivors.
        """
        pool = [
            lr
            for lr in self._learnings
            if lr.status == "active"
            and (not org_id or lr.org_id == org_id)
            and (tool_name is None or lr.tool_name == tool_name)
        ]
        survivors: list[Learning] = []
        for lr in pool:
            anchor = _consolidation_anchor(survivors, lr)
            if anchor is None:
                survivors.append(lr)
            else:
                lifecycle.absorb(anchor, lr)
        return survivors

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

    async def advance_stage(
        self,
        learning_id: int,
        *,
        to_stage: LearningStage,
        actor: str,
        reason: str = "",
        org_id: str = "",
    ) -> Learning:
        """Move a learning one rung up the knowledge ladder (ADR-103).

        The rules live in `plan_advance`; this store applies them to the
        stored instance (which it hands back to callers, so identity is
        preserved exactly as with `store`) and appends the transition to the
        in-memory ledger. A scoped caller (`org_id`) can only advance a row
        it could have read — the same write rule `mark_outcome` enforces.
        """
        learning = await self._get_for_scope(learning_id, org_id=org_id)
        updated, transition = plan_advance(learning, to_stage=to_stage, actor=actor, reason=reason)
        learning.stage = updated.stage
        learning.validated_by = updated.validated_by
        learning.promoted_by = updated.promoted_by
        learning.status = updated.status
        self._stage_history.append(transition)
        return learning

    async def stage_history(self, learning_id: int, *, org_id: str = "") -> list[StageTransition]:
        """The audit trail of one learning's ladder transitions, oldest first."""
        await self._get_for_scope(learning_id, org_id=org_id)
        return [
            transition
            for transition in self._stage_history
            if transition.learning_id == learning_id
        ]

    async def _get_for_scope(self, learning_id: int, *, org_id: str) -> Learning:
        """The stored learning with this id, visible to this org scope.

        The scope rule matches `mark_outcome`: a caller may only move state on
        rows it could have been served. An unknown id raises the same way —
        the distinction between "no such row" and "not yours" would leak
        ids across orgs.
        """
        for lr in self._learnings:
            if lr.id == learning_id and matches_learning_scope(lr, org_id=org_id):
                return lr
        raise KeyError(f"no learning #{learning_id} visible in this scope")
