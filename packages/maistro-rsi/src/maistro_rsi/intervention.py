"""Stall detection, lineage review, and reseeding — the RSI intervention policy.

A healthy hypothesis loop eventually improves; a *stalled* one burns real
agent/test cycles re-deriving the same dead end. This module is the M5-B
intervention policy the coordinator invokes when cycles stop improving:

  1. **Detect** — `StallTracker` counts consecutive non-improving cycles and
     fires once at the configured threshold (N), so the threshold is both
     configurable and observable in the log event that announces the stall.
  2. **Review** — a `LineageReviewer` is invoked over the *actual candidate
     lineage/evidence*: the root-to-failure chain of the stalled branch with
     every ancestor's hypothesis, recorded evidence, and distilled insight —
     plus the tree's archive of promising explored candidates — never only the
     latest failed candidate.
  3. **Reseed** — the reviewer's K directions are filtered down to the
     *materially distinct* ones (duplicates of each other or of hypotheses
     already tried on the presented lineage are dropped, not re-run), then each
     surviving direction is expanded as a new OPEN node, branching from the
     archived candidate the direction names — an older promising node, not only
     the current champion/latest seed.
  4. **Provenance** — every reseeded node carries its ``intervention_id``
     artifact and every direction is preserved verbatim on the `Intervention`
     record, so an intervention is reconstructible from the tree alone.
  5. **Measurability** — each `Intervention` records its cost (the stalled
     cycles that funded it, the reviewer's wall-clock) and its subsequent gain
     (best-score delta measured after reseeding), and once ``park_after``
     consecutive interventions have produced no gain the objective is *parked*:
     `ObjectiveParked` stops the run so the caller's backlog policy — not the
     loop itself — decides whether the objective is ever retried.

The module is pure: no sandbox, git, or network. The coordinator wires it in;
tests reason about the policy without any executor at all.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog

from maistro_rsi.htr import HypothesisNode, HypothesisTree, NodeStatus

logger = structlog.get_logger()

__all__ = [
    "ArchiveCandidate",
    "Intervention",
    "InterventionConfig",
    "InterventionPolicy",
    "LineageReviewContext",
    "LineageReviewer",
    "LineageStep",
    "ObjectiveParked",
    "ReseedDirection",
    "StallTracker",
    "materially_distinct",
    "template_lineage_reviewer",
]


@dataclass(frozen=True)
class LineageStep:
    """One ancestor on the presented lineage: its hypothesis, the evidence it
    produced (``None`` while unexecuted), and its distilled insight. The
    reviewer sees the whole chain — an abandoned ancestor's lesson is exactly
    what keeps the K directions from re-proposing it."""

    node_id: str
    hypothesis: str
    depth: int
    status: str
    insight: str | None = None
    tests_passed: bool | None = None
    benchmarks_won: int | None = None
    battles: int | None = None
    improved: bool | None = None

    @classmethod
    def from_node(cls, node: HypothesisNode) -> LineageStep:
        evidence = node.evidence
        return cls(
            node_id=node.id,
            hypothesis=node.hypothesis,
            depth=node.depth,
            status=node.status.value,
            insight=node.insight,
            tests_passed=evidence.tests_passed if evidence else None,
            benchmarks_won=evidence.benchmarks_won if evidence else None,
            battles=evidence.battles if evidence else None,
            improved=evidence.improved if evidence else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Plain-data form for intervention-state checkpoints."""
        return {
            "node_id": self.node_id,
            "hypothesis": self.hypothesis,
            "depth": self.depth,
            "status": self.status,
            "insight": self.insight,
            "tests_passed": self.tests_passed,
            "benchmarks_won": self.benchmarks_won,
            "battles": self.battles,
            "improved": self.improved,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LineageStep:
        """Rebuild from :meth:`to_dict` output."""
        return cls(
            node_id=data["node_id"],
            hypothesis=data["hypothesis"],
            depth=int(data["depth"]),
            status=data["status"],
            insight=data.get("insight"),
            tests_passed=data.get("tests_passed"),
            benchmarks_won=data.get("benchmarks_won"),
            battles=data.get("battles"),
            improved=data.get("improved"),
        )


@dataclass(frozen=True)
class ArchiveCandidate:
    """One promising archived (EXPLORED) candidate offered as a possible
    reseed branch point. The archive is *not* the champion alone: older, lower-
    ranked branches that once showed promise appear here too, because a stalled
    champion is precisely the wrong place to keep branching from."""

    node_id: str
    hypothesis: str
    score: float
    depth: int

    @classmethod
    def from_node(cls, node: HypothesisNode) -> ArchiveCandidate:
        return cls(
            node_id=node.id,
            hypothesis=node.hypothesis,
            score=node.score or 0.0,
            depth=node.depth,
        )


@dataclass(frozen=True)
class LineageReviewContext:
    """Everything a reviewer may ground its directions in: the stalled node,
    how many cycles stalled, the full root-to-failure lineage **with evidence**
    (never only the latest failed candidate), and the archived promising
    candidates available as reseed branch points."""

    failed_node_id: str
    stalled_cycles: int
    lineage: tuple[LineageStep, ...]
    archive: tuple[ArchiveCandidate, ...]


@dataclass(frozen=True)
class ReseedDirection:
    """One reviewer-returned direction. ``seed_node_id`` names the archived
    candidate to branch from (``None`` → the tree's own most promising seed)."""

    text: str
    seed_node_id: str | None = None


#: Invoked by the coordinator once a stall is confirmed; returns the candidate
#: directions to reseed from. Async to match the executor seam — a real reviewer
#: calls a model.
LineageReviewer = Callable[[LineageReviewContext], Awaitable[Sequence[ReseedDirection]]]


def _normalize(text: str) -> str:
    """Fold a hypothesis/direction to its comparable substance: casefolded,
    whitespace-collapsed, punctuation-stripped."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip().lower()


def materially_distinct(
    directions: Sequence[ReseedDirection],
    context: LineageReviewContext,
) -> list[ReseedDirection]:
    """Filter the reviewer's directions down to the materially distinct ones.

    A direction is *materially* the same as something already present when its
    normalized text equals the normalized text of (a) another surviving
    direction, or (b) any hypothesis on the presented lineage — including the
    failed node's own hypothesis. Re-running a reworded dead end is the exact
    waste stall intervention exists to stop, so near-identical rewordings are
    dropped here, not left for the executor to burn a cycle on.
    """
    tried = {_normalize(step.hypothesis) for step in context.lineage}
    distinct: list[ReseedDirection] = []
    seen: set[str] = set()
    for direction in directions:
        text = direction.text.strip()
        if not text:
            continue
        key = _normalize(text)
        if key in tried or key in seen:
            continue
        seen.add(key)
        distinct.append(ReseedDirection(text=text, seed_node_id=direction.seed_node_id))
    return distinct


@dataclass
class Intervention:
    """The provenance + measurement record of one stall intervention.

    Preserved on `CoordinatorResult.interventions` and, via the reseeded
    nodes' ``intervention_id`` artifacts, in the tree snapshot itself — the
    directions the reviewer returned are never discarded. Cost and gain are
    both recorded so every intervention is measurable: ``stalled_cycles`` and
    ``reviewer_seconds`` are the cost side; ``subsequent_gain`` is set by the
    coordinator as soon as any later cycle yields a new best-score reading.
    """

    index: int
    trigger_node_id: str
    stalled_cycles: int
    stall_threshold: int
    lineage: tuple[LineageStep, ...]
    archive: tuple[ArchiveCandidate, ...]
    directions: tuple[ReseedDirection, ...] = ()
    seed_node_ids: tuple[str, ...] = ()
    reviewer_seconds: float = 0.0
    best_score_at_trigger: float = 0.0
    subsequent_gain: float | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Plain-data form for audit trails and checkpoints."""
        return {
            "index": self.index,
            "created_at": self.created_at,
            "trigger_node_id": self.trigger_node_id,
            "stalled_cycles": self.stalled_cycles,
            "stall_threshold": self.stall_threshold,
            "lineage": [vars(step) for step in self.lineage],
            "archive": [vars(candidate) for candidate in self.archive],
            "directions": [
                {"text": d.text, "seed_node_id": d.seed_node_id} for d in self.directions
            ],
            "seed_node_ids": list(self.seed_node_ids),
            "reviewer_seconds": self.reviewer_seconds,
            "best_score_at_trigger": self.best_score_at_trigger,
            "subsequent_gain": self.subsequent_gain,
        }

    @property
    def cost(self) -> dict[str, float | int]:
        """The measurable cost of this intervention: the stalled cycles that
        funded it and the reviewer's wall-clock."""
        return {
            "stalled_cycles": self.stalled_cycles,
            "reviewer_seconds": self.reviewer_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Intervention:
        """Rebuild from :meth:`to_dict` output (intervention-state resume)."""
        return cls(
            index=int(data["index"]),
            trigger_node_id=data["trigger_node_id"],
            stalled_cycles=int(data["stalled_cycles"]),
            stall_threshold=int(data["stall_threshold"]),
            lineage=tuple(LineageStep.from_dict(step) for step in data["lineage"]),
            archive=tuple(
                ArchiveCandidate(
                    node_id=candidate["node_id"],
                    hypothesis=candidate["hypothesis"],
                    score=float(candidate["score"]),
                    depth=int(candidate["depth"]),
                )
                for candidate in data["archive"]
            ),
            directions=tuple(
                ReseedDirection(
                    text=direction["text"],
                    seed_node_id=direction.get("seed_node_id"),
                )
                for direction in data["directions"]
            ),
            seed_node_ids=tuple(data.get("seed_node_ids", ())),
            reviewer_seconds=float(data.get("reviewer_seconds", 0.0)),
            best_score_at_trigger=float(data.get("best_score_at_trigger", 0.0)),
            subsequent_gain=(
                float(data["subsequent_gain"]) if data.get("subsequent_gain") is not None else None
            ),
            created_at=float(data.get("created_at", time.time())),
        )


class StallTracker:
    """Counts consecutive non-improving cycles; fires once the configured
    threshold (N) is reached. The threshold is validated at construction — a
    non-positive threshold would fire on the first cycle (or never), and both
    are configuration errors, not runtime surprises."""

    def __init__(self, threshold: int) -> None:
        if threshold < 1:
            raise ValueError(f"stall threshold must be >= 1, got {threshold}")
        self.threshold = threshold
        self.consecutive_non_improving = 0

    def record(self, improved: bool) -> bool:
        """Fold one cycle's outcome in; ``True`` exactly when the stall
        threshold is *reached by this cycle* (fires once per stall, not on
        every further non-improving cycle)."""
        if improved:
            self.consecutive_non_improving = 0
            return False
        self.consecutive_non_improving += 1
        return self.consecutive_non_improving == self.threshold

    def reset(self) -> None:
        self.consecutive_non_improving = 0


class ObjectiveParked(RuntimeError):
    """The objective has consumed ``park_after`` interventions without any of
    them producing a gain — the loop stops spending on it and hands the parked
    objective (with every intervention's provenance) back to the caller, whose
    backlog policy decides whether and when it is ever retried.

    A ``RuntimeError`` subclass so bare ``except Exception`` handlers keep
    treating a park as a run-level stop; a distinct type so no caller has to
    match on the message text.
    """

    def __init__(
        self,
        objective: str,
        interventions: tuple[Intervention, ...],
        steps: tuple[str, ...] = (),
    ) -> None:
        self.objective = objective
        self.interventions = interventions
        # Node ids the coordinator executed in the run that raised this park:
        # the triggering cycle runs and records its node BEFORE intervening, so
        # a caller that persists steps only from a returned CoordinatorResult
        # would drop an already-executed experiment and leave its node OPEN in
        # the on-disk snapshot — re-executed by a later resume.
        self.steps = steps
        super().__init__(
            f"objective parked after {len(interventions)} intervention(s) without improvement: "
            f"{objective!r}"
        )


def template_lineage_reviewer(context: LineageReviewContext) -> list[ReseedDirection]:
    """Deterministic fallback reviewer: one distinct refinement direction per
    archived candidate (round-robin), phrased from the lineage's distilled
    lessons. Degrades to the failed node's own hypothesis when the archive is
    empty; the coordinator's distinctness filter drops anything that merely
    rewords a tried hypothesis, so this can never reseed a dead end verbatim."""
    archive = list(context.archive)
    if not archive:
        archive = [
            ArchiveCandidate(
                node_id=context.failed_node_id,
                hypothesis=(context.lineage[-1].hypothesis if context.lineage else ""),
                score=0.0,
                depth=0,
            )
        ]
    directions: list[ReseedDirection] = []
    for position, candidate in enumerate(archive):
        lessons = [step.insight for step in context.lineage if step.insight]
        lesson = lessons[-1] if lessons else "no lessons recorded yet"
        directions.append(
            ReseedDirection(
                text=(
                    f"Alternative direction #{position + 1}: revisit {candidate.hypothesis} "
                    f"from a different angle, avoiding the recorded lesson: {lesson}"
                ),
                seed_node_id=candidate.node_id,
            )
        )
    return directions


async def _template_reviewer(context: LineageReviewContext) -> Sequence[ReseedDirection]:
    """Adapt the sync template reviewer to the async reviewer seam."""
    return template_lineage_reviewer(context)


@dataclass
class InterventionConfig:
    """Knobs of the intervention policy — every threshold is configurable and
    every firing is logged by the coordinator."""

    #: N consecutive non-improving cycles that constitute a stall.
    stall_threshold: int = 3
    #: K materially distinct directions requested from the reviewer.
    direction_count: int = 3
    #: After this many interventions with no subsequent gain, the objective is
    #: parked (``ObjectiveParked``) instead of receiving another intervention.
    park_after: int = 2
    #: How many archived promising candidates the reviewer may see.
    archive_limit: int = 8

    def __post_init__(self) -> None:
        if self.stall_threshold < 1:
            raise ValueError(f"stall threshold must be >= 1, got {self.stall_threshold}")
        if self.direction_count < 1:
            raise ValueError(f"direction count must be >= 1, got {self.direction_count}")
        if self.park_after < 1:
            raise ValueError(f"park_after must be >= 1, got {self.park_after}")
        if self.archive_limit < 1:
            raise ValueError(f"archive limit must be >= 1, got {self.archive_limit}")


class InterventionPolicy:
    """The coordinator-side intervention machinery: stall detection, lineage
    review invocation, distinctness-enforced reseeding, provenance records,
    gain measurement, and parking.

    Pure with respect to the tree: the reviewer is injected, the archive is
    read from the tree's own EXPLORED nodes, and reseeding is ordinary
    ``expand`` calls — so the policy is testable without any executor.
    """

    def __init__(
        self,
        config: InterventionConfig | None = None,
        reviewer: LineageReviewer | None = None,
    ) -> None:
        self.config = config or InterventionConfig()
        self.reviewer: LineageReviewer = reviewer or _template_reviewer
        self.tracker = StallTracker(self.config.stall_threshold)
        self.interventions: list[Intervention] = []
        self._next_index = 0

    # -- durable state (resume) -----------------------------------------------

    @property
    def next_index(self) -> int:
        """Index the next intervention will get (for resume logging)."""
        return self._next_index

    def state_dict(self) -> dict[str, Any]:
        """Plain-data snapshot of the policy's *mutable* state for the tree
        checkpoint: the stall streak, every intervention record, and the next
        intervention index. Resumable campaigns persist this beside the tree so
        a boundary (wall-clock, cycle budget, crash) never resets a non-
        improving streak to zero, drops prior gainless interventions from the
        ``park_after`` accounting, or reissues an already-used
        ``intervention_id``."""
        return {
            "tracker": {
                "consecutive_non_improving": self.tracker.consecutive_non_improving,
            },
            "interventions": [intervention.to_dict() for intervention in self.interventions],
            "next_index": self._next_index,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Restore from :meth:`state_dict` output on a resumed tree. The
        configuration (thresholds) always comes from the *current* run; only
        the accumulated state crosses the boundary."""
        tracker = state["tracker"]
        self.tracker.consecutive_non_improving = int(tracker["consecutive_non_improving"])
        self.interventions = [Intervention.from_dict(record) for record in state["interventions"]]
        self._next_index = int(state["next_index"])

    # -- stall detection ------------------------------------------------------

    def observe(self, improved: bool) -> bool:
        """Fold one completed cycle in; ``True`` when a stall is detected this
        cycle (threshold reached — logged once per stall by the caller)."""
        return self.tracker.record(improved)

    # -- review context -------------------------------------------------------

    def review_context(self, tree: HypothesisTree, failed_node_id: str) -> LineageReviewContext:
        """Build what the reviewer sees: the failed node's *full* root-to-node
        lineage with evidence, plus the tree's archived promising candidates —
        never only the latest failed candidate."""
        lineage = tuple(LineageStep.from_node(node) for node in tree.lineage(failed_node_id))
        archive = tuple(
            ArchiveCandidate.from_node(node)
            for node in tree.expandable_seeds()[: self.config.archive_limit]
        )
        return LineageReviewContext(
            failed_node_id=failed_node_id,
            stalled_cycles=self.tracker.consecutive_non_improving,
            lineage=lineage,
            archive=archive,
        )

    # -- the intervention itself ---------------------------------------------

    def _gainless_interventions(self) -> int:
        return sum(
            1 for i in self.interventions if i.subsequent_gain is None or i.subsequent_gain <= 0
        )

    async def intervene(self, tree: HypothesisTree, failed_node_id: str) -> Intervention:
        """Review the stalled lineage and reseed the tree from the materially
        distinct directions.

        Each surviving direction is expanded from the archived candidate it
        names (falling back to the tree's own most promising seed when it names
        none, or one that is unknown or abandoned); every reseeded node records
        its ``intervention_id`` artifact and the `Intervention` record
        preserves the returned directions verbatim. Raises
        :class:`ObjectiveParked` *instead of intervening* once ``park_after``
        interventions have produced no subsequent gain.
        """
        if self.interventions and self._gainless_interventions() >= self.config.park_after:
            raise ObjectiveParked(
                objective=tree.nodes[tree.root_id].hypothesis,
                interventions=tuple(self.interventions),
            )
        context = self.review_context(tree, failed_node_id)
        best = tree.best_node()
        intervention = Intervention(
            index=self._next_index,
            trigger_node_id=failed_node_id,
            stalled_cycles=context.stalled_cycles,
            stall_threshold=self.config.stall_threshold,
            lineage=context.lineage,
            archive=context.archive,
            best_score_at_trigger=(best.score or 0.0) if best is not None else 0.0,
        )
        self._next_index += 1

        started = time.monotonic()
        returned = list(await self.reviewer(context))
        intervention.reviewer_seconds = time.monotonic() - started
        requested = self.config.direction_count
        considered = returned[:requested]
        distinct = materially_distinct(considered, context)
        dropped = len(considered) - len(distinct)
        if dropped:
            await logger.ainfo(
                "htr_intervention_directions_deduped",
                intervention_index=intervention.index,
                dropped=dropped,
                kept=len(distinct),
                requested=requested,
            )
        intervention.directions = tuple(distinct)

        seed_ids: list[str] = []
        for direction in distinct:
            seed_id = direction.seed_node_id
            if seed_id is None or not self._expandable(tree, seed_id):
                seed_id = tree.select_seed().id
            node = tree.expand(seed_id, direction.text)
            node.artifacts["intervention_id"] = str(intervention.index)
            seed_ids.append(node.id)
        intervention.seed_node_ids = tuple(seed_ids)
        self.interventions.append(intervention)
        self.tracker.reset()
        await logger.ainfo(
            "htr_intervention_reseeded",
            intervention_index=intervention.index,
            stalled_cycles=intervention.stalled_cycles,
            stall_threshold=intervention.stall_threshold,
            directions=len(intervention.directions),
            seed_node_ids=list(seed_ids),
            reviewer_seconds=intervention.reviewer_seconds,
        )
        return intervention

    @staticmethod
    def _expandable(tree: HypothesisTree, node_id: str) -> bool:
        """A reseed branch point must exist and not be a pruned dead end."""
        node = tree.nodes.get(node_id)
        return node is not None and node.status is not NodeStatus.ABANDONED

    # -- measurement ----------------------------------------------------------

    def observe_post_intervention_cycle(self, tree: HypothesisTree, improved: bool) -> None:
        """Measure subsequent gain for the most recent intervention: every
        cycle after it re-records the intervention's ``subsequent_gain`` as
        the best-score delta so far, so cost *and* subsequent gain are always
        measured, never inferred after the fact."""
        if not self.interventions:
            return
        latest = self.interventions[-1]
        best = tree.best_node()
        latest.subsequent_gain = (
            (best.score or 0.0) if best is not None else 0.0
        ) - latest.best_score_at_trigger
