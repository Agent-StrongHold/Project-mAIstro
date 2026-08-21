---
id: ADR-016
title: EpisodicMemory + 7-tier weights + InMemoryEpisodicStore
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
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
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
---

# ADR-016: EpisodicMemory + 7-tier weights + InMemoryEpisodicStore

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T2  
**Depends on:** ADR-013, ADR-014

---

## Context

No episodic memory — agents cannot learn from past experiences across sessions.

## Decision

Port `InMemoryEpisodicStore` + `tiers.py` (clamp_weight, reinforce, decay) into `src/maistro/memory/episodic/`. The 7-tier system enforces weight bounds so REGRET memories never fade below 0.6 (structurally unforgettable) and WISDOM memories stay ≥0.9.

## Acceptance criteria

- [ ] `clamp_weight(REGRET, 0.0)` returns 0.6 (floor enforced)
- [ ] `clamp_weight(WISDOM, 0.5)` returns 0.9 (floor enforced)
- [ ] `clamp_weight(OBSERVATION, 0.8)` returns 0.5 (ceiling enforced)
- [ ] `reinforce()` returns new `EpisodicMemory` with weight increased, clamped
- [ ] `decay()` returns new `EpisodicMemory` with weight decreased, clamped to floor
- [ ] `store()` + `retrieve()` returns matching memories by keyword
- [ ] `retrieve()` blocks cross-org memory leakage (team scope requires org match)
- [ ] `retrieve()` scores by weight × word-overlap
- [ ] `reinforce()` (store method) updates the stored memory weight
- [ ] Deleted memories are excluded from retrieval

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
