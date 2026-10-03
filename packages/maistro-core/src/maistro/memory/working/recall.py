"""Graph-backed recall over the working-memory projection (#301).

The epic's premise: durable, lossless context **without assuming vector
retrieval is the answer**. Recall here is deliberately structural:

* candidates come from the **working set** — what this Workspace's log says
  is live — not from a similarity index;
* matching is lexical (whole-term overlap over entry text and metadata tags)
  plus explicit recency, both deterministic and reproducible in tests;
* expansion is **lineage** — the projection's typed edges (shared
  ``result_ref``, shared content digest), i.e. "the result behind this
  entry" and "the same claim re-observed" — never a learned embedding.

Entries whose content digest is identical are **collapsed**: a hypothesis
re-stated five times is one fact with five observations, and returning it
five times spends context on redundancy the log already measured. The
redundancy itself is quantified separately by
:mod:`maistro.memory.working.measurement`.
"""

from __future__ import annotations

from dataclasses import dataclass

from maistro.memory.working.projection import WorkingMemoryManager, WorkspaceWorkingMemory
from maistro.memory.working.store import WorkspaceLogStore
from maistro.memory.working.types import (
    ObservationKind,
    WorkingResult,
    WorkspaceObservation,
)

#: Tokens shorter than this carry no match signal ("the", "a", hex fragments).
_MIN_TERM_LEN = 3


@dataclass(frozen=True)
class RecallHit:
    """One recalled entry, optionally resolved to its full result."""

    entry: WorkspaceObservation
    result: WorkingResult | None
    score: float
    #: The query terms that matched, and "lineage" when the hit arrived by
    #: traversal rather than its own text.
    matched: tuple[str, ...]


def _terms(text: str) -> set[str]:
    return {t for t in text.lower().split() if len(t) >= _MIN_TERM_LEN}


def score_entry(
    entry: WorkspaceObservation, query_terms: set[str]
) -> tuple[float, tuple[str, ...]]:
    """Deterministic lexical score: matched-term share, no model involved.

    Metadata ``tags`` count as terms (a tool result tagged ``deploy`` matches
    a query about deploys without the word appearing in the compact line).
    """
    if not query_terms:
        return 0.0, ()
    haystack = _terms(entry.text)
    raw_tags = entry.meta.get("tags", [])
    if isinstance(raw_tags, (list, tuple)):
        for tag in raw_tags:
            haystack.update(_terms(str(tag)))
    matched = tuple(sorted(haystack & query_terms))
    if not matched:
        return 0.0, ()
    return len(matched) / len(query_terms), matched


class WorkingMemoryRecall:
    """Recall backed by the real durable log through its projection."""

    def __init__(
        self,
        manager: WorkingMemoryManager,
        store: WorkspaceLogStore | None = None,
    ) -> None:
        self._manager = manager
        # Result resolution falls back to the durable store when the
        # projection has not hydrated a referenced payload (open question 2
        # in the ADR: hydration selects, it does not materialise everything).
        self._store = store if store is not None else manager.store

    @staticmethod
    def _within_kinds(
        entries: list[WorkspaceObservation],
        kinds: tuple[ObservationKind, ...] | None,
    ) -> list[WorkspaceObservation]:
        """The working-set entries whose kind a query admits."""
        if kinds is None:
            return list(entries)
        return [e for e in entries if e.kind in kinds]

    @staticmethod
    def _rank(
        candidates: list[WorkspaceObservation],
        query_terms: set[str],
    ) -> list[RecallHit]:
        """Score the working set against the query, newest-favored.

        Recency tiebreaker: later log positions are worth more, and equal
        scores break toward the newest observation.
        """
        scored: list[RecallHit] = []
        total = max(len(candidates), 1)
        for position, entry in enumerate(candidates):
            score, matched = score_entry(entry, query_terms)
            if query_terms and score == 0.0:
                continue
            score += 0.01 * (position / total)
            scored.append(RecallHit(entry=entry, result=None, score=score, matched=matched))
        scored.sort(
            key=lambda hit: (hit.score, hit.entry.seq if hit.entry.seq else 0), reverse=True
        )
        return scored

    async def _resolve_results(
        self,
        workspace_id: str,
        projection: WorkspaceWorkingMemory,
        hits: list[RecallHit],
    ) -> list[RecallHit]:
        """Attach full results, hydrating from the store when the projection
        has not materialised the referenced payload."""
        resolved: list[RecallHit] = []
        for hit in hits:
            ref = hit.entry.result_ref
            result: WorkingResult | None = projection.result(ref) if ref else None
            if result is None and ref:
                result = await self._store.get_result(workspace_id, ref)
            resolved.append(
                RecallHit(entry=hit.entry, result=result, score=hit.score, matched=hit.matched)
            )
        return resolved

    async def recall(
        self,
        workspace_id: str,
        query: str = "",
        *,
        kinds: tuple[ObservationKind, ...] | None = None,
        limit: int = 8,
        with_results: bool = True,
        lineage: bool = True,
        keep_duplicates: bool = False,
    ) -> list[RecallHit]:
        """Rank the working set against ``query``; resolve full results.

        An empty query is not an error — it is "give me the working set,
        newest first", which is what a fresh cycle in a long-running
        Workspace wants before it has said anything.

        ``keep_duplicates=False`` (the default) collapses digest-equal
        entries to their newest observation.
        """
        projection = await self._manager.projection(workspace_id)
        candidates = self._within_kinds(projection.active_entries(), kinds)
        scored = self._rank(candidates, _terms(query))

        if lineage:
            scored = self._expand(projection, scored)

        if not keep_duplicates:
            scored = _collapse_duplicates(scored)

        trimmed = scored[:limit]
        if with_results:
            return await self._resolve_results(workspace_id, projection, trimmed)
        return trimmed

    def _expand(
        self,
        projection: WorkspaceWorkingMemory,
        hits: list[RecallHit],
    ) -> list[RecallHit]:
        """One hop of lineage expansion behind the top direct hits.

        Kept to one hop deliberately: unbounded traversal is how a working
        graph becomes the whole log in the prompt. Expanded entries carry
        lower scores than anything matched directly and are marked
        ``matched=("lineage",)`` so a caller can see why a hit is there.
        """
        direct_ids = {h.entry.entry_id for h in hits}
        expanded: list[RecallHit] = []
        floor = min((h.score for h in hits), default=0.0)
        for hit in hits[: max(len(hits) // 2, 1)]:
            for neighbor in projection.neighbors(hit.entry.entry_id):
                if neighbor.entry_id in direct_ids:
                    continue
                direct_ids.add(neighbor.entry_id)
                expanded.append(
                    RecallHit(
                        entry=neighbor,
                        result=None,
                        score=max(floor / 2, 0.0),
                        matched=("lineage",),
                    )
                )
        return sorted(
            hits + expanded,
            key=lambda h: (h.score, h.entry.seq if h.entry.seq else 0),
            reverse=True,
        )


def _collapse_duplicates(hits: list[RecallHit]) -> list[RecallHit]:
    """Digest-equal entries collapse to their newest observation.

    Redundant hypotheses are a *measurement*, not five recall slots. The
    newest observation wins because it is the one most likely to carry the
    refined phrasing; the older ones remain in the log.
    """
    seen_digests: set[str] = set()
    kept: list[RecallHit] = []
    for hit in hits:
        digest = hit.entry.digest
        if digest and digest in seen_digests:
            continue
        if digest:
            seen_digests.add(digest)
        kept.append(hit)
    return kept
