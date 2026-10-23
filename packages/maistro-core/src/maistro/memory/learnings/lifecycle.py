"""Learning lifecycle: contradiction, reinforcement, decay, supersession, consolidation.

ADR-015 made learnings accumulated corrections; ADR-080 gave *episodic* memory its
dynamics. Learnings — the institutional-knowledge records injected into system
prompts — stayed effectively append-only: the dedup path overwrote content in place
and nothing could revise it. This module gives learnings a revisable lifecycle: new
evidence can reinforce, contradict, weaken, combine, supersede or retire an earlier
learning, and none of those updates ever erase the prior version or the evidence.

Shape follows the established side-record pattern of this package (`SkillMutation`,
`LearningApproval`): lifecycle state lives in append-only ledgers keyed by learning
id, held by :class:`InMemoryLearningLifecycle` beside an
:class:`~maistro.memory.learnings.store.InMemoryLearningStore`. The ledger owns the
revisable confidence and the exact-Run/evaluation evidence that the `Learning` row
does not carry, the same way the episodic store's tier dynamics live in
`maistro.memory.episodic.tiers` beside the row (ADR-080 parts A/B, applied to
learnings). Durable twins of the ledger follow, as they did for the episodic store.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.types import CONTRADICT_DELTA, REINFORCE_DELTA, Learning


def _now() -> datetime:
    return datetime.now(UTC)


class LearningLifecycleError(Exception):
    """Base class for lifecycle refusals."""


class UnknownLearningError(LearningLifecycleError):
    """The lifecycle was asked to act on a learning it does not track."""


class InactiveLearningError(LearningLifecycleError):
    """The learning is not active, so the requested revision cannot land on it."""


class EvidenceLinkRequiredError(LearningLifecycleError):
    """Evidence-driven updates must name the exact Run or evaluation that drove them.

    A learning changes confidence because *something* observed it work, fail or
    clash. An update with neither a Run id nor an evaluation id is an
    unattributable mutation of institutional knowledge, and is refused rather
    than recorded with empty provenance.
    """


class LearningEvidenceKind(StrEnum):
    """Why one lifecycle event happened to one learning."""

    CREATED = "created"
    REINFORCED = "reinforced"
    CONTRADICTED = "contradicted"
    WEAKENED = "weakened"
    DECAYED = "decayed"
    SUPERSEDED = "superseded"
    RETIRED = "retired"
    CONSOLIDATED = "consolidated"


#: Kinds that record *why* a learning changed and therefore must name the exact
#: Run or evaluation that drove the change. Decay, retirement and creation are
#: system- or author-driven and may stand without one.
EVIDENCE_DRIVEN_KINDS = frozenset(
    {
        LearningEvidenceKind.REINFORCED,
        LearningEvidenceKind.CONTRADICTED,
        LearningEvidenceKind.WEAKENED,
        LearningEvidenceKind.SUPERSEDED,
        LearningEvidenceKind.CONSOLIDATED,
    }
)


@dataclass(frozen=True)
class EvidenceLink:
    """Where the evidence came from: the exact Run, and optionally evaluation.

    ``run_id`` names the canonical Run (`#709` provenance axes; ``node_run_id``
    and ``attempt_id`` refine it). ``eval_id`` names the evaluation that scored
    the Run's outcome. At least one of the two must be non-blank for
    evidence-driven updates; a blank link cannot be attributed and is refused.
    """

    run_id: str = ""
    node_run_id: str = ""
    attempt_id: str = ""
    eval_id: str = ""

    def resolved(self) -> bool:
        """Whether this link names a Run or an evaluation."""
        return bool(self.run_id.strip()) or bool(self.eval_id.strip())

    def describe(self) -> str:
        """One-line attribution used in evidence notes and logs."""
        parts = [f"run={self.run_id}" if self.run_id else ""]
        parts.append(f"node={self.node_run_id}" if self.node_run_id else "")
        parts.append(f"attempt={self.attempt_id}" if self.attempt_id else "")
        parts.append(f"eval={self.eval_id}" if self.eval_id else "")
        return " ".join(p for p in parts if p)


@dataclass(frozen=True)
class LearningEvidence:
    """One lifecycle event on one learning, in a globally monotonic order."""

    sequence: int
    learning_id: int
    kind: LearningEvidenceKind
    at: datetime
    link: EvidenceLink = field(default_factory=EvidenceLink)
    note: str = ""
    #: The other learning this event is about: the contradicting counterpart,
    #: the replacement in a supersession, the derived record in a consolidation.
    related_learning_id: int | None = None

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError("evidence timestamp must be timezone-aware")
        if self.kind in EVIDENCE_DRIVEN_KINDS and not self.link.resolved():
            raise EvidenceLinkRequiredError(
                f"{self.kind.value} evidence must name a Run or an evaluation"
            )


@dataclass(frozen=True)
class LearningRevision:
    """A preserved prior state of a learning, snapshotted before a change.

    Confidence and status updates amend the live row in place (the in-memory
    store hands back the same instance), so the only place the prior version
    survives is here. Every mutation records the snapshot *before* it mutates;
    revision 1 is the state the learning was first observed in. Within one
    learning the revisions are ordered, and the causing evidence event is the
    last one recorded for that learning at ``at``.
    """

    learning_id: int
    revision: int
    at: datetime
    cause: LearningEvidenceKind
    snapshot: Learning

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError("revision timestamp must be timezone-aware")


@dataclass(frozen=True)
class ConflictRecord:
    """A registered contradiction between two active learnings (ADR-080 part B).

    Never auto-resolved: both sides stay active and retrievable with lowered
    confidence until a reviewer resolves the record and disposes of the sides
    (supersede, weaken, retire) through the lifecycle.
    """

    conflict_id: str
    a_id: int
    b_id: int
    detected_at: datetime
    link: EvidenceLink
    note: str = ""
    resolved: bool = False
    resolution: str = ""

    def __post_init__(self) -> None:
        if self.detected_at.tzinfo is None:
            raise ValueError("conflict timestamp must be timezone-aware")
        if self.a_id == self.b_id:
            raise ValueError("a learning cannot contradict itself")
        if not self.link.resolved():
            raise EvidenceLinkRequiredError(
                "a contradiction record must name the Run or evaluation that detected it"
            )

    def involves(self, learning_id: int) -> bool:
        return learning_id in (self.a_id, self.b_id)


@dataclass(frozen=True)
class ConsolidationRecord:
    """Provenance of a derived learning back to the sources it was combined from."""

    derived_id: int
    source_ids: tuple[int, ...]
    at: datetime
    link: EvidenceLink
    note: str = ""

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError("consolidation timestamp must be timezone-aware")
        if len(set(self.source_ids)) < 2:
            raise ValueError("consolidation combines at least two distinct source learnings")
        if self.derived_id in self.source_ids:
            raise ValueError("the derived record is new; it cannot be one of its own sources")
        if not self.link.resolved():
            raise EvidenceLinkRequiredError(
                "consolidation must name the Run or evaluation that asked for it"
            )


@dataclass(frozen=True)
class LearningStanding:
    """The lifecycle's revisable confidence in one learning, and when it last moved."""

    learning_id: int
    confidence: float
    last_touched_at: datetime

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        if self.last_touched_at.tzinfo is None:
            raise ValueError("last_touched_at must be timezone-aware")


