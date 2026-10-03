"""Working-graph candidates for Dreaming (ADR-082226-5104 §7, SPEC-241).

Dreaming consolidates working memory into durable memory *as an ordinary Run*.
What this module contributes is the candidate side of that: a read-only view
of one Workspace's working graph — the records, the entity relations, the
hypothesis-tier entries — that a consolidation Graph can consume as input.

What this module deliberately does not have: any route to a durable store.
Promotion happens only when the Dreaming Run's own NodeRuns call the
authoritative stores (``EpisodicStore``, consolidation proposals applied
through ``maistro.memory.episodic.consolidation``). The working graph cannot
promote durable truth, because it has no method that could.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from maistro.memory.working.protocol import RelationRecord
from maistro.types.memory import MemoryTier

if TYPE_CHECKING:
    from maistro.memory.working.projection import WorkspaceWorkingMemoryProjection
    from maistro.memory.working.protocol import EntityRecord
    from maistro.types.memory import EpisodicMemory


@dataclass(frozen=True)
class DreamingCandidateSet:
    """One Workspace's working graph, projected for consolidation.

    ``memories`` are the hot records (already durable-backed by identity);
    ``hypotheses`` are the subset still in the HYPOTHESIS tier — the
    "working hypothesis vs durable knowledge" separation ADR-082226-5104 §6
    draws. ``relations`` are the temporary associations a Dreaming Run may
    consider promoting; ``clusters`` group the entities into connected
    co-occurrence neighbourhoods (bounded traversal, §7's "clustering"), so
    a consolidation Graph sees association structure, not just an edge bag.
    Nothing here is durable until that Run says so.
    """

    workspace_id: str
    memories: tuple[EpisodicMemory, ...]
    hypotheses: tuple[EpisodicMemory, ...]
    entities: tuple[EntityRecord, ...]
    relations: tuple[RelationRecord, ...]
    clusters: tuple[tuple[str, ...], ...] = ()


async def collect_candidates(
    projection: WorkspaceWorkingMemoryProjection,
    *,
    limit: int = 200,
) -> DreamingCandidateSet:
    """Read one projection's candidate set. Reads only; writes nothing."""
    memories = projection.records()[:limit]
    hypotheses = tuple(m for m in memories if m.tier == MemoryTier.HYPOTHESIS)
    entities: list[EntityRecord] = []
    for name in projection.entity_names():
        record = await projection.lookup_entity(name)
        if record is not None:
            entities.append(record)
    relations = [
        RelationRecord(source=a, target=b, kind="co_occurs_with", weight=weight)
        for a, b, weight in projection.relation_pairs()
    ]
    # Connected neighbourhoods, discovered by bounded BFS from each
    # not-yet-visited entity (most-mentioned first, so cluster order is
    # deterministic). Traversal cannot leave this projection, so clusters
    # inherit the one-Workspace isolation the graph has.
    clusters: list[tuple[str, ...]] = []
    visited: set[str] = set()
    depth = max(1, len(entities))
    for name in projection.entity_names():
        if name in visited:
            continue
        walk = await projection.traverse(name, max_depth=depth)
        if walk.visited:
            clusters.append(walk.visited)
            visited.update(walk.visited)
    return DreamingCandidateSet(
        workspace_id=projection.workspace_id,
        memories=tuple(memories),
        hypotheses=hypotheses,
        entities=tuple(entities),
        relations=tuple(relations),
        clusters=tuple(clusters),
    )
