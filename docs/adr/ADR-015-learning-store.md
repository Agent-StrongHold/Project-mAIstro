---
id: ADR-015
title: Learning type + InMemoryLearningStore
repo: maistro-engine
kind: adr
status: Implemented
created: 2026-04-26
implemented: 2026-09-28
substrate:
  - maistro-engine#ADR-013
  - maistro-engine#ADR-014
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-core/tests/memory/learnings/test_learning_store.py
ac-modules:
  AC-1: maistro.memory.learnings.store
  AC-2: maistro.memory.learnings.store
  AC-3: maistro.memory.learnings.store
  AC-4: maistro.memory.learnings.store
  AC-5: maistro.memory.learnings.store
  AC-6: maistro.memory.learnings.store
  AC-7: maistro.memory.learnings.store
  AC-8: maistro.memory.learnings.store
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
  - status: Implemented
    date: 2026-09-28
    reason: Audited against InMemoryLearningStore and focused learning-store acceptance tests.
---

# ADR-015: Learning type + InMemoryLearningStore

**Status:** Implemented  
**Date:** 2026-04-26  
**Tranche:** T2  
**Depends on:** ADR-013, ADR-014

---

## Context

No self-improving memory. Every agent call starts from zero — no accumulated corrections from past failures, no promoted patterns to inject into prompts.

## Decision

Port `InMemoryLearningStore` into `src/maistro/memory/learnings/store.py`. Key features: dedup via trigger-key Jaccard overlap (≥50% overlap → overwrite), org-scope isolation (strict — learnings from org-A invisible to org-B), FIFO eviction cap at 10,000, auto-promotion when hit_count ≥ threshold.

## Acceptance criteria

- [x] **AC-1** `store()` deduplicates: same tool + same org + ≥50% key overlap → overwrites, does not add
- [x] **AC-2** `store()` does NOT dedup across different orgs
- [x] **AC-3** `store()` evicts oldest when at capacity
- [x] **AC-4** `find_relevant()` returns learnings with matching trigger keys, org-filtered
- [x] **AC-5** `find_relevant()` excludes learnings from other orgs
- [x] **AC-6** `mark_used()` increments `hit_count` for all provided IDs
- [x] **AC-7** `check_auto_promotions()` changes status to "promoted" at threshold
- [x] **AC-8** `get_promoted()` only returns status="promoted" entries

## Test plan

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

## Source references

- `stronghold/src/stronghold/memory/learnings/store.py`


## 2026-09-28 implementation audit

Verified against the current InMemoryLearningStore and `packages/maistro-core/tests/memory/learnings/test_learning_store.py`. Deduplication, org isolation, bounded eviction, relevance lookup, usage tracking, threshold promotion, and promoted-only retrieval are directly exercised. SPEC-216 carries the same completed behavioral contract but its lifecycle status remains to be reconciled during the spec audit.
