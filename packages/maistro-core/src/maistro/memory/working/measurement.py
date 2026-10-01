"""Measured working memory: redundant hypotheses, fresh vs lineage recall.

The epic's last scope line is a demand for measurement, not vibes: "measured
redundant-hypothesis/fresh-vs-lineage performance". These metrics are
deterministic functions over a projection — same graph, same numbers — and
per ADR-083026-a91e a metric that cannot be measured on the given graph is
``None`` (absent), never a polite zero.

* **Redundant-hypothesis collapse** — how much of the hypothesis stream is
  the same claim re-observed (equal content digests). High collapse is the
  log-as-context win: five re-statements cost one recall slot and one digest.
* **Fresh vs lineage** — for a set of probe queries: hits scored from entry
  text alone (fresh) versus hits additionally reachable by one hop of the
  projection's typed edges — shared ``result_ref`` or shared digest
  (lineage). Lineage gain is the measured value of "remember what produced
  this", the AVO-style lineage finding the epic cites.
"""

from __future__ import annotations

from dataclasses import dataclass

from maistro.memory.working.projection import WorkspaceWorkingMemory
from maistro.memory.working.recall import _terms, score_entry
from maistro.memory.working.types import ObservationKind, WorkspaceObservation


@dataclass(frozen=True)
class RedundantHypothesisMeasurement:
    """How much of the hypothesis stream is repetition."""

    hypotheses_total: int
    unique: int
    redundant: int
    #: ``redundant / hypotheses_total``; absent (``None``) when the graph
    #: holds no hypotheses — unmeasured, not zero (ADR-083026-a91e).
    collapse_ratio: float | None


@dataclass(frozen=True)
class FreshVsLineageMeasurement:
    """Recall reachable fresh (text match) vs through lineage (typed edges)."""

    queries: int
    fresh_hits: int
    #: |fresh U one-hop neighborhood| - everything reachable when traversal
    #: is on, per query, summed over queries.
    lineage_hits: int
    #: |fresh AND neighborhood| / |fresh| - how many fresh hits have graph
    #: edges at all. Absent when no query recalls anything fresh.
    overlap_ratio: float | None
    #: |neighborhood minus fresh| / |fresh| - the measured lift the edges buy
    #: beyond what entry text alone reaches. Absent when no query recalls
    #: anything fresh.
    lineage_gain: float | None


def measure_redundant_hypotheses(
    projection: WorkspaceWorkingMemory,
    *,
    kind: ObservationKind = ObservationKind.HYPOTHESIS,
) -> RedundantHypothesisMeasurement:
    """Collapse measurement over *every held entry* of ``kind``.

    The log, not the working set, is the right population: simplification
    removing redundancy from the working set is the system working; the
    measurement should still see that the redundancy existed.
    """
    held = [e for e in projection.all_entries() if e.kind is kind]
    if not held:
        return RedundantHypothesisMeasurement(
            hypotheses_total=0, unique=0, redundant=0, collapse_ratio=None
        )
    digests = {e.digest for e in held if e.digest}
    unique = len(digests)
    redundant = len(held) - unique
    return RedundantHypothesisMeasurement(
        hypotheses_total=len(held),
        unique=unique,
        redundant=redundant,
        collapse_ratio=redundant / len(held),
    )


def _fresh_hits(projection: WorkspaceWorkingMemory, query: str) -> list[WorkspaceObservation]:
    """Entries whose own text/tags match the query, scored, above zero."""
    query_terms = _terms(query)
    if not query_terms:
        return []
    hits: list[WorkspaceObservation] = []
    for entry in projection.active_entries():
        score, _ = score_entry(entry, query_terms)
        if score > 0.0:
            hits.append(entry)
    return hits


def _lineage_hits(
    projection: WorkspaceWorkingMemory, fresh: list[WorkspaceObservation]
) -> list[WorkspaceObservation]:
    """The one-hop neighborhood of the fresh hits, *including* fresh entries
    themselves when they have edges — the neighborhood is the measured set,
    and excluding the fresh ids here would make ``overlap_ratio`` zero by
    construction, which is a metric that cannot fail, not a finding."""
    found: dict[str, WorkspaceObservation] = {}
    for entry in fresh:
        for neighbor in projection.neighbors(entry.entry_id):
            found[neighbor.entry_id] = neighbor
    return sorted(found.values(), key=lambda e: e.seq if e.seq is not None else 0)


def measure_fresh_vs_lineage(
    projection: WorkspaceWorkingMemory,
    queries: list[str],
) -> FreshVsLineageMeasurement:
    """Deterministic probe measurement over the projection's working set.

    No LLM and no fixtures shipped with the metric: the caller supplies the
    probe queries (typically the cycle's own task text), and the numbers
    describe *this* Workspace's graph. A projection with an empty working
    set measures zero hits — that is a real measurement of an empty graph,
    not an absence — but the ratios stay ``None`` because a division by zero
    is not a finding.
    """
    fresh_total = 0
    reach_total = 0
    overlap_total = 0
    for query in queries:
        fresh = _fresh_hits(projection, query)
        neighborhood = _lineage_hits(projection, fresh)
        fresh_ids = {e.entry_id for e in fresh}
        neighborhood_ids = {e.entry_id for e in neighborhood}
        fresh_total += len(fresh_ids)
        reach_total += len(fresh_ids | neighborhood_ids)
        # A fresh hit "overlaps" when it has edges at all: its lineage was
        # reachable the moment it matched, even though neighbors() never
        # returns the entry itself.
        overlap_total += sum(1 for entry in fresh if projection.neighbors(entry.entry_id))
    overlap_ratio: float | None = None
    lineage_gain: float | None = None
    if fresh_total > 0:
        overlap_ratio = overlap_total / fresh_total
        lineage_gain = (reach_total - fresh_total) / fresh_total
    return FreshVsLineageMeasurement(
        queries=len(queries),
        fresh_hits=fresh_total,
        lineage_hits=reach_total,
        overlap_ratio=overlap_ratio,
        lineage_gain=lineage_gain,
    )
