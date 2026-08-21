---
id: SPEC-217
title: "InMemoryOutcomeStore: outcome recording and task completion analytics"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-20
substrate:
  - maistro-engine#ADR-013
  - maistro-engine#ADR-014
  - maistro-engine#ADR-017
implements:
  - maistro-engine#ADR-017
related:
  - maistro-engine#SPEC-215
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-217: InMemoryOutcomeStore: outcome recording and task completion analytics

## Context

Without outcome tracking, there was no way to measure task completion
rates, compare model/provider performance by task type, or build
experience-augmented prompts that reference past results. ADR-017 decided
to port `InMemoryOutcomeStore` with bounded FIFO storage and an
org-filtered completion-rate query.

## Goals

- Record `Outcome` entries (task type, model, provider, success/failure,
  timing, token counts) with bounded memory via FIFO eviction.
- Compute task completion rate (`{total, succeeded, failed, rate,
  by_model}`) over a configurable day window, optionally org-filtered.

## Non-goals

- Persisted (non-in-memory) outcome storage.
- Real-time alerting on completion-rate drops (a consumer concern, not this
  store's).

## Decision

`maistro/memory/outcomes.py`:

```python
class InMemoryOutcomeStore:
    def __init__(self, max_outcomes: int = MAX_OUTCOMES) -> None: ...
    async def record(self, outcome: Outcome) -> int: ...
    async def get_task_completion_rate(self, task_type="", days=7, org_id="") -> dict[str, Any]: ...
    async def get_experience_context(self, ...) -> ...: ...
    async def get_usage_breakdown(self, ...) -> ...: ...
    async def get_daily_timeseries(self, ...) -> ...: ...
    async def list_outcomes(self, ...) -> list[Outcome]: ...
```

`record()` appends an `Outcome` and returns an auto-incrementing integer ID;
when the store is at `max_outcomes` capacity, the oldest entry is evicted
before the new one is added. `get_task_completion_rate()` filters by
`task_type` (when given), restricts to outcomes recorded within the `days`
window, and further restricts to a single `org_id` when provided via the
internal `_org_matches` helper — outcomes recorded for other orgs are
excluded from the computed rate.

The implemented module additionally provides `get_experience_context`,
`get_usage_breakdown`, `get_daily_timeseries`, and `list_outcomes`, which
grew on top of ADR-017's original surface; these are later additions not
enumerated in ADR-017's acceptance criteria and are out of scope for this
spec's criteria below.

## Acceptance criteria

- [x] `record()` stores an outcome and returns an integer ID
- [x] `record()` evicts the oldest entry when at capacity
- [x] `get_task_completion_rate()` returns
      `{total, succeeded, failed, rate, by_model}`
- [x] `get_task_completion_rate()` respects the `days` window
- [x] `get_task_completion_rate()` is org-filtered when `org_id` is provided

## Testing

| Test | Covers |
|---|---|
| `test_record_returns_id` | happy path |
| `test_record_eviction_at_cap` | FIFO cap |
| `test_completion_rate_calculation` | math |
| `test_completion_rate_day_window` | time filter |
| `test_completion_rate_org_filter` | org isolation |

## Open questions

- None — design is implemented and stable as of this writing.

## References

- [ADR-013: Memory types](../adr/ADR-013-memory-types.md)
- [ADR-014: Memory protocols](../adr/ADR-014-memory-protocols.md)
- [ADR-017: Outcome + InMemoryOutcomeStore](../adr/ADR-017-outcome-store.md)
- `packages/maistro-core/src/maistro/memory/outcomes.py`