@dataclass(frozen=True)
class LearningDecaySweep:
    """Outcome of one decay pass over tracked active learnings.

    Mirrors the episodic :class:`~maistro.memory.types.DecaySweep` shape, with
    ``retired`` counting learnings decayed past ``retire_below``.
    """

    scanned: int = 0
    decayed: int = 0
    retired: int = 0


@dataclass(frozen=True)
class SurfacedConflict:
    """A conflict surfaced alongside retrieval, with both current sides attached."""

    record: ConflictRecord
    a: Learning
    b: Learning


@dataclass(frozen=True)
class LearningRetrieval:
    """Relevant active learnings plus the conflicts they are known to be in.

    ``learnings`` is the store's active, scope-filtered, keyword-scored result
    re-ranked by lifecycle confidence. ``conflicts`` carries every unresolved
    registered contradiction that touches at least one returned learning —
    including the ones whose counterpart was *not* retrieved — so a consumer
    never sees one side of a known contradiction without the other.
    """

    learnings: list[Learning] = field(default_factory=list)
    conflicts: list[SurfacedConflict] = field(default_factory=list)


@dataclass
class _MutableStanding:
    """Internal, mutable twin of :class:`LearningStanding` (frozen for readers)."""

    confidence: float
    last_touched_at: datetime


