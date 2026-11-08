---
id: ADR-016
title: EpisodicMemory + 7-tier weights + InMemoryEpisodicStore
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
  - packages/maistro-core/tests/memory/episodic/test_episodic.py
  - packages/maistro-core/tests/memory/episodic/test_ranking.py
ac-modules:
  AC-1: maistro.memory.episodic.tiers
  AC-2: maistro.memory.episodic.tiers
  AC-3: maistro.memory.episodic.tiers
  AC-4: maistro.memory.episodic.tiers
  AC-5: maistro.memory.episodic.tiers
  AC-6: maistro.memory.episodic.store
  AC-7: maistro.memory.episodic.store
  AC-8: maistro.memory.episodic.ranking
  AC-9: maistro.memory.episodic.store
  AC-10: maistro.memory.episodic.store
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
    reason: Audited against episodic tier/store implementation and focused retrieval/ranking tests.
---

# ADR-016: EpisodicMemory + 7-tier weights + InMemoryEpisodicStore

**Status:** Implemented  
**Date:** 2026-04-26  
**Tranche:** T2  
**Depends on:** ADR-013, ADR-014

---

## Context

No episodic memory — agents cannot learn from past experiences across sessions.

## Decision

Port `InMemoryEpisodicStore` + `tiers.py` (clamp_weight, reinforce, decay) into `src/maistro/memory/episodic/`. The 7-tier system enforces weight bounds so REGRET memories never fade below 0.6 (structurally unforgettable) and WISDOM memories stay ≥0.9.

## Acceptance criteria

- [x] **AC-1** `clamp_weight(REGRET, 0.0)` returns 0.6 (floor enforced)
- [x] **AC-2** `clamp_weight(WISDOM, 0.5)` returns 0.9 (floor enforced)
- [x] **AC-3** `clamp_weight(OBSERVATION, 0.8)` returns 0.5 (ceiling enforced)
- [x] **AC-4** `reinforce()` returns new `EpisodicMemory` with weight increased, clamped
- [x] **AC-5** `decay()` returns new `EpisodicMemory` with weight decreased, clamped to floor
- [x] **AC-6** `store()` + `retrieve()` returns matching memories by keyword
- [x] **AC-7** `retrieve()` blocks cross-org memory leakage (team scope requires org match)
- [x] **AC-8** `retrieve()` scores by weight × word-overlap
- [x] **AC-9** `reinforce()` (store method) updates the stored memory weight
- [x] **AC-10** Deleted memories are excluded from retrieval

## Test plan

| Test | Covers |
|---|---|
| `test_clamp_weight_regret_floor` | REGRET ≥ 0.6 |
| `test_clamp_weight_wisdom_floor` | WISDOM ≥ 0.9 |
| `test_clamp_weight_observation_ceiling` | OBSERVATION ≤ 0.5 |
| `test_reinforce_increases_weight` | reinforce op |
| `test_decay_decreases_weight_to_floor` | decay op, floor enforced |
| `test_retrieve_keyword_match` | basic retrieval |
| `test_retrieve_team_scope_requires_org` | cross-tenant leakage |
| `test_retrieve_excludes_deleted` | soft delete |
| `test_reinforce_store_method_updates_weight` | store reinforce |

## Source references

- `stronghold/src/stronghold/memory/episodic/store.py`
- `stronghold/src/stronghold/memory/episodic/tiers.py`


## 2026-09-28 implementation audit

Verified against the episodic tier/store implementation and focused episodic retrieval/ranking tests. The original seven-tier bounds, reinforcement/decay, scope isolation, soft-delete exclusion, and weighted relevance requirements are implemented. Ranking has since evolved to a shared hybrid lexical/vector scorer whose combined relevance remains multiplied by memory weight.
