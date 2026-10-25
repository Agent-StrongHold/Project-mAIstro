---
id: SPEC-216
title: "InMemoryLearningStore: dedup, org-scope isolation, FIFO eviction, auto-promotion"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-013
  - maistro-engine#ADR-014
  - maistro-engine#ADR-015
implements:
  - maistro-engine#ADR-015
related:
  - maistro-engine#SPEC-215
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - tests/memory/learnings/test_learning_store.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-216: InMemoryLearningStore: dedup, org-scope isolation, FIFO eviction, auto-promotion

## Context

Without persisted self-improving memory, every agent call started from zero
context — no accumulated corrections from past tool failures, and no
mechanism to promote a frequently-hit correction into something injected
proactively into future prompts. ADR-015 decided to port
`InMemoryLearningStore` with dedup, strict org isolation, bounded capacity,
and threshold-based auto-promotion.

## Goals

- Deduplicate learnings for the same tool within the same org when trigger
  keys overlap ≥50% (Jaccard similarity), overwriting rather than
  accumulating near-duplicates.
- Strict org-scope isolation — a learning stored for org A is never visible
  to org B, including for dedup purposes.
- Bounded memory via FIFO eviction at a fixed capacity (`MAX_LEARNINGS`,
  default 10,000).
- Auto-promote a learning to `status="promoted"` once its `hit_count`
  crosses a caller-supplied threshold.

## Non-goals

- Persisted (non-in-memory) learning storage — covered by the Postgres
  persistence layer, out of scope for this spec.
- Cross-org learning sharing of any kind (explicitly the opposite of the
  isolation guarantee here).

## Decision

`maistro/memory/learnings/store.py`:

```python
class InMemoryLearningStore:
    def __init__(self, max_learnings: int = MAX_LEARNINGS) -> None: ...
    async def store(self, learning: Learning) -> int: ...
    async def find_relevant(self, user_text, *, agent_id=None, org_id="", max_results=10) -> list[Learning]: ...
    async def mark_used(self, learning_ids: list[int]) -> None: ...
    async def mark_outcome(self, ...) -> None: ...
    async def check_auto_promotions(self, threshold=5, *, org_id="") -> list[Learning]: ...
    async def get_promoted(self, task_type=None, *, org_id="") -> list[Learning]: ...
    async def list_ineffective(self, min_uses: int) -> list[Learning]: ...
    async def list_all(self, org_id: str = "", limit: int = 200) -> list[Learning]: ...
```

`store()` computes Jaccard overlap between the incoming learning's
`trigger_keys` and each existing learning's, scoped to the same `tool_name`
and `org_id`; at ≥50% overlap the existing entry is overwritten in place
rather than appended. Different-org learnings are never compared for dedup,
even with identical trigger keys. When at capacity, the oldest entry (by
insertion order) is evicted before a new one is added.

## Acceptance criteria

- [x] `store()` deduplicates: same tool + same org + ≥50% key overlap →
      overwrites, does not add a new entry
- [x] `store()` does NOT dedup across different orgs
- [x] `store()` evicts the oldest entry when at capacity
- [x] `find_relevant()` returns learnings with matching trigger keys,
      org-filtered
- [x] `find_relevant()` excludes learnings from other orgs
- [x] `mark_used()` increments `hit_count` for all provided IDs
- [x] `check_auto_promotions()` changes status to `"promoted"` at threshold
- [x] `get_promoted()` only returns `status="promoted"` entries

## Testing

| Test | Covers |
|---|---|
| `test_store_dedup_same_org` | Jaccard ≥50% overwrites |
| `test_store_no_dedup_different_org` | cross-org isolation |
| `test_store_eviction_at_cap` | FIFO cap |
| `test_find_relevant_keyword_match` | trigger key scoring |
| `test_find_relevant_org_isolation` | org filter |
| `test_mark_used_increments` | hit_count |
| `test_auto_promotion` | threshold promotion |
| `test_get_promoted_only_promoted` | status filter |

## Open questions

- None — design is implemented and stable as of this writing.

## References

- [ADR-013: Memory types](../adr/ADR-013-memory-types.md)
- [ADR-014: Memory protocols](../adr/ADR-014-memory-protocols.md)
- [ADR-015: Learning type + InMemoryLearningStore](../adr/ADR-015-learning-store.md)
- `packages/maistro-core/src/maistro/memory/learnings/store.py`
