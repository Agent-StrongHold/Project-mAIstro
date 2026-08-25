---
id: SPEC-241
title: "Memory consolidation — merge, contradiction review, incremental writes (ADR-080 part B)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-013
  - maistro-engine#ADR-016
implements:
  - maistro-engine#ADR-080
related:
  - maistro-engine#SPEC-240
  - maistro-engine#SPEC-242
  - maistro-engine#SPEC-243
supersedes: []
blocks: []
blocked-by:
  - maistro-engine#SPEC-240
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/memory/episodic/test_consolidation.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-241: Memory consolidation

## Context

ADR-080 part (B) specifies a consolidation pass that runs overnight on batch-priced tokens and
additionally fires immediately on a detected contradiction, merging semantically-similar memories
(weighted by current weight) and, on contradiction, lowering both sides' confidence and flagging for
review rather than picking a winner — writes are incremental, never full replacement. None of this
exists today: there is no consolidation runner, no semantic-similarity merge, no contradiction
review queue.

## Goals

- A `consolidate(memories: list[EpisodicMemory]) -> ConsolidationResult` pure function that, given a
  batch of memories, proposes merges (semantically-similar pairs/groups) and flags (contradicting
  pairs) without mutating the store directly.
- A `ConsolidationResult` data shape carrying `merges: list[MergeProposal]` and
  `contradictions: list[ContradictionFlag]`.
- An overnight batch runner entry point that calls `consolidate` over a scope's memory set using
  batch-priced LLM calls for similarity/contradiction judgment, applying writes incrementally.
- An immediate-trigger path: when a write detects a contradiction with an existing memory (via the
  embedding similarity already available per ADR-079), consolidation runs for just that pair without
  waiting for the overnight batch.

## Non-goals

- The decay/reinforcement primitives consolidation reads weight from — SPEC-240, a dependency.
- Cross-scope consent — SPEC-242.
- Retrieval ranking — SPEC-243.
- The specific embedding/similarity model choice — defers to ADR-079's existing model registry.
- A durable job-scheduling system for the "overnight" cadence — depends on ADR-046 (Scheduler);
  this SPEC defines the consolidation function and its trigger contract, not the cron wiring.

## Decision

```python
@dataclass
class MergeProposal:
    primary: EpisodicMemory       # the surviving record, incrementally amended
    absorbed: list[EpisodicMemory]
    merged_weight: float          # weighted average by absorbed memories' current weight

@dataclass
class ContradictionFlag:
    a: EpisodicMemory
    b: EpisodicMemory
    confidence_delta: float       # amount both sides' confidence drops

@dataclass
class ConsolidationResult:
    merges: list[MergeProposal]
    contradictions: list[ContradictionFlag]

def consolidate(
    memories: list[EpisodicMemory],
    *,
    similarity_fn: Callable[[EpisodicMemory, EpisodicMemory], float],
    contradiction_fn: Callable[[EpisodicMemory, EpisodicMemory], bool],
) -> ConsolidationResult: ...
```

`similarity_fn`/`contradiction_fn` are injected (protocol-driven DI per the repo convention) so the
pure merge/flag logic is testable without a real LLM call; the overnight runner and immediate-trigger
path both wire real embedding-similarity and an LLM-judge contradiction check.

Applying a `MergeProposal` or `ContradictionFlag` to the store is always an **amend-in-place** write
on the primary/both records — `absorbed` records are marked `deleted=True` rather than purged, so
history survives.

## Acceptance criteria

- [x] `consolidate` merges memories whose `similarity_fn` exceeds a threshold, weighting the merged
      result by each input's current `weight`.
- [x] `consolidate` flags (does not merge) pairs where `contradiction_fn` returns true, computing a
      `confidence_delta` that lowers both sides rather than discarding either.
- [x] Applying a merge result never deletes the absorbed records — they are marked `deleted=True`,
      preserving history (incremental write, never full replacement).
- [x] The immediate-trigger path runs `consolidate` for a single new-memory-vs-existing pair
      synchronously after a write that yields contradiction, without waiting for the batch runner
      (`consolidate_pair`).
- [x] The overnight batch runner processes the scope's memory set in batches and reports
      counts (merged, flagged) for observability (`run_batch` / `BatchReport`). Note: `run_batch`
      applies proposals via injected `apply_store_merge`/`apply_store_contradiction` callbacks — the
      real cron/batch-token-pricing wiring is deferred to ADR-046 (Scheduler), per Non-goals.

## Testing

- New unit tests for `consolidate`'s pure merge/flag logic using fake `similarity_fn`/`contradiction_fn`.
- Integration test exercising the immediate-trigger path against the episodic store.

## Open questions

- Whether merge proposals require human approval before applying, or apply automatically when
  confidence is high — ADR-080 doesn't specify; default to auto-apply for merges (reversible via
  `deleted` flag) and always-flag (never auto-resolve) for contradictions, revisit if this proves
  too aggressive in practice.

## References

- `packages/maistro-core/src/maistro/memory/episodic/tiers.py`
- [ADR-080: Memory Dynamics](../adr/ADR-080-memory-dynamics.md)
- [ADR-079: Model registry, routing, embeddings](../adr/ADR-079-model-registry-routing-embeddings.md)
