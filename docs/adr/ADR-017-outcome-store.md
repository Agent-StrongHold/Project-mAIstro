---
id: ADR-017
title: Outcome + InMemoryOutcomeStore
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

# ADR-017: Outcome + InMemoryOutcomeStore

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T2  
**Depends on:** ADR-013, ADR-014

---

## Context

No outcome tracking — impossible to measure task completion rates, model performance by task type, or build experience-augmented prompts.

## Decision

Port `InMemoryOutcomeStore` into `src/maistro/memory/outcomes.py`. FIFO eviction at 10,000. Provides `get_task_completion_rate()` with org-filtering.

## Acceptance criteria

- [ ] `record()` stores outcome and returns an integer ID
- [ ] `record()` evicts oldest when at cap
- [ ] `get_task_completion_rate()` returns `{total, succeeded, failed, rate, by_model}`
- [ ] `get_task_completion_rate()` respects the `days` window
- [ ] `get_task_completion_rate()` is org-filtered when `org_id` provided

## Test plan

| Test | Covers |
|---|---|
| `test_record_returns_id` | happy path |
| `test_record_eviction_at_cap` | FIFO cap |
| `test_completion_rate_calculation` | math |
| `test_completion_rate_day_window` | time filter |
| `test_completion_rate_org_filter` | org isolation |

## Source references

- `stronghold/src/stronghold/memory/outcomes.py`
