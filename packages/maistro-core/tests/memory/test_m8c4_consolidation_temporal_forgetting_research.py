"""M8-C4 research harness — episodic-to-semantic consolidation, temporal contradiction handling, forgetting.

Issue #923 (leaf of epic #901, initiative #879). Hypothesis under study:
long-lived Workspace memory improves when raw episodic observations are
periodically consolidated into higher-level facts, stale claims decay, and
contradictory temporal facts are reconciled explicitly.

This module is a RESEARCH ARTIFACT, not product code. It implements the
measurement machinery the #923 experiment demands — a deterministic synthetic
Workspace history with ground truth by construction (repeated, superseded,
contradictory, and obsolete facts); raw episodic retrieval versus
consolidation / decay / temporal-version strategies; current-fact accuracy,
stale-fact intrusion, information loss, contradiction-resolution quality,
storage growth, consolidation cost, and auditability back to source episodes —
so the real experiment is reproducible the moment real Workspace histories
exist.

What the fixtures are and are not:

- The hand-checked fixture pins every weight, decay rate, similarity, and
  rank so each headline number is verifiable by hand arithmetic in the test
  comments. It validates the *machinery*.
- The seeded corpus generates histories by construction (version chains,
  duplicate groups, contradiction pairs, obsolete one-offs, audit-only
  episodes), so its assertions are the guarantees construction provides
  (tie ordering, degeneration equalities, direction of deltas), never hoped-
  for quality numbers.
- NEITHER is experimental evidence about real embeddings, real extraction,
  or real Workspace histories. Numbers from this harness must never be quoted
  as such. The real-experiment procedure lives in
  ``docs/research/923-episodic-consolidation-temporal-forgetting.md``.

Canonical shapes replicated for measurement (the owners stay in maistro-core):

- Raw episodic retrieval is ``memory/episodic/ranking.py`` verbatim (SPEC-243 /
  ADR-080 part D): ``(keyword_overlap + vector) * weight`` with the shipped
  default vector term (``no_vector`` — an explicit zero), stable descending
  sort, and the ``min_score`` drop. Stable sorting makes insertion (day) order
  the tiebreak, which is exactly what lets a *stale* fact lead a tie.
- Decay is ``tiers.tick_decay`` semantics: ``weight -= decay_rate * elapsed_
  hours``, clamped to the ADR-091 tier band — the OBSERVATION floor is 0.1, so
  decay sinks a fact to its floor and never out of the store. Repeated facts
  are modeled with slowed per-record decay rates (the ``SLOW_DECAY`` feedback
  multiplier is the shipped mechanism that produces them).
- Consolidation is ``memory/episodic/consolidation.py`` semantics (ADR-080
  part B / SPEC-241): all-pairs scan; near-duplicates merge (primary survives,
  absorbed become ``deleted=True`` — retained, never purged; merged weight is
  the weighted mean of squares ``sum(w*w)/sum(w)``); contradictions lower BOTH
  sides by ``CONTRADICT_DELTA`` and flag both for review, once per unresolved
  pair (the lifecycle's dedup — ``_unresolved_record`` — is what stops a
  nightly batch from re-flagging and re-decrementing the same pair forever).
  The similarity and contradiction predicates are injectable in production;
  here they stand in as token Jaccard (threshold 0.85) and
  same-subject/different-value.
- Temporal versions replicate the *learnings* lifecycle's supersession
  (``memory/learnings/lifecycle.py``): a newer row supersedes an older one;
  the predecessor is retained as historical record. The episodic side ships NO
  supersession — that gap is precisely what the temporal arm measures.
- Contradiction surfacing replicates the lifecycle's
  ``record_contradiction``/``find_relevant`` shape: registering a conflict
  REQUIRES an evidence link, and retrieval attaches every unresolved conflict
  touching a returned row so an answer never sees one side of a known
  contradiction without the other.

Trust boundary (the epic contract, enforced by construction):

- Every number produced here is ADVISORY EVIDENCE. Nothing reads or writes a
  Goal, a Run authority, a durable memory store, or any authorization path.
  The module imports no maistro module at all, so it cannot become a second
  canonical memory authority by accident — the exact prohibition the epic
  states. The issue's own constraint ("consolidation may not erase provenance
  or mutate canonical history invisibly") is measured, not assumed: every
  strategy runs through an append-only ledger whose replay must reconstruct
  the full episode set, and chain integrity is scored over the final state.
  Deliberate WRONGNESS variants (purging consolidation, floorless decay,
  silent supersession) are part of the measurement grid — they demonstrate
  the failures the shipped retention mechanisms prevent, so the pins cannot
  pass for the wrong reason.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-C4 output as
#: authorization. Durable memory authority remains PostgreSQL + pgvector
#: (ADR-011/ADR-034); consolidation and decay dynamics remain ADR-080 /
#: SPEC-241 / SPEC-080126-9e42 owners.
ADVISORY_ONLY = True

# ---------------------------------------------------------------------------
# Canonical-shape replicas (measurement-only; the owners stay in maistro-core)
# ---------------------------------------------------------------------------

#: memory/episodic/consolidation.py
SIMILARITY_MERGE_THRESHOLD = 0.85
CONTRADICT_DELTA = 0.05

#: maistro/types/memory.py — ADR-091 OBSERVATION tier band (the fixture tier).
OBSERVATION_FLOOR = 0.1
OBSERVATION_CEILING = 0.5

#: maistro/types/memory.py — decay curve constants (ADR-080 part A).
DEFAULT_DECAY_RATE = 0.01  # weight lost per hour at decay_rate=1.0

_HOURS_PER_DAY = 24.0


def keyword_overlap(query: str, content: str) -> float:
    """Replica of episodic/ranking.py ``keyword_overlap``: raw split, no stopwords."""
    query_words = {w for w in query.lower().split() if w}
    if not query_words:
        return 0.0
    content_words = {w for w in content.lower().split() if w}
    if not content_words:
        return 0.0
    return len(query_words & content_words) / len(query_words)


def no_vector(query: str, content: str) -> float:
    """Replica of episodic/ranking.py ``no_vector``: the shipped zero term."""
    return 0.0


def token_jaccard(a: str, b: str) -> float:
    """The harness's similarity predicate stand-in (production injects its own)."""
    aw = set(a.lower().split())
    bw = set(b.lower().split())
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / len(aw | bw)


# ---------------------------------------------------------------------------
# Corpus records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Episode:
    """One episodic record in the synthetic Workspace history.

    ``day`` is the temporal position. ``subject`` names the fact's entity key
    (ground truth, used only by the contradiction predicate and corpus
    labeling — never by retrieval). ``value`` is the fact's distinguishing
    token (versions differ here). ``supersedes`` names the predecessor this
    row replaces — the history's DECLARED temporal version; declared pairs are
    exempt from the contradiction predicate, because a supersession IS the
    resolution of an outdated claim, not an open conflict. ``decay_rate`` is
    the per-record hourly rate; slowed rates model the shipped SLOW_DECAY
    effect of reinforcement on repeated facts.
    """

    memory_id: str
    content: str
    day: int
    subject: str = ""
    value: str = ""
    supersedes: str = ""
    weight: float = 0.3
    decay_rate: float = DEFAULT_DECAY_RATE

    def __post_init__(self) -> None:
        if not self.memory_id:
            raise ValueError("memory_id must be non-empty")
        if self.day < 0:
            raise ValueError(f"{self.memory_id}: negative day")
        if not OBSERVATION_FLOOR <= self.weight <= OBSERVATION_CEILING:
            raise ValueError(
                f"{self.memory_id}: weight {self.weight} outside the ADR-091 OBSERVATION band"
            )
        if self.decay_rate < 0:
            raise ValueError(f"{self.memory_id}: negative decay_rate")


