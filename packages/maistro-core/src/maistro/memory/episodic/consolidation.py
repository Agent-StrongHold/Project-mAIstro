"""Memory consolidation: merge, contradiction review, incremental writes (ADR-080 part B / SPEC-241)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field

from maistro.memory.types import CONTRADICT_DELTA, EpisodicMemory

SimilarityFn = Callable[[EpisodicMemory, EpisodicMemory], float]
ContradictionFn = Callable[[EpisodicMemory, EpisodicMemory], bool]

SIMILARITY_MERGE_THRESHOLD = 0.85


@dataclass(frozen=True)
class MergeProposal:
    """A proposed merge of similar memories: primary survives, absorbed are amended away."""

    primary: EpisodicMemory
    absorbed: list[EpisodicMemory]
    merged_weight: float


@dataclass(frozen=True)
class ContradictionFlag:
    """A proposed contradiction: both sides lose confidence and require human review."""

    a: EpisodicMemory
    b: EpisodicMemory
    confidence_delta: float


@dataclass(frozen=True)
class ConsolidationResult:
    """The output of one consolidation pass: proposed merges and contradiction flags."""

    merges: list[MergeProposal] = field(default_factory=list)
    contradictions: list[ContradictionFlag] = field(default_factory=list)


def _weighted_merge_weight(group: list[EpisodicMemory]) -> float:
    total_weight = sum(m.weight for m in group)
    if total_weight == 0:
        return 0.0
    return sum(m.weight * m.weight for m in group) / total_weight


def consolidate(
    memories: list[EpisodicMemory],
    *,
    similarity_fn: SimilarityFn,
    contradiction_fn: ContradictionFn,
    similarity_threshold: float = SIMILARITY_MERGE_THRESHOLD,
) -> ConsolidationResult:
    """Propose merges for similar pairs and flags for contradicting pairs; never mutates input."""
    merges: list[MergeProposal] = []
    contradictions: list[ContradictionFlag] = []
    absorbed_ids: set[str] = set()

    for i, a in enumerate(memories):
        if a.memory_id in absorbed_ids:
            continue
        for b in memories[i + 1 :]:
            if b.memory_id in absorbed_ids:
                continue
            if contradiction_fn(a, b):
                contradictions.append(
                    ContradictionFlag(a=a, b=b, confidence_delta=CONTRADICT_DELTA)
                )
                continue
            if similarity_fn(a, b) >= similarity_threshold:
                group = [a, b]
                merges.append(
                    MergeProposal(
                        primary=a,
                        absorbed=[b],
                        merged_weight=_weighted_merge_weight(group),
                    )
                )
                absorbed_ids.add(b.memory_id)

    return ConsolidationResult(merges=merges, contradictions=contradictions)


def apply_merge(proposal: MergeProposal) -> tuple[EpisodicMemory, list[EpisodicMemory]]:
    """Amend the primary's weight in place; mark absorbed records deleted (never purged)."""
    primary = dataclasses.replace(proposal.primary, weight=proposal.merged_weight)
    absorbed = [dataclasses.replace(m, deleted=True) for m in proposal.absorbed]
    return primary, absorbed


def apply_contradiction(flag: ContradictionFlag) -> tuple[EpisodicMemory, EpisodicMemory]:
    """Lower both sides' weight by confidence_delta and flag both for review."""
    a = dataclasses.replace(
        flag.a, weight=max(0.0, flag.a.weight - flag.confidence_delta), flagged_for_review=True
    )
    b = dataclasses.replace(
        flag.b, weight=max(0.0, flag.b.weight - flag.confidence_delta), flagged_for_review=True
    )
    return a, b


def consolidate_pair(
    new_memory: EpisodicMemory,
    existing: EpisodicMemory,
    *,
    similarity_fn: SimilarityFn,
    contradiction_fn: ContradictionFn,
    similarity_threshold: float = SIMILARITY_MERGE_THRESHOLD,
) -> ConsolidationResult:
    """Immediate-trigger path: run consolidate for a single new-vs-existing pair synchronously."""
    return consolidate(
        [new_memory, existing],
        similarity_fn=similarity_fn,
        contradiction_fn=contradiction_fn,
        similarity_threshold=similarity_threshold,
    )


@dataclass(frozen=True)
class BatchReport:
    """Observability counts from one overnight consolidation batch run."""

    merged: int
    flagged: int


def run_batch(
    memories: list[EpisodicMemory],
    *,
    similarity_fn: SimilarityFn,
    contradiction_fn: ContradictionFn,
    apply_store_merge: Callable[[MergeProposal], None],
    apply_store_contradiction: Callable[[ContradictionFlag], None],
) -> BatchReport:
    """Run consolidate over a scope's memory set, applying each proposal incrementally."""
    result = consolidate(memories, similarity_fn=similarity_fn, contradiction_fn=contradiction_fn)
    for merge in result.merges:
        apply_store_merge(merge)
    for flag in result.contradictions:
        apply_store_contradiction(flag)
    return BatchReport(merged=len(result.merges), flagged=len(result.contradictions))