class InMemoryLearningLifecycle:
    """Revisable lifecycle over an :class:`InMemoryLearningLifecycle` store's learnings.

    The lifecycle tracks the learnings it observed (``observe``), and every
    later update snapshots the prior state into the revision ledger before it
    mutates. The ledgers are append-only: superseding or retiring sets status
    and never deletes, so `list_all` keeps seeing every learning the org ever
    held, exactly the durable-twin contract.
    """

    def __init__(
        self,
        store: InMemoryLearningStore,
        *,
        reinforce_delta: float = REINFORCE_DELTA,
        weaken_delta: float = CONTRADICT_DELTA,
        #: Confidence lost per hour of staleness. Linear, like the episodic
        #: store's default, so a sweep's cost is proportional to silence.
        decay_per_hour: float = 0.01,
        #: Confidence never decays below this — a lesson that went quiet keeps
        #: a floor until a reviewer retires it, mirroring REGRET's floor.
        decay_floor: float = 0.1,
        #: When set, a decay pass retires a learning whose confidence fell to
        #: this level; stale knowledge leaves retrieval with evidence, not by
        #: deletion.
        retire_below: float | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._store = store
        self._reinforce_delta = reinforce_delta
        self._weaken_delta = weaken_delta
        self._decay_per_hour = decay_per_hour
        self._decay_floor = decay_floor
        self._retire_below = retire_below
        self._clock = clock
        self._tracked: dict[int, Learning] = {}
        self._standing: dict[int, _MutableStanding] = {}
        self._revisions: dict[int, list[LearningRevision]] = {}
        self._evidence: dict[int, list[LearningEvidence]] = {}
        self._conflicts: dict[str, ConflictRecord] = {}
        self._consolidations: list[ConsolidationRecord] = []
        self._sequence = 0

    # ── observation ──────────────────────────────────────────────────

    async def observe(self, learning: Learning, *, link: EvidenceLink | None = None) -> int:
        """Store a learning through the underlying store and start tracking it.

        With no link given, the CREATED evidence reuses the provenance the
        store filled from the ambient execution context, so creation evidence
        still names the Run that produced the learning (#709).
        """
        learning_id = await self._store.store(learning)
        # After a dedup hit the store kept the pre-existing object and its id;
        # track the store's instance, not the caller's orphan.
        tracked = self._store.get(learning_id) or learning
        resolved_link = link or EvidenceLink(
            run_id=tracked.run_id,
            node_run_id=tracked.node_run_id,
            attempt_id=tracked.attempt_id,
        )
        now = self._clock()
        self._tracked[learning_id] = tracked
        self._standing[learning_id] = _MutableStanding(
            confidence=DEFAULT_CONFIDENCE, last_touched_at=now
        )
        self._record(
            learning_id,
            LearningEvidenceKind.CREATED,
            resolved_link,
            at=now,
            note="observed",
        )
        self._snapshot(learning_id, LearningEvidenceKind.CREATED, now)
        return learning_id

    # ── reinforcement / weakening ─────────────────────────────────────

    async def reinforce(
        self,
        learning_ids: Sequence[int],
        *,
        link: EvidenceLink,
        note: str = "",
    ) -> list[Learning]:
        """Raise confidence for each learning, citing the Run/evaluation that proved it."""
        return await self._shift(learning_ids, +self._reinforce_delta, link, note=note)

    async def weaken(
        self,
        learning_ids: Sequence[int],
        *,
        link: EvidenceLink,
        note: str = "",
        delta: float | None = None,
    ) -> list[Learning]:
        """Lower confidence for each learning, citing the Run/evaluation that disproved it."""
        return await self._shift(
            learning_ids, -(delta if delta is not None else self._weaken_delta), link, note=note
        )

    async def _shift(
        self,
        learning_ids: Sequence[int],
        amount: float,
        link: EvidenceLink,
        *,
        note: str,
    ) -> list[Learning]:
        if not link.resolved():
            raise EvidenceLinkRequiredError(
                "reinforcement and weakening evidence must name a Run or an evaluation"
            )
        kind = LearningEvidenceKind.REINFORCED if amount > 0 else LearningEvidenceKind.WEAKENED
        updated: list[Learning] = []
        seen: set[int] = set()
        for learning_id in learning_ids:
            if learning_id in seen:
                continue
            seen.add(learning_id)
            learning = self._require(learning_id)
            self._require_active(learning)
            now = self._clock()
            self._snapshot(learning_id, kind, now)
            standing = self._standing[learning_id]
            standing.confidence = _clamp(standing.confidence + amount)
            standing.last_touched_at = now
            self._record(learning_id, kind, link, at=now, note=note)
            updated.append(learning)
        return updated

    # ── contradiction ────────────────────────────────────────────────

    async def record_contradiction(
        self, a_id: int, b_id: int, *, link: EvidenceLink, note: str = ""
    ) -> ConflictRecord:
        """Register that two active learnings contradict, and lower both sides.

        Follows ADR-080 part B for learnings: both sides lose confidence and
        the pair is flagged for review — no winner is picked, neither side is
        discarded, and both remain active and retrievable while unresolved.
        Registering the same unresolved pair again appends fresh evidence and
        lowers both sides again but does not duplicate the record.
        """
        if a_id == b_id:
            raise ValueError("a learning cannot contradict itself")
        a = self._require(a_id)
        b = self._require(b_id)
        for learning in (a, b):
            self._require_active(learning)
        now = self._clock()
        record = self._unresolved_record(a_id, b_id)
        if record is None:
            record = ConflictRecord(
                conflict_id=uuid4().hex,
                a_id=a_id,
                b_id=b_id,
                detected_at=now,
                link=link,
                note=note,
            )
            self._conflicts[record.conflict_id] = record
        for side, other in ((a_id, b_id), (b_id, a_id)):
            self._snapshot(side, LearningEvidenceKind.CONTRADICTED, now)
            standing = self._standing[side]
            standing.confidence = _clamp(standing.confidence - self._weaken_delta)
            standing.last_touched_at = now
            self._record(
                side,
                LearningEvidenceKind.CONTRADICTED,
                link,
                at=now,
                note=note,
                related_learning_id=other,
            )
        return record

    def _unresolved_record(self, a_id: int, b_id: int) -> ConflictRecord | None:
        for record in self._conflicts.values():
            if not record.resolved and record.involves(a_id) and record.involves(b_id):
                return record
        return None

    def _active_tracked_sides(self, record: ConflictRecord) -> tuple[Learning, Learning] | None:
        """Both tracked, active sides of a conflict, or None if it no longer applies."""
        side_a = self._tracked.get(record.a_id)
        side_b = self._tracked.get(record.b_id)
        if side_a is None or side_b is None:
            return None
        if side_a.status != "active" or side_b.status != "active":
            return None
        return side_a, side_b

    async def find_conflicts(
        self, *, org_id: str = "", include_resolved: bool = False
    ) -> list[ConflictRecord]:
        """Registered contradictions whose sides are still tracked and active.

        This is the "conflicting active learnings are detectable" read: an
        evaluation harness or review queue calls this to see which pairs of
        live institutional knowledge disagree. A side that was superseded or
        retired drops the pair out of the default result — the conflict is no
        longer between *active* learnings.
        """
        results: list[ConflictRecord] = []
        for record in self._conflicts.values():
            if record.resolved and not include_resolved:
                continue
            sides = self._active_tracked_sides(record)
            if sides is None:
                continue
            side_a, side_b = sides
            if org_id and (side_a.org_id != org_id or side_b.org_id != org_id):
                continue
            results.append(record)
        return results

    async def resolve_conflict(self, conflict_id: str, *, resolution: str) -> ConflictRecord:
        """Mark a contradiction reviewed. Disposing of the sides is a separate act."""
        record = self._conflicts.get(conflict_id)
        if record is None:
            raise UnknownLearningError(conflict_id)
        if not resolution.strip():
            raise ValueError("a resolution must say what the review decided")
        resolved = dataclasses.replace(record, resolved=True, resolution=resolution)
        self._conflicts[conflict_id] = resolved
        return resolved

    # ── supersession / retirement ────────────────────────────────────

    async def supersede(
        self, old_id: int, replacement: Learning, *, link: EvidenceLink, note: str = ""
    ) -> tuple[Learning, Learning]:
        """Replace one active learning with a newer statement of the same lesson.

        The old record keeps its row — status ``superseded``, out of retrieval,
        still visible to `list_all` and to this lifecycle's history — and the
        replacement is stored fresh with evidence pointing back at it.
        """
        if not link.resolved():
            raise EvidenceLinkRequiredError(
                "supersession must name the Run or evaluation that produced the replacement"
            )
        old = self._require(old_id)
        self._require_active(old)
        now = self._clock()
        self._snapshot(old_id, LearningEvidenceKind.SUPERSEDED, now)
        # Retire the old row *before* storing the replacement: the store's
        # dedup probe only matches `active` rows, and a replacement usually
        # overlaps its own predecessor's trigger keys. Storing first would
        # overwrite the old record's content in place — exactly the erase
        # this lifecycle exists to prevent.
        old.status = "superseded"
        new_id = await self._store.store(replacement)
        new = self._store.get(new_id) or replacement
        self._tracked[old_id] = old
        self._tracked[new_id] = new
        self._standing[new_id] = _MutableStanding(
            confidence=DEFAULT_CONFIDENCE, last_touched_at=now
        )
        self._record(
            old_id,
            LearningEvidenceKind.SUPERSEDED,
            link,
            at=now,
            note=note,
            related_learning_id=new_id,
        )
        self._record(
            new_id,
            LearningEvidenceKind.SUPERSEDED,
            link,
            at=now,
            note=note or "supersedes an earlier statement",
            related_learning_id=old_id,
        )
        self._snapshot(new_id, LearningEvidenceKind.SUPERSEDED, now)
        return old, new

    async def retire(
        self, learning_ids: Sequence[int], *, reason: str, link: EvidenceLink | None = None
    ) -> list[Learning]:
        """Retire learnings: out of retrieval, preserved in the store, with a reason."""
        if not reason.strip():
            raise ValueError("retirement must carry a reason")
        retired: list[Learning] = []
        seen: set[int] = set()
        for learning_id in learning_ids:
            if learning_id in seen:
                continue
            seen.add(learning_id)
            learning = self._require(learning_id)
            self._require_active(learning)
            now = self._clock()
            learning.status = "retired"
            standing = self._standing[learning_id]
            standing.last_touched_at = now
            self._snapshot(learning_id, LearningEvidenceKind.RETIRED, now)
            self._record(
                learning_id,
                LearningEvidenceKind.RETIRED,
                link or EvidenceLink(),
                at=now,
                note=reason,
            )
            retired.append(learning)
        return retired

    # ── consolidation ────────────────────────────────────────────────

    def _validated_consolidation_sources(self, source_ids: Sequence[int]) -> list[Learning]:
        """Deduplicated, tracked, active sources — at least two of them."""
        sources = [self._require(source_id) for source_id in dict.fromkeys(source_ids)]
        if len(sources) < 2:
            raise ValueError("consolidation combines at least two distinct source learnings")
        for source in sources:
            self._require_active(source)
        return sources

    def _mark_sources_consolidated(self, sources: list[Learning], *, at: datetime) -> None:
        """Take every source out of the active set, snapshotting each first.

        Runs before the derived row is stored — same ordering as `supersede` —
        so the store's dedup probe cannot land the merged content on a source
        and erase it in place.
        """
        for source in sources:
            source.status = "consolidated"
            assert source.id is not None
            self._snapshot(source.id, LearningEvidenceKind.CONSOLIDATED, at)

    def _record_source_consolidations(
        self,
        source_ids: list[int],
        *,
        derived_id: int,
        link: EvidenceLink,
        at: datetime,
        note: str,
    ) -> None:
        """Give each source CONSOLIDATED evidence pointing at the derived row."""
        for source_id in source_ids:
            self._record(
                source_id,
                LearningEvidenceKind.CONSOLIDATED,
                link,
                at=at,
                note=note,
                related_learning_id=derived_id,
            )

    async def consolidate(
        self,
        source_ids: Sequence[int],
        merged: Learning,
        *,
        link: EvidenceLink,
        note: str = "",
    ) -> tuple[Learning, ConsolidationRecord]:
        """Combine active learnings into one new derived record, keeping the sources.

        The derived learning is stored as a fresh row; every source is marked
        ``consolidated`` and kept, and the record ties the derived id back to
        the exact source ids. Content-bearing consolidation judgments (what to
        write into ``merged``) belong to the caller, as they do for the
        episodic merge proposals in SPEC-241.
        """
        if not link.resolved():
            raise EvidenceLinkRequiredError(
                "consolidation must name the Run or evaluation that asked for it"
            )
        sources = self._validated_consolidation_sources(source_ids)
        resolved_ids: list[int] = []
        for source in sources:
            assert source.id is not None
            resolved_ids.append(source.id)
        now = self._clock()
        self._mark_sources_consolidated(sources, at=now)
        derived_id = await self._store.store(merged)
        derived = self._store.get(derived_id) or merged
        self._tracked[derived_id] = derived
        self._standing[derived_id] = _MutableStanding(
            confidence=max(self._standing[sid].confidence for sid in resolved_ids),
            last_touched_at=now,
        )
        self._record_source_consolidations(
            resolved_ids, derived_id=derived_id, link=link, at=now, note=note
        )
        self._record(
            derived_id,
            LearningEvidenceKind.CONSOLIDATED,
            link,
            at=now,
            note=note or "derived from consolidated sources",
        )
        self._snapshot(derived_id, LearningEvidenceKind.CONSOLIDATED, now)
        record = ConsolidationRecord(
            derived_id=derived_id,
            source_ids=tuple(sid for sid in resolved_ids if sid is not None),
            at=now,
            link=link,
            note=note,
        )
        self._consolidations.append(record)
        return derived, record

    # ── decay ────────────────────────────────────────────────────────

    async def decay(self, *, now: datetime | None = None) -> LearningDecaySweep:
        """Lower confidence of active learnings that went untouched (ADR-080 part A).

        Staleness is measured from each learning's last lifecycle touch, so a
        reinforced learning restarts its decay clock. A pass charges only the
        interval since that touch: repeated sweeps never double-charge the
        same silent hours. Crossing ``retire_below`` retires the learning with
        decay as the recorded reason.
        """
        at = now or self._clock()
        if at.tzinfo is None:
            raise ValueError("decay timestamp must be timezone-aware")
        scanned = decayed = retired = 0
        for learning_id, learning in list(self._tracked.items()):
            if learning.status != "active":
                continue
            scanned += 1
            standing = self._standing[learning_id]
            silent_hours = max((at - standing.last_touched_at).total_seconds() / 3600.0, 0.0)
            drop = self._decay_per_hour * silent_hours
            if drop <= 0.0:
                continue
            self._snapshot(learning_id, LearningEvidenceKind.DECAYED, at)
            standing.confidence = max(self._decay_floor, standing.confidence - drop)
            standing.last_touched_at = at
            self._record(
                learning_id,
                LearningEvidenceKind.DECAYED,
                EvidenceLink(),
                at=at,
                note=f"silent for {silent_hours:.2f}h",
            )
            decayed += 1
            if self._retire_below is not None and standing.confidence <= self._retire_below:
                learning.status = "retired"
                self._snapshot(learning_id, LearningEvidenceKind.RETIRED, at)
                self._record(
                    learning_id,
                    LearningEvidenceKind.RETIRED,
                    EvidenceLink(),
                    at=at,
                    note=f"confidence decayed to {standing.confidence:.2f}",
                )
                retired += 1
        return LearningDecaySweep(scanned=scanned, decayed=decayed, retired=retired)

    # ── retrieval ────────────────────────────────────────────────────

    async def find_relevant(
        self,
        user_text: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        org_id: str = "",
        max_results: int = 10,
    ) -> LearningRetrieval:
        """Relevant active learnings re-ranked by lifecycle confidence, plus their conflicts.

        The store's keyword scoring stays the primary key — relevance is still
        about the query — and confidence breaks ties and orders equal scores,
        so a reinforced lesson outranks a decayed one that mentions the same
        trigger word (ADR-080 part D applied to learnings).
        """
        matched = await self._store.find_relevant(
            user_text,
            agent_id=agent_id,
            user_id=user_id,
            team_id=team_id,
            org_id=org_id,
            max_results=max_results,
        )
        # Stable sort: the store's keyword score stays the primary key and
        # confidence only orders among equally relevant learnings.
        matched.sort(
            key=lambda lr: (
                -(
                    self._standing[lr.id].confidence
                    if lr.id in self._standing
                    else DEFAULT_CONFIDENCE
                )
            )
        )
        conflicts = await self._conflicts_touching(
            [lr.id for lr in matched if lr.id is not None], org_id=org_id
        )
        return LearningRetrieval(learnings=matched, conflicts=conflicts)

    async def _conflicts_touching(
        self, learning_ids: list[int], *, org_id: str
    ) -> list[SurfacedConflict]:
        touched = set(learning_ids)
        surfaced: list[SurfacedConflict] = []
        for record in await self.find_conflicts(org_id=org_id):
            if not touched & {record.a_id, record.b_id}:
                continue
            a = self._tracked[record.a_id]
            b = self._tracked[record.b_id]
            surfaced.append(SurfacedConflict(record=record, a=a, b=b))
        return surfaced

    # ── reads ────────────────────────────────────────────────────────

    async def standing(self, learning_id: int) -> LearningStanding:
        mutable = self._standing.get(learning_id)
        if mutable is None:
            raise UnknownLearningError(str(learning_id))
        return LearningStanding(
            learning_id=learning_id,
            confidence=mutable.confidence,
            last_touched_at=mutable.last_touched_at,
        )

    async def current(self, learning_id: int) -> Learning:
        return self._require(learning_id)

    async def evidence_for(self, learning_id: int) -> list[LearningEvidence]:
        """All lifecycle evidence for one learning, oldest first."""
        self._require(learning_id)
        return list(self._evidence.get(learning_id, ()))

    async def revisions_for(self, learning_id: int) -> list[LearningRevision]:
        """Every preserved prior state of one learning, oldest first."""
        self._require(learning_id)
        return list(self._revisions.get(learning_id, ()))

    # ── internals ────────────────────────────────────────────────────

    def _require(self, learning_id: int) -> Learning:
        learning = self._tracked.get(learning_id)
        if learning is None:
            raise UnknownLearningError(str(learning_id))
        return learning

    def _require_active(self, learning: Learning) -> None:
        if learning.status != "active":
            raise InactiveLearningError(
                f"learning {learning.id} is {learning.status!r}, not active"
            )

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _record(
        self,
        learning_id: int,
        kind: LearningEvidenceKind,
        link: EvidenceLink,
        *,
        at: datetime,
        note: str = "",
        related_learning_id: int | None = None,
    ) -> LearningEvidence:
        evidence = LearningEvidence(
            sequence=self._next_sequence(),
            learning_id=learning_id,
            kind=kind,
            at=at,
            link=link,
            note=note,
            related_learning_id=related_learning_id,
        )
        self._evidence.setdefault(learning_id, []).append(evidence)
        return evidence

    def _snapshot(self, learning_id: int, cause: LearningEvidenceKind, at: datetime) -> None:
        """Preserve the current state before the caller mutates it."""
        learning = self._tracked[learning_id]
        revisions = self._revisions.setdefault(learning_id, [])
        snapshot = dataclasses.replace(learning, trigger_keys=list(learning.trigger_keys))
        revisions.append(
            LearningRevision(
                learning_id=learning_id,
                revision=len(revisions) + 1,
                at=at,
                cause=cause,
                snapshot=snapshot,
            )
        )


#: Confidence a learning starts with, before any evidence moves it.
DEFAULT_CONFIDENCE: float = 0.5


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