@dataclass(frozen=True)
class Question:
    """One query against the history at an as-of day.

    ``kind`` is declared, not derived: "current" questions score
    current-fact accuracy (the answer should be the fact's latest state);
    "audit" questions score auditability (every episode ever relevant must
    remain reachable). ``current_relevant`` names the episodes that answer the
    query at ``as_of``; ``audit_relevant`` names every episode ever relevant,
    superseded predecessors and absorbed duplicates included.
    ``contradiction_pair`` declares — as ground truth — a known conflict
    between two episodes; questions carrying one score contradiction
    resolution quality (was the conflict surfaced, or answered silently?).
    """

    query_id: str
    text: str
    as_of: int
    current_relevant: frozenset[str]
    audit_relevant: frozenset[str]
    kind: str = "current"  # "current" | "audit"
    contradiction_pair: tuple[str, str] = ()

    def __post_init__(self) -> None:
        if not self.query_id:
            raise ValueError("query_id must be non-empty")
        if self.kind not in ("current", "audit"):
            raise ValueError(f"{self.query_id}: kind must be 'current' or 'audit'")
        if not self.current_relevant <= self.audit_relevant:
            raise ValueError(
                f"{self.query_id}: current relevance must be a subset of audit relevance"
            )
        if self.contradiction_pair:
            if (
                len(self.contradiction_pair) != 2
                or self.contradiction_pair[0] == self.contradiction_pair[1]
            ):
                raise ValueError(
                    f"{self.query_id}: contradiction_pair must name two distinct episodes"
                )
            if not set(self.contradiction_pair) <= self.audit_relevant:
                raise ValueError(f"{self.query_id}: contradiction_pair must be audit-relevant")


@dataclass(frozen=True)
class History:
    """A synthetic Workspace history with ground truth by construction."""

    episodes: tuple[Episode, ...]
    questions: tuple[Question, ...]

    def __post_init__(self) -> None:
        if not self.episodes:
            raise ValueError("history must hold at least one episode")
        ids = [e.memory_id for e in self.episodes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate episode memory_ids")
        qids = [q.query_id for q in self.questions]
        if len(qids) != len(set(qids)):
            raise ValueError("duplicate question query_ids")
        known = set(ids)
        for e in self.episodes:
            if e.supersedes and e.supersedes not in known:
                raise ValueError(f"{e.memory_id}: supersedes unknown {e.supersedes}")
        for q in self.questions:
            unknown = (q.current_relevant | q.audit_relevant) - known
            if unknown:
                raise ValueError(
                    f"{q.query_id}: relevance names unknown episodes {sorted(unknown)}"
                )


# ---------------------------------------------------------------------------
# Store, ledger, and canonical mutations
# ---------------------------------------------------------------------------


@dataclass
class StoredRow:
    """A live-or-tombstoned episodic row inside the harness store.

    Mirrors ``EpisodicMemory``'s fields that the strategies act on. ``deleted``
    is the consolidation tombstone (retained, never purged — unless a WRONGNESS
    variant purges it, which is recorded as an erasure). ``superseded_by``
    names the successor when the temporal arm registered the row's version
    chain; empty means current.
    """

    episode: Episode
    weight: float
    deleted: bool = False
    flagged_for_review: bool = False
    superseded_by: str = ""
    absorbed_sources: tuple[str, ...] = ()

    @property
    def memory_id(self) -> str:
        return self.episode.memory_id

    @property
    def is_current(self) -> bool:
        return not self.deleted and not self.superseded_by


@dataclass(frozen=True)
class LedgerEvent:
    """One append-only history event: the auditability substrate.

    ``kind`` names the move; ``actor`` names what drove it (a strategy arm at a
    day, or the history itself); ``sources`` and ``outputs`` name the rows it
    read and wrote. Replay applies events in order and must reconstruct the
    FULL episode set — an erasure the ledger cannot account for breaks
    auditability, which is the issue's own constraint.
    """

    kind: str  # "store" | "merge" | "contradiction" | "supersede" | "decay" | "purge"
    actor: str
    day: int
    sources: tuple[str, ...]
    outputs: tuple[str, ...]
    detail: str = ""


@dataclass
class Store:
    """The harness's in-memory episodic store plus its append-only ledger.

    Rows enter at their episode's day (``insert``); ``simulate`` stages them
    through the history so decay and consolidation only ever see what the
    Workspace had seen at that point.
    """

    rows: dict[str, StoredRow] = field(default_factory=dict)
    ledger: list[LedgerEvent] = field(default_factory=list)
    #: Rows removed from the store entirely. Only WRONGNESS variants write it;
    #: every name here is an erasure the audit trail cannot explain.
    purged: dict[str, str] = field(default_factory=dict)
    #: conflict_id -> (side_a, side_b) unresolved contradictions, lifecycle shape.
    conflicts: dict[str, tuple[str, str]] = field(default_factory=dict)

    def insert(self, episode: Episode) -> StoredRow:
        row = StoredRow(episode=episode, weight=episode.weight)
        self.rows[episode.memory_id] = row
        self.ledger.append(
            LedgerEvent(
                kind="store",
                actor="history",
                day=episode.day,
                sources=(),
                outputs=(episode.memory_id,),
                detail=f"weight={episode.weight}",
            )
        )
        return row

    def live_rows(self) -> list[StoredRow]:
        """Rows visible to ordinary retrieval: tombstoned rows stay out."""
        return [r for r in self.rows.values() if not r.deleted]

    def retained_rows(self) -> list[StoredRow]:
        """Every row still in the store, tombstones included (the audit path)."""
        return list(self.rows.values())


def make_store(episodes: tuple[Episode, ...]) -> Store:
    """A store pre-populated with every episode (for direct-use probes)."""
    store = Store()
    for e in episodes:
        store.insert(e)
    return store


def tick_decay(row: StoredRow, elapsed_hours: float) -> StoredRow:
    """Replica of tiers.tick_decay: linear loss, clamped to the tier floor."""
    lost = row.episode.decay_rate * elapsed_hours
    return replace(row, weight=max(OBSERVATION_FLOOR, row.weight - lost))


def apply_decay_sweep(store: Store, day: int, actor: str) -> int:
    """One hourly-cadence sweep across all live rows (driver.run_once shape)."""
    changed = 0
    for rid, row in store.rows.items():
        if row.deleted:
            continue
        decayed = tick_decay(row, _HOURS_PER_DAY)
        if decayed.weight != row.weight:
            store.rows[rid] = decayed
            changed += 1
    store.ledger.append(
        LedgerEvent(
            kind="decay",
            actor=actor,
            day=day,
            sources=(),
            outputs=(),
            detail=f"decayed={changed}",
        )
    )
    return changed


def merge_weight(w_a: float, w_b: float) -> float:
    """consolidation._weighted_merge_weight for one pair: sum(w*w)/sum(w)."""
    total = w_a + w_b
    if total == 0:
        return 0.0
    return (w_a * w_a + w_b * w_b) / total


def consolidate_pair(
    store: Store, primary_id: str, absorbed_id: str, *, day: int, actor: str
) -> None:
    """consolidation.apply_merge semantics: primary survives, absorbed tombstoned."""
    primary = store.rows[primary_id]
    absorbed = store.rows[absorbed_id]
    merged = merge_weight(primary.weight, absorbed.weight)
    store.rows[primary_id] = replace(
        primary,
        weight=merged,
        absorbed_sources=(*primary.absorbed_sources, absorbed_id),
    )
    store.rows[absorbed_id] = replace(absorbed, deleted=True)
    store.ledger.append(
        LedgerEvent(
            kind="merge",
            actor=actor,
            day=day,
            sources=(primary_id, absorbed_id),
            outputs=(primary_id, absorbed_id),
            detail=f"merged_weight={merged}",
        )
    )


def flag_contradiction(
    store: Store, a_id: str, b_id: str, *, day: int, actor: str, evidence: str
) -> str:
    """Lifecycle record_contradiction shape: both sides lose confidence, both flagged.

    The evidence link is REQUIRED — a contradiction nobody can attribute to the
    Run or evaluation that found it must not register (lifecycle's
    EvidenceLinkRequiredError, replicated).
    """
    if not evidence:
        raise ValueError("a contradiction record must name the Run or evaluation that detected it")
    a = store.rows[a_id]
    b = store.rows[b_id]
    store.rows[a_id] = replace(
        a,
        weight=max(OBSERVATION_FLOOR, a.weight - CONTRADICT_DELTA),
        flagged_for_review=True,
    )
    store.rows[b_id] = replace(
        b,
        weight=max(OBSERVATION_FLOOR, b.weight - CONTRADICT_DELTA),
        flagged_for_review=True,
    )
    conflict_id = f"c{len(store.conflicts) + 1}"
    store.conflicts[conflict_id] = (a_id, b_id)
    store.ledger.append(
        LedgerEvent(
            kind="contradiction",
            actor=actor,
            day=day,
            sources=(a_id, b_id),
            outputs=(a_id, b_id),
            detail=f"evidence={evidence}",
        )
    )
    return conflict_id


def register_supersession(
    store: Store, predecessor_id: str, successor_id: str, *, day: int, actor: str
) -> None:
    """Lifecycle supersede shape on episodic rows: predecessor retained, marked."""
    store.rows[predecessor_id] = replace(store.rows[predecessor_id], superseded_by=successor_id)
    store.ledger.append(
        LedgerEvent(
            kind="supersede",
            actor=actor,
            day=day,
            sources=(predecessor_id, successor_id),
            outputs=(predecessor_id,),
            detail="temporal version",
        )
    )


# ---------------------------------------------------------------------------
# Strategy arms
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Strategy:
    """One arm of the #923 experiment.

    ``consolidate`` runs an all-pairs consolidation batch at the end of every
    day; ``flag_contradictions`` registers the conflicts that batch finds (once
    per unresolved pair). ``decay`` runs the hourly sweep at each day end.
    ``temporal`` registers the history's declared supersession chains as each
    successor arrives. The three WRONGNESS flags each sabotage exactly one
    retention mechanism: ``purge_absorbed`` erases merged-away rows instead of
    tombstoning them, ``floorless`` removes decay's tier floor, and
    ``silent_supersession`` erases predecessors instead of retaining them.
    """

    name: str
    consolidate: bool = False
    flag_contradictions: bool = False
    decay: bool = False
    temporal: bool = False
    purge_absorbed: bool = False
    floorless: bool = False
    silent_supersession: bool = False

    def __post_init__(self) -> None:
        if self.purge_absorbed and not self.consolidate:
            raise ValueError(f"{self.name}: purge_absorbed requires consolidate")
        if self.floorless and not self.decay:
            raise ValueError(f"{self.name}: floorless requires decay")
        if self.silent_supersession and not self.temporal:
            raise ValueError(f"{self.name}: silent_supersession requires temporal")

    def describe(self) -> str:
        parts = [self.name]
        if self.consolidate:
            parts.append("consolidate" + ("+purge" if self.purge_absorbed else ""))
        if self.decay:
            parts.append("decay" + ("+no-floor" if self.floorless else ""))
        if self.temporal:
            parts.append("temporal" + ("+silent" if self.silent_supersession else ""))
        if self.flag_contradictions:
            parts.append("flag")
        return "|".join(parts)


def _contradicts(a: Episode, b: Episode) -> bool:
    """Same subject, incompatible values, and NO declared supersession between
    them — a declared temporal version is the resolution of an outdated claim,
    not an open conflict."""
    declared = b.memory_id == a.supersedes or a.memory_id == b.supersedes
    return (
        bool(a.subject)
        and a.subject == b.subject
        and bool(a.value)
        and bool(b.value)
        and a.value != b.value
        and not declared
    )


def run_consolidation_batch(store: Store, strategy: Strategy, day: int) -> dict[str, int]:
    """consolidation.run_batch shape: all-pairs scan, apply each proposal once."""
    rows = sorted(store.live_rows(), key=lambda r: (r.episode.day, r.memory_id))
    episodes = [r.episode for r in rows]
    comparisons = 0
    merges = 0
    flags = 0
    absorbed_ids: set[str] = set()
    for i, a in enumerate(episodes):
        if a.memory_id in absorbed_ids:
            continue
        for b in episodes[i + 1 :]:
            if b.memory_id in absorbed_ids:
                continue
            comparisons += 1
            if _contradicts(a, b):
                if strategy.flag_contradictions and not _already_registered(
                    store, a.memory_id, b.memory_id
                ):
                    flags += 1
                    flag_contradiction(
                        store,
                        a.memory_id,
                        b.memory_id,
                        day=day,
                        actor=strategy.describe(),
                        evidence=f"{strategy.name}@day{day}",
                    )
                continue
            if _similar(a, b):
                merges += 1
                consolidate_pair(
                    store, a.memory_id, b.memory_id, day=day, actor=strategy.describe()
                )
                absorbed_ids.add(b.memory_id)
                if strategy.purge_absorbed:
                    del store.rows[b.memory_id]
                    store.purged[b.memory_id] = f"purged@day{day}"
                    store.ledger.append(
                        LedgerEvent(
                            kind="purge",
                            actor=strategy.describe(),
                            day=day,
                            sources=(a.memory_id, b.memory_id),
                            outputs=(),
                            detail="WRONGNESS: absorbed row erased, not tombstoned",
                        )
                    )
    return {"comparisons": comparisons, "merges": merges, "flags": flags}


def _similar(a: Episode, b: Episode) -> bool:
    return (
        a.subject == b.subject and token_jaccard(a.content, b.content) >= SIMILARITY_MERGE_THRESHOLD
    )


def _already_registered(store: Store, a_id: str, b_id: str) -> bool:
    """Lifecycle's unresolved-pair dedup: never flag the same pair twice."""
    return any(set(sides) == {a_id, b_id} for sides in store.conflicts.values())


def _register_day_supersessions(
    store: Store, history: History, strategy: Strategy, day: int
) -> None:
    """Temporal arm: register the history's declared chains as successors arrive."""
    for e in history.episodes:
        if not (e.supersedes and e.day == day):
            continue
        if strategy.silent_supersession:
            # WRONGNESS: erase the predecessor instead of retaining it.
            store.purged[e.supersedes] = f"purged@day{day}"
            del store.rows[e.supersedes]
            store.ledger.append(
                LedgerEvent(
                    kind="purge",
                    actor=strategy.describe(),
                    day=day,
                    sources=(e.supersedes,),
                    outputs=(),
                    detail=f"WRONGNESS: predecessor erased for {e.memory_id}",
                )
            )
        else:
            register_supersession(
                store, e.supersedes, e.memory_id, day=day, actor=strategy.describe()
            )


def simulate(history: History, strategy: Strategy) -> RunResult:
    """Replay the history day by day under one strategy arm."""
    store = Store()
    total = {"comparisons": 0, "merges": 0, "flags": 0}
    last_day = max((e.day for e in history.episodes), default=0)
    for day in range(0, last_day + 1):
        for e in history.episodes:
            if e.day == day:
                store.insert(e)
        if strategy.temporal:
            _register_day_supersessions(store, history, strategy, day)
        if strategy.consolidate:
            counts = run_consolidation_batch(store, strategy, day)
            for key in total:
                total[key] += counts[key]
        if strategy.decay:
            if strategy.floorless:
                _apply_floorless_decay(store, day, strategy.describe())
            else:
                apply_decay_sweep(store, day, strategy.describe())
    result = evaluate(history, store, strategy)
    return RunResult(
        strategy=strategy,
        store=store,
        comparisons=total["comparisons"],
        merges=total["merges"],
        flags=total["flags"],
        **result,
    )


def _apply_floorless_decay(store: Store, day: int, actor: str) -> None:
    """WRONGNESS decay: no tier floor — weight is unbounded below (reaches 0)."""
    for rid, row in store.rows.items():
        if row.deleted:
            continue
        lost = row.episode.decay_rate * _HOURS_PER_DAY
        store.rows[rid] = replace(row, weight=row.weight - lost)
    store.ledger.append(
        LedgerEvent(kind="decay", actor=actor, day=day, sources=(), outputs=(), detail="floorless")
    )


# ---------------------------------------------------------------------------
# Retrieval and metrics
# ---------------------------------------------------------------------------


def score(query: str, content: str, weight: float) -> float:
    """SPEC-243 shape with the shipped default vector term: (kw + 0) * weight."""
    return (keyword_overlap(query, content) + no_vector(query, content)) * max(weight, 0.0)


def retrieve(store: Store, query: str, k: int, *, audit_mode: bool = False) -> list[StoredRow]:
    """episodic/ranking.py ``rank`` shape over the harness store.

    Ordinary mode retrieves live, current rows (tombstones and marked
    predecessors stay out — a policy choice the temporal arm exists to price).
    ``audit_mode=True`` is the audit path: every RETAINED row qualifies,
    tombstones and superseded predecessors included; purged rows are gone for
    every mode, which is exactly the information-loss surface. Stable
    descending sort keeps insertion order as the tiebreak, as production does.
    """
    if audit_mode:
        candidates = list(store.rows.values())
    else:
        candidates = [r for r in store.rows.values() if r.is_current]
    scored = [(score(query, r.episode.content, r.weight), r) for r in candidates]
    kept = [(s, r) for s, r in scored if s > 0.0]
    kept.sort(key=lambda pair: pair[0], reverse=True)
    return [r for _s, r in kept[:k]]


def _conflicts_touching(store: Store, retrieved_ids: set[str]) -> list[tuple[str, str]]:
    """Lifecycle find_relevant's conflict attachment: unresolved conflicts that
    touch at least one returned row."""
    return [sides for sides in store.conflicts.values() if set(sides) & retrieved_ids]


@dataclass
class QueryOutcome:
    query_id: str
    kind: str  # "current" | "audit"
    retrieved: tuple[str, ...]
    audit_retrieved: tuple[str, ...]
    top1_is_current: bool
    stale_slots: int
    audit_recall: float
    conflict_declared: bool
    conflict_surfaced: bool


@dataclass
class RunResult:
    strategy: Strategy
    store: Store
    comparisons: int
    merges: int
    flags: int
    outcomes: list[QueryOutcome] = field(default_factory=list)
    current_accuracy: float = 0.0
    stale_intrusion: float = 0.0
    audit_recall: float = 0.0
    information_loss: float = 0.0
    contradiction_quality: float = 0.0
    live_rows: int = 0
    retained_rows: int = 0
    chain_integrity: float = 1.0
    ledger_replay_ok: bool = True


def evaluate(history: History, store: Store, strategy: Strategy) -> dict[str, object]:
    """Score one arm: the issue's full measure list."""
    outcomes: list[QueryOutcome] = []
    for q in sorted(history.questions, key=lambda q: q.query_id):
        retrieved = retrieve(store, q.text, 3)
        audit_retrieved = retrieve(store, q.text, 3, audit_mode=True)
        rids = {r.memory_id for r in retrieved}
        arids = {r.memory_id for r in audit_retrieved}
        top1_is_current = bool(retrieved) and retrieved[0].memory_id in q.current_relevant
        stale_slots = len(rids - q.current_relevant)
        audit_recall = len(arids & q.audit_relevant) / len(q.audit_relevant)
        # Contradiction resolution: a declared pair must be SURFACED — both
        # sides in the context AND the conflict attached (the lifecycle
        # contract). Both sides answered with no attachment is an unresolved
        # contradiction smuggled into the prompt; one side alone is worse.
        declared = bool(q.contradiction_pair)
        surfaced = (
            declared
            and set(q.contradiction_pair) <= rids
            and set(q.contradiction_pair)
            in [set(sides) for sides in _conflicts_touching(store, rids)]
        )
        outcomes.append(
            QueryOutcome(
                query_id=q.query_id,
                kind=q.kind,
                retrieved=tuple(r.memory_id for r in retrieved),
                audit_retrieved=tuple(r.memory_id for r in audit_retrieved),
                top1_is_current=top1_is_current,
                stale_slots=stale_slots,
                audit_recall=audit_recall,
                conflict_declared=declared,
                conflict_surfaced=surfaced,
            )
        )

    current_qs = [o for o in outcomes if o.kind == "current"]
    current_accuracy = (
        sum(1 for o in current_qs if o.top1_is_current) / len(current_qs) if current_qs else 0.0
    )
    stale_slots_total = sum(o.stale_slots for o in current_qs)
    slot_total = sum(len(o.retrieved) for o in current_qs)
    stale_intrusion = stale_slots_total / slot_total if slot_total else 0.0
    audit_recall_mean = sum(o.audit_recall for o in outcomes) / len(outcomes) if outcomes else 0.0
    # Information loss: audit-relevant episodes reachable in NO mode. Retention
    # (tombstones, floors) keeps this at 0.0; purges and floorless decay move it.
    audit_episodes: set[str] = set()
    for q in history.questions:
        audit_episodes |= q.audit_relevant
    lost = sum(1 for e in audit_episodes if e not in store.rows or store.rows[e].weight <= 0.0)
    information_loss = lost / len(audit_episodes) if audit_episodes else 0.0
    declared_qs = [o for o in outcomes if o.conflict_declared]
    contradiction_quality = (
        sum(1 for o in declared_qs if o.conflict_surfaced) / len(declared_qs)
        if declared_qs
        else 0.0
    )

    live = store.live_rows()
    retained = store.retained_rows()
    # Auditability back to source episodes: every history episode must still
    # be present (tombstones count; purges do not), and every retained row's
    # absorbed sources must resolve. The ledger replay must reconstruct the
    # FULL episode set for the audit trail to explain the final state.
    absent = sum(1 for e in history.episodes if e.memory_id not in store.rows)
    broken = 0
    for row in retained:
        for src in row.absorbed_sources:
            if src not in store.rows:
                broken += 1
    chain_integrity = 1.0 - ((absent + broken) / len(history.episodes)) if history.episodes else 1.0
    replay_ok = replay_ledger(history, store.ledger)

    return {
        "outcomes": outcomes,
        "current_accuracy": current_accuracy,
        "stale_intrusion": stale_intrusion,
        "audit_recall": audit_recall_mean,
        "information_loss": information_loss,
        "contradiction_quality": contradiction_quality,
        "live_rows": len(live),
        "retained_rows": len(retained),
        "chain_integrity": chain_integrity,
        "ledger_replay_ok": replay_ok,
    }


def replay_ledger(history: History, ledger: list[LedgerEvent]) -> bool:
    """Replay the append-only ledger: it must reconstruct the FULL episode set.

    Every recorded output must resolve to a retained row, and no episode may
    end up unaccounted for — an erasure the ledger cannot explain is a broken
    audit trail (the issue's "may not erase provenance or mutate canonical
    history invisibly", measured).
    """
    state = {e.memory_id: True for e in history.episodes}
    for event in ledger:
        if event.kind == "purge":
            for src in event.sources:
                state[src] = False
        for out in event.outputs:
            if out and not state.get(out, False):
                return False
    return all(state.values())


def build_report(history: History, strategies: list[Strategy]) -> dict[str, object]:
    """The frozen, JSON-shaped experiment report."""
    results = [simulate(history, s) for s in strategies]
    return {
        "advisory_only": ADVISORY_ONLY,
        "history_episodes": len(history.episodes),
        "questions": len(history.questions),
        "arms": [
            {
                "strategy": r.strategy.name,
                "current_accuracy": round(r.current_accuracy, 4),
                "stale_intrusion": round(r.stale_intrusion, 4),
                "audit_recall": round(r.audit_recall, 4),
                "information_loss": round(r.information_loss, 4),
                "contradiction_quality": round(r.contradiction_quality, 4),
                "live_rows": r.live_rows,
                "retained_rows": r.retained_rows,
                "comparisons": r.comparisons,
                "merges": r.merges,
                "flags": r.flags,
                "chain_integrity": round(r.chain_integrity, 4),
                "ledger_replay_ok": r.ledger_replay_ok,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Hand-checked fixture — every number verifiable by hand
# ---------------------------------------------------------------------------


def hand_history() -> History:
    """A single-Workspace history with exact weights, rates, and ranks.

    Facts (all OBSERVATION band, floor 0.1 / ceiling 0.5):
      d1 deploy_v14  "deploy api uses postgres 14"  w=0.30 rate=0.010
      d2 exports_a   "report exports run nightly"   w=0.30 rate=0.002
      d3 offsite     "offsite held at the lodge"    w=0.30 rate=0.010 (obsolete)
      d3 exports_b   "report exports run nightly"   w=0.40 rate=0.002 (duplicate)
      d4 runbook     "migration runbook approved by dana" w=0.50 rate=0.002
      d5 deploy_v16  "deploy api uses postgres 16"  w=0.30 rate=0.010 supersedes deploy_v14
      d6 cache_300   "cache ttl is 300 seconds"     w=0.50 rate=0.002
      d6 cache_600   "cache ttl is 600 seconds"     w=0.30 rate=0.002 (contradicts)

    Token sets are pairwise disjoint across subjects, so every keyword overlap
    is exactly 1.0 (all query words present) or 0.0 (no shared tokens).
    """
    episodes = (
        Episode(
            "deploy_v14",
            "deploy api uses postgres 14",
            1,
            subject="deploy",
            value="14",
            weight=0.30,
        ),
        Episode(
            "exports_a",
            "report exports run nightly",
            2,
            subject="exports",
            value="nightly",
            weight=0.30,
            decay_rate=0.002,
        ),
        Episode(
            "offsite", "offsite held at the lodge", 3, subject="offsite", value="lodge", weight=0.30
        ),
        Episode(
            "exports_b",
            "report exports run nightly",
            3,
            subject="exports",
            value="nightly",
            weight=0.40,
            decay_rate=0.002,
        ),
        Episode(
            "runbook",
            "migration runbook approved by dana",
            4,
            subject="runbook",
            value="dana",
            weight=0.50,
            decay_rate=0.002,
        ),
        Episode(
            "deploy_v16",
            "deploy api uses postgres 16",
            5,
            subject="deploy",
            value="16",
            supersedes="deploy_v14",
            weight=0.30,
        ),
        Episode(
            "cache_300",
            "cache ttl is 300 seconds",
            6,
            subject="cache",
            value="300",
            weight=0.50,
            decay_rate=0.002,
        ),
        Episode(
            "cache_600",
            "cache ttl is 600 seconds",
            6,
            subject="cache",
            value="600",
            weight=0.30,
            decay_rate=0.002,
        ),
    )
    questions = (
        Question(
            "q_cache",
            "cache ttl",
            6,
            current_relevant=frozenset({"cache_300", "cache_600"}),
            audit_relevant=frozenset({"cache_300", "cache_600"}),
            contradiction_pair=("cache_300", "cache_600"),
        ),
        Question(
            "q_deploy",
            "deploy api uses postgres",
            6,
            current_relevant=frozenset({"deploy_v16"}),
            audit_relevant=frozenset({"deploy_v14", "deploy_v16"}),
        ),
        Question(
            "q_deploy_audit",
            "deploy api uses postgres",
            6,
            current_relevant=frozenset({"deploy_v14", "deploy_v16"}),
            audit_relevant=frozenset({"deploy_v14", "deploy_v16"}),
            kind="audit",
        ),
        Question(
            "q_exports",
            "report exports run",
            6,
            current_relevant=frozenset({"exports_a"}),
            audit_relevant=frozenset({"exports_a", "exports_b"}),
        ),
        Question(
            "q_offsite_audit",
            "offsite held lodge",
            6,
            current_relevant=frozenset({"offsite"}),
            audit_relevant=frozenset({"offsite"}),
            kind="audit",
        ),
        Question(
            "q_runbook",
            "migration runbook approved",
            6,
            current_relevant=frozenset({"runbook"}),
            audit_relevant=frozenset({"runbook"}),
        ),
    )
    return History(episodes=episodes, questions=questions)


#: The five real arms of the experiment (plus wrongness variants for pins).
RAW = Strategy("raw")
CONSOLIDATE = Strategy("consolidate", consolidate=True, flag_contradictions=True)
DECAYED = Strategy("decayed", decay=True)
TEMPORAL = Strategy("temporal", temporal=True)
COMBINED = Strategy(
    "combined", consolidate=True, decay=True, temporal=True, flag_contradictions=True
)
#: WRONGNESS grid — each removes exactly the mechanism a pin credits.
CONSOLIDATE_PURGE = Strategy(
    "consolidate-purge", consolidate=True, purge_absorbed=True, flag_contradictions=True
)
DECAY_NO_FLOOR = Strategy("decay-no-floor", decay=True, floorless=True)
TEMPORAL_SILENT = Strategy("temporal-silent", temporal=True, silent_supersession=True)

ALL_ARMS = [RAW, CONSOLIDATE, DECAYED, TEMPORAL, COMBINED]
WRONG_ARMS = [CONSOLIDATE_PURGE, DECAY_NO_FLOOR, TEMPORAL_SILENT]


# ---------------------------------------------------------------------------
# Seeded corpus — construction-guaranteed facts at scale
# ---------------------------------------------------------------------------


def seeded_history(entities: int = 24) -> History:
    """A long synthetic Workspace history with ground truth by construction.

    Entity i belongs to exactly one fact family by pure modulo — no
    stochasticity anywhere, so the corpus is byte-identical across runs:

    - ``i % 4 == 0`` VERSIONED: a stale opener ``svcN_pipeline svcN_state
      legacyN`` (day N) superseded by ``svcN_pipeline svcN_state vN`` (day
      N+3). Current query text is ``svcN_pipeline svcN_state``: both versions
      overlap it at 1.0 with equal weight 0.3, so raw's stable tiebreak leads
      with the OLDER version — stale intrusion is exact, not probabilistic.
      EVERY content token is subject-prefixed, so cross-entity overlap is
      exactly 0.0 and only the queried entity's rows can rank.
    - ``i % 4 == 1`` DUPLICATED: the same episode twice (days N, N+1; weights
      0.3, 0.4) — ``svcN_workers svcN_scale rN``. The heavier duplicate
      displaces the canonical first row in raw ranking; the consolidation
      batch merges the pair (Jaccard 1.0).
    - ``i % 4 == 2`` CONTRADICTORY: same subject, incompatible values, both
      weight 0.4 (day N) — ``svcN_pipeline svcN_uses vN`` vs ``svcN_pipeline
      svcN_uses altN``. No declared supersession — an open conflict the
      flagging arm registers once.
    - ``i % 4 == 3`` OBSOLETE: a fact plus a one-off note nothing ever queries
      — decay's target.

    Queries: current-fact questions for the first three families (top-1 must
    be the current fact), audit questions for versioned and duplicated
    families (both versions / both copies must stay reachable), and a
    contradiction-pair question for the contradictory family.
    """
    if entities < 8:
        raise ValueError("seeded corpus needs at least 8 entities for all four families")
    episodes: list[Episode] = []
    questions: list[Question] = []
    for i in range(entities):
        day = i + 1
        subj = f"svc{i}"
        base_value = f"v{i}"
        stale_word = f"legacy{i}"
        rate = 0.002 if i % 2 == 0 else 0.01
        family = i % 4
        if family == 0:
            episodes.append(
                Episode(
                    f"{subj}_v1",
                    f"{subj}_pipeline {subj}_state {stale_word}",
                    day,
                    subject=subj,
                    value=stale_word,
                    weight=0.3,
                    decay_rate=rate,
                )
            )
            episodes.append(
                Episode(
                    f"{subj}_v2",
                    f"{subj}_pipeline {subj}_state {base_value}",
                    day + 3,
                    subject=subj,
                    value=base_value,
                    supersedes=f"{subj}_v1",
                    weight=0.3,
                    decay_rate=rate,
                )
            )
            text = f"{subj}_pipeline {subj}_state"
            questions.append(
                Question(
                    f"q_{subj}_current",
                    text,
                    day + 4,
                    current_relevant=frozenset({f"{subj}_v2"}),
                    audit_relevant=frozenset({f"{subj}_v1", f"{subj}_v2"}),
                )
            )
            questions.append(
                Question(
                    f"q_{subj}_audit",
                    text,
                    day + 4,
                    current_relevant=frozenset({f"{subj}_v1", f"{subj}_v2"}),
                    audit_relevant=frozenset({f"{subj}_v1", f"{subj}_v2"}),
                    kind="audit",
                )
            )
        elif family == 1:
            episodes.append(
                Episode(
                    f"{subj}_a",
                    f"{subj}_workers {subj}_scale {i}",
                    day,
                    subject=subj,
                    value=f"r{i}",
                    weight=0.3,
                    decay_rate=rate,
                )
            )
            episodes.append(
                Episode(
                    f"{subj}_b",
                    f"{subj}_workers {subj}_scale {i}",
                    day + 1,
                    subject=subj,
                    value=f"r{i}",
                    weight=0.4,
                    decay_rate=rate,
                )
            )
            text = f"{subj}_workers {subj}_scale"
            questions.append(
                Question(
                    f"q_{subj}_current",
                    text,
                    day + 2,
                    current_relevant=frozenset({f"{subj}_a"}),
                    audit_relevant=frozenset({f"{subj}_a", f"{subj}_b"}),
                )
            )
            questions.append(
                Question(
                    f"q_{subj}_audit",
                    text,
                    day + 2,
                    current_relevant=frozenset({f"{subj}_a", f"{subj}_b"}),
                    audit_relevant=frozenset({f"{subj}_a", f"{subj}_b"}),
                    kind="audit",
                )
            )
        elif family == 2:
            episodes.append(
                Episode(
                    f"{subj}_c1",
                    f"{subj}_pipeline {subj}_uses {base_value}",
                    day,
                    subject=subj,
                    value=base_value,
                    weight=0.4,
                    decay_rate=rate,
                )
            )
            episodes.append(
                Episode(
                    f"{subj}_c2",
                    f"{subj}_pipeline {subj}_uses alt{i}",
                    day,
                    subject=subj,
                    value=f"alt{i}",
                    weight=0.4,
                    decay_rate=rate,
                )
            )
            questions.append(
                Question(
                    f"q_{subj}_conflict",
                    f"{subj}_pipeline {subj}_uses",
                    day + 1,
                    current_relevant=frozenset({f"{subj}_c1", f"{subj}_c2"}),
                    audit_relevant=frozenset({f"{subj}_c1", f"{subj}_c2"}),
                    contradiction_pair=(f"{subj}_c1", f"{subj}_c2"),
                )
            )
        else:
            episodes.append(
                Episode(
                    f"{subj}_fact",
                    f"{subj}_schedule {subj}_reviews quarterly",
                    day,
                    subject=subj,
                    value=f"q{i}",
                    weight=0.3,
                    decay_rate=rate,
                )
            )
            episodes.append(
                Episode(
                    f"{subj}_note",
                    f"{subj}_offsite notes lodge{i}",
                    day + 1,
                    subject=f"{subj}_offsite",
                    value=f"lodge{i}",
                    weight=0.3,
                    decay_rate=0.01,
                )
            )
    return History(episodes=tuple(episodes), questions=tuple(questions))


# ---------------------------------------------------------------------------
# Contract: evidence only
# ---------------------------------------------------------------------------


def module_source() -> str:
    return Path(__file__).with_suffix(".py").read_text(encoding="utf-8")


class TestEvidenceOnlyContract:
    def test_advisory_marker_is_true(self) -> None:
        assert ADVISORY_ONLY is True

    def test_module_imports_no_maistro_module(self) -> None:
        tree = ast.parse(module_source())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("maistro"), alias.name
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or not node.module.startswith("maistro"), node.module

    def test_empty_history_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one episode"):
            History(episodes=(), questions=())

    def test_duplicate_episode_ids_rejected(self) -> None:
        e = Episode("x", "content words", 1)
        with pytest.raises(ValueError, match="duplicate episode"):
            History(episodes=(e, replace(e)), questions=())

    def test_duplicate_query_ids_rejected(self) -> None:
        e = Episode("x", "content words", 1)
        q = Question("q", "content", 2, frozenset({"x"}), frozenset({"x"}))
        with pytest.raises(ValueError, match="duplicate question"):
            History(episodes=(e,), questions=(q, q))

    def test_unknown_supersession_target_rejected(self) -> None:
        e = Episode("x", "content words", 1, supersedes="ghost")
        with pytest.raises(ValueError, match="supersedes unknown"):
            History(episodes=(e,), questions=())

    def test_relevance_must_name_known_episodes(self) -> None:
        e = Episode("x", "content words", 1)
        q = Question("q", "content", 2, frozenset({"ghost"}), frozenset({"ghost"}))
        with pytest.raises(ValueError, match="unknown episodes"):
            History(episodes=(e,), questions=(q,))

    def test_current_relevance_subset_of_audit_relevance(self) -> None:
        with pytest.raises(ValueError, match="subset"):
            Question("q", "content", 2, frozenset({"x"}), frozenset())

    def test_bad_question_kind_rejected(self) -> None:
        with pytest.raises(ValueError, match="kind"):
            Question("q", "content", 2, frozenset({"x"}), frozenset({"x"}), kind="historical")

    def test_bad_contradiction_pair_rejected(self) -> None:
        with pytest.raises(ValueError, match="two distinct"):
            Question(
                "q", "content", 2, frozenset({"x"}), frozenset({"x"}), contradiction_pair=("x", "x")
            )
        with pytest.raises(ValueError, match="audit-relevant"):
            Question(
                "q",
                "content",
                2,
                frozenset({"x"}),
                frozenset({"x"}),
                contradiction_pair=("x", "ghost"),
            )

    def test_weight_outside_tier_band_rejected(self) -> None:
        with pytest.raises(ValueError, match="OBSERVATION band"):
            Episode("x", "content words", 1, weight=0.05)

    def test_contradiction_requires_evidence_link(self) -> None:
        store = make_store(hand_history().episodes)
        with pytest.raises(ValueError, match="must name the Run or evaluation"):
            flag_contradiction(store, "cache_300", "cache_600", day=6, actor="t", evidence="")

    def test_wrongness_requires_parent_mechanism(self) -> None:
        with pytest.raises(ValueError, match="purge_absorbed requires"):
            Strategy("bad", purge_absorbed=True)
        with pytest.raises(ValueError, match="floorless requires"):
            Strategy("bad", floorless=True)
        with pytest.raises(ValueError, match="silent_supersession requires"):
            Strategy("bad", silent_supersession=True)

    def test_tiny_seeded_corpus_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least 8 entities"):
            seeded_history(entities=4)


class TestHandCheckedArithmetic:
    """Every number below is verifiable by hand against the fixture comment."""

    def test_scores_are_the_production_formula_exact(self) -> None:
        store = make_store(hand_history().episodes)
        # q_deploy tokens {deploy, api, uses, postgres}: both versions contain
        # all four -> overlap 1.0. Raw arm (no decay): score = 1.0 * 0.30 = 0.30.
        q = next(q for q in hand_history().questions if q.query_id == "q_deploy")
        rows = retrieve(store, q.text, 5)
        assert [r.memory_id for r in rows][:2] == ["deploy_v14", "deploy_v16"]
        for r in rows[:2]:
            assert score(q.text, r.episode.content, r.weight) == pytest.approx(0.30)

    def test_raw_leads_with_the_stale_fact(self) -> None:
        # Equal scores sort stably; insertion (day) order puts deploy_v14
        # (day 1) ahead of deploy_v16 (day 5). Top-1 is the superseded fact.
        result = simulate(hand_history(), RAW)
        outcome = next(o for o in result.outcomes if o.query_id == "q_deploy")
        assert outcome.retrieved[0] == "deploy_v14"
        assert outcome.top1_is_current is False
        assert outcome.stale_slots == 1

    def test_temporal_arm_promotes_the_current_version(self) -> None:
        # Temporal marks deploy_v14 superseded_by deploy_v16; current-mode
        # retrieval excludes it, so top-1 is the current fact.
        result = simulate(hand_history(), TEMPORAL)
        outcome = next(o for o in result.outcomes if o.query_id == "q_deploy")
        assert outcome.retrieved[0] == "deploy_v16"
        assert outcome.top1_is_current is True
        assert outcome.stale_slots == 0

    def test_audit_mode_still_reaches_the_superseded_episode(self) -> None:
        # Retention: the marked predecessor stays in the store and the audit
        # path reaches it (canonical-history mutation is prohibited).
        result = simulate(hand_history(), TEMPORAL)
        outcome = next(o for o in result.outcomes if o.query_id == "q_deploy_audit")
        assert "deploy_v14" in outcome.audit_retrieved
        assert "deploy_v14" in result.store.rows
        assert result.store.rows["deploy_v14"].superseded_by == "deploy_v16"

    def test_silent_supersession_loses_the_audit_episode(self) -> None:
        # WRONGNESS: erasing the predecessor instead of retaining it makes the
        # audit query miss and breaks the ledger's reconstruction.
        result = simulate(hand_history(), TEMPORAL_SILENT)
        outcome = next(o for o in result.outcomes if o.query_id == "q_deploy_audit")
        assert "deploy_v14" not in result.store.rows
        assert "deploy_v14" not in outcome.audit_retrieved
        assert result.audit_recall < 1.0
        assert result.information_loss > 0.0

    def test_consolidation_merges_duplicates_and_keeps_the_chain(self) -> None:
        # exports_a (w=0.30) + exports_b (w=0.40) merge on day 3: merged weight
        # is (0.09 + 0.16) / 0.70 = 5/14; exports_b is tombstoned, retained,
        # and named in exports_a's absorbed chain.
        result = simulate(hand_history(), CONSOLIDATE)
        store = result.store
        a = store.rows["exports_a"]
        b = store.rows["exports_b"]
        assert a.weight == pytest.approx(5 / 14)
        assert a.absorbed_sources == ("exports_b",)
        assert b.deleted is True
        assert "exports_b" in store.rows  # retained, never purged
        outcome = next(o for o in result.outcomes if o.query_id == "q_exports")
        assert outcome.retrieved[0] == "exports_a"

    def test_merge_weight_uses_the_weighted_mean_of_squares(self) -> None:
        assert merge_weight(0.30, 0.40) == pytest.approx(5 / 14)
        assert merge_weight(0.0, 0.0) == 0.0
        assert merge_weight(1.0, 0.0) == pytest.approx(1.0)

    def test_consolidation_flags_contradictions_and_lowers_both_sides(self) -> None:
        # The day-6 batch flags (cache_300, cache_600) once: both sides lose
        # CONTRADICT_DELTA (0.50 -> 0.45, 0.30 -> 0.25) and both carry
        # flagged_for_review; neither is resolved silently.
        result = simulate(hand_history(), CONSOLIDATE)
        store = result.store
        assert store.rows["cache_300"].weight == pytest.approx(0.45)
        assert store.rows["cache_600"].weight == pytest.approx(0.25)
        assert store.rows["cache_300"].flagged_for_review is True
        assert store.rows["cache_600"].flagged_for_review is True
        assert len(store.conflicts) == 1
        assert result.flags == 1

    def test_declared_supersessions_are_not_flagged_as_contradictions(self) -> None:
        # deploy_v16.supersedes deploy_v14: a temporal version is the
        # resolution of an outdated claim, so the batch never flags the pair.
        result = simulate(hand_history(), CONSOLIDATE)
        registered = {frozenset(sides) for sides in result.store.conflicts.values()}
        assert registered == {frozenset({"cache_300", "cache_600"})}

    def test_raw_never_surfaced_a_declared_contradiction(self) -> None:
        # q_cache retrieves both sides, but with no conflict registry the
        # contradiction is never surfaced — quality 0.0: nothing resolved.
        result = simulate(hand_history(), RAW)
        outcome = next(o for o in result.outcomes if o.query_id == "q_cache")
        assert set(outcome.retrieved) == {"cache_300", "cache_600"}
        assert outcome.conflict_surfaced is False
        assert result.contradiction_quality == 0.0

    def test_flagging_surfaced_both_sides(self) -> None:
        # The flagging arm attaches the conflict; both sides retrieved and the
        # conflict surfaced -> quality 1.0.
        result = simulate(hand_history(), CONSOLIDATE)
        outcome = next(o for o in result.outcomes if o.query_id == "q_cache")
        assert set(outcome.retrieved) == {"cache_300", "cache_600"}
        assert result.contradiction_quality == 1.0

    def test_decay_sinks_obsolete_facts_to_the_floor_not_out_of_the_store(self) -> None:
        # offsite: rate 0.010, swept days 3-6 -> 4 x 0.24 lost, but the
        # OBSERVATION floor holds it at 0.10 in the store. runbook (rate
        # 0.002): 0.50 - 3 x 24 x 0.002 = 0.356, still fully scoreable.
        result = simulate(hand_history(), DECAYED)
        store = result.store
        assert store.rows["offsite"].weight == pytest.approx(OBSERVATION_FLOOR)
        assert store.rows["runbook"].weight == pytest.approx(0.356)
        assert result.information_loss == 0.0
        outcome = next(o for o in result.outcomes if o.query_id == "q_offsite_audit")
        assert "offsite" in outcome.audit_retrieved

    def test_floorless_decay_loses_audit_facts(self) -> None:
        # WRONGNESS: without the floor, offsite sinks to 0.30 - 0.96 = -0.66
        # and drops out of every retrieval — information loss appears.
        result = simulate(hand_history(), DECAY_NO_FLOOR)
        assert result.store.rows["offsite"].weight < 0.0
        assert result.information_loss > 0.0
        outcome = next(o for o in result.outcomes if o.query_id == "q_offsite_audit")
        assert "offsite" not in outcome.audit_retrieved

    def test_purging_consolidation_breaks_chain_integrity_and_audit(self) -> None:
        # WRONGNESS: the absorbed duplicate is erased; the surviving row's
        # chain names a row the store no longer holds, and the episode itself
        # is gone — both violations count against auditability (1 absent +
        # 1 broken chain over 8 episodes).
        result = simulate(hand_history(), CONSOLIDATE_PURGE)
        store = result.store
        assert "exports_b" not in store.rows
        assert "exports_b" in store.purged
        assert result.chain_integrity == pytest.approx(0.75)
        assert result.audit_recall < 1.0

    def test_retaining_arms_keep_full_chain_integrity(self) -> None:
        for strategy in ALL_ARMS:
            result = simulate(hand_history(), strategy)
            assert result.chain_integrity == 1.0, strategy.describe()
            assert result.ledger_replay_ok is True, strategy.describe()

    def test_ledger_replay_detects_erasure(self) -> None:
        history = hand_history()
        silent = simulate(history, TEMPORAL_SILENT)
        purge = simulate(history, CONSOLIDATE_PURGE)
        assert silent.ledger_replay_ok is False
        assert purge.ledger_replay_ok is False
        for strategy in ALL_ARMS:
            assert simulate(history, strategy).ledger_replay_ok is True

    def test_storage_live_rows_flatten_under_consolidation(self) -> None:
        # 8 episodes: raw keeps 8 live rows; consolidation tombstones the one
        # duplicate -> 7 live, 8 retained.
        raw = simulate(hand_history(), RAW)
        cons = simulate(hand_history(), CONSOLIDATE)
        assert raw.live_rows == 8
        assert raw.retained_rows == 8
        assert cons.live_rows == 7
        assert cons.retained_rows == 8

    def test_purge_shrinks_retained_rows(self) -> None:
        # Retention is what keeps the audit trail complete: the purge variant's
        # retained count is the tell.
        cons = simulate(hand_history(), CONSOLIDATE)
        purge = simulate(hand_history(), CONSOLIDATE_PURGE)
        assert cons.retained_rows == 8
        assert purge.retained_rows == 7

    def test_consolidation_cost_is_the_sum_of_daily_all_pairs_batches(self) -> None:
        # Batches run daily over the then-live rows (day: rows -> comparisons):
        # d2: 2 -> 1; d3: 4 -> 6 candidates but the absorbed-skip short-circuits
        # one (the merge lands mid-batch, so (offsite, exports_b) is never
        # compared) -> 5; d4: 4 -> 6; d5: 5 -> 10; d6: 7 -> 21 (flag lands).
        # Total 43 comparisons, exactly one merge and one flag.
        result = simulate(hand_history(), CONSOLIDATE)
        assert result.comparisons == 43
        assert result.merges == 1
        assert result.flags == 1

    def test_consolidation_cost_grows_quadratically(self) -> None:
        # Doubling the entity count more than triples the comparisons
        # (n(n-1)/2 per batch, summed over the longer history).
        small = simulate(seeded_history(entities=8), CONSOLIDATE)
        large = simulate(seeded_history(entities=16), CONSOLIDATE)
        assert large.comparisons > 3 * small.comparisons


class TestSeededCorpus:
    """Assertions construction guarantees — never hoped-for quality."""

    def test_corpus_shape_and_determinism(self) -> None:
        a = seeded_history()
        b = seeded_history()
        assert a.episodes == b.episodes
        assert a.questions == b.questions
        assert len(a.episodes) == 48  # 24 entities x 2 episodes
        assert len(a.questions) == 30  # 12 versioned + 12 duplicated + 6 conflict

    def test_version_chains_are_well_formed(self) -> None:
        history = seeded_history()
        ids = {e.memory_id for e in history.episodes}
        for e in history.episodes:
            if e.supersedes:
                assert e.supersedes in ids

    def test_current_fact_accuracy_ordering(self) -> None:
        # Temporal versions repair what raw's tie ordering breaks: raw leads
        # with the stale opener on every versioned entity (equal scores,
        # stable insertion order) and with the heavier duplicate on every
        # duplicated entity, so its current-fact accuracy sits at 1/3 (only
        # the contradiction family answers with a current fact at top-1);
        # the temporal arm lifts the versioned family, and the full stack
        # answers every current question correctly.
        raw = simulate(seeded_history(), RAW)
        temporal = simulate(seeded_history(), TEMPORAL)
        consolidate = simulate(seeded_history(), CONSOLIDATE)
        combined = simulate(seeded_history(), COMBINED)
        assert raw.current_accuracy == pytest.approx(1 / 3)
        assert temporal.current_accuracy == pytest.approx(2 / 3)
        assert consolidate.current_accuracy == pytest.approx(2 / 3)
        assert combined.current_accuracy == 1.0

    def test_stale_intrusion_is_repaired_by_temporal_versions(self) -> None:
        history = seeded_history()
        raw = simulate(history, RAW)
        temporal = simulate(history, TEMPORAL)
        assert raw.stale_intrusion > 0.0
        assert temporal.stale_intrusion < raw.stale_intrusion
        # Per versioned query: raw's top slot holds the stale opener; the
        # temporal arm's holds only current rows (svc0 is family 0 — versioned
        # — by construction, and no other entity shares its tokens).
        q0 = next(q for q in history.questions if q.query_id == "q_svc0_current")
        raw_rows = retrieve(raw.store, q0.text, 3)
        temporal_rows = retrieve(temporal.store, q0.text, 3)
        assert [r.memory_id for r in raw_rows][:2] == ["svc0_v1", "svc0_v2"]
        assert [r.memory_id for r in temporal_rows] == ["svc0_v2"]

    def test_decay_lowers_obsolete_scores_without_removing_rows(self) -> None:
        history = seeded_history()
        decayed = simulate(history, DECAYED)
        assert decayed.information_loss == 0.0
        assert decayed.retained_rows == len(history.episodes)
        # Every live row that decayed still sits at or above the tier floor.
        floors = [r for r in decayed.store.rows.values() if not r.deleted]
        assert all(r.weight >= OBSERVATION_FLOOR - 1e-9 for r in floors)

    def test_information_loss_is_zero_when_retained_and_positive_under_purge(self) -> None:
        history = seeded_history()
        for strategy in ALL_ARMS:
            result = simulate(history, strategy)
            assert result.information_loss == 0.0, strategy.describe()
            assert result.audit_recall == 1.0, strategy.describe()
        purge = simulate(history, TEMPORAL_SILENT)
        assert purge.information_loss > 0.0
        assert purge.audit_recall < 1.0
        merge_purge = simulate(history, CONSOLIDATE_PURGE)
        assert merge_purge.information_loss > 0.0
        assert merge_purge.audit_recall < 1.0

    def test_audit_recall_survives_consolidation_and_temporal_in_audit_mode(self) -> None:
        # The exact trade the current/audit mode split exists to price: the
        # current-mode answer hides tombstones and predecessors, but the audit
        # path still reaches every retained episode.
        history = seeded_history()
        cons = simulate(history, CONSOLIDATE)
        temporal = simulate(history, TEMPORAL)
        for result in (cons, temporal):
            assert result.audit_recall == 1.0
            assert result.retained_rows == len(history.episodes)

    def test_consolidation_reduces_live_rows_on_seeded_corpus(self) -> None:
        history = seeded_history()
        raw = simulate(history, RAW)
        cons = simulate(history, CONSOLIDATE)
        dup_groups = sum(1 for e in history.episodes if e.memory_id.endswith("_b"))
        assert raw.live_rows == len(history.episodes)
        assert raw.live_rows - cons.live_rows == dup_groups
        assert cons.retained_rows == len(history.episodes)
        assert cons.merges == dup_groups

    def test_current_mode_hides_what_audit_mode_restores(self) -> None:
        history = seeded_history()
        temporal = simulate(history, TEMPORAL)
        superseded = [r for r in temporal.store.rows.values() if r.superseded_by]
        assert superseded, "fixture must exercise supersession"
        stale_id = superseded[0].memory_id
        audit_q = next(
            q for q in history.questions if stale_id in q.audit_relevant and q.kind == "audit"
        )
        current_ids = {r.memory_id for r in retrieve(temporal.store, audit_q.text, 5)}
        audit_ids = {
            r.memory_id for r in retrieve(temporal.store, audit_q.text, 5, audit_mode=True)
        }
        assert stale_id not in current_ids
        assert stale_id in audit_ids
        assert audit_q.audit_relevant <= audit_ids

    def test_contradiction_quality_ordering(self) -> None:
        history = seeded_history()
        raw = simulate(history, RAW)
        cons = simulate(history, CONSOLIDATE)
        assert raw.contradiction_quality == 0.0
        assert cons.contradiction_quality == 1.0

    def test_auditability_is_complete_for_every_retaining_arm(self) -> None:
        history = seeded_history()
        for strategy in ALL_ARMS:
            result = simulate(history, strategy)
            assert result.chain_integrity == 1.0, strategy.describe()
            assert result.ledger_replay_ok is True, strategy.describe()

    def test_purge_breaks_auditability_on_seeded_corpus(self) -> None:
        history = seeded_history()
        purge = simulate(history, CONSOLIDATE_PURGE)
        assert purge.chain_integrity < 1.0
        assert purge.audit_recall < 1.0
        assert purge.ledger_replay_ok is False

    def test_storage_growth_rate_is_reduced_by_consolidation(self) -> None:
        # Same episodes; the consolidating arm simply holds fewer of them in
        # answering position — the row count is identical, the live footprint
        # is not.
        history = seeded_history()
        raw = simulate(history, RAW)
        cons = simulate(history, CONSOLIDATE)
        assert cons.live_rows < raw.live_rows

    def test_combined_arm_beats_raw_on_current_accuracy_without_losing_audit(self) -> None:
        history = seeded_history()
        raw = simulate(history, RAW)
        combined = simulate(history, COMBINED)
        assert combined.current_accuracy == 1.0 > raw.current_accuracy
        assert combined.stale_intrusion == 0.0 < raw.stale_intrusion
        assert combined.audit_recall == 1.0
        assert combined.information_loss == 0.0

    def test_report_round_trips(self) -> None:
        import json

        report = build_report(seeded_history(entities=8), ALL_ARMS + WRONG_ARMS)
        text = json.dumps(report)
        again = json.loads(text)
        assert again == report
        assert report["advisory_only"] is True
        assert len(report["arms"]) == len(ALL_ARMS) + len(WRONG_ARMS)

    def test_headline_results_are_frozen(self) -> None:
        # Frozen headline numbers for the hand fixture: any machinery change
        # that moves these must say so in the research note.
        report = build_report(hand_history(), ALL_ARMS + WRONG_ARMS)
        by_name = {arm["strategy"]: arm for arm in report["arms"]}
        assert by_name["raw"]["current_accuracy"] == 0.5
        assert by_name["raw"]["contradiction_quality"] == 0.0
        assert by_name["raw"]["retained_rows"] == 8
        assert by_name["raw"]["chain_integrity"] == 1.0
        assert by_name["consolidate"]["live_rows"] == 7
        assert by_name["consolidate"]["comparisons"] == 43
        assert by_name["consolidate"]["merges"] == 1
        assert by_name["consolidate"]["flags"] == 1
        assert by_name["consolidate"]["contradiction_quality"] == 1.0
        assert by_name["consolidate"]["current_accuracy"] == 0.75
        assert by_name["decayed"]["information_loss"] == 0.0
        assert by_name["temporal"]["current_accuracy"] == 0.75
        assert by_name["temporal"]["stale_intrusion"] == 0.1667
        assert by_name["combined"]["current_accuracy"] == 1.0
        assert by_name["combined"]["stale_intrusion"] == 0.0
        assert by_name["combined"]["chain_integrity"] == 1.0
        assert by_name["consolidate-purge"]["chain_integrity"] == 0.75
        assert by_name["consolidate-purge"]["ledger_replay_ok"] is False
        assert by_name["decay-no-floor"]["information_loss"] == 0.375
        assert by_name["temporal-silent"]["audit_recall"] == 0.8333
        assert by_name["temporal-silent"]["chain_integrity"] == 0.875
        assert by_name["temporal-silent"]["ledger_replay_ok"] is False
        # The replay/retention invariant: an arm reconstructs the full episode
        # set if and only if it never broke a provenance chain.
        for arm in report["arms"]:
            assert arm["ledger_replay_ok"] is (arm["chain_integrity"] == 1.0)
