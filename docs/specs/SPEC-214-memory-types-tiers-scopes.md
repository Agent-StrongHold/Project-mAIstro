---
id: SPEC-214
title: "Memory types: Learning, EpisodicMemory, Outcome, tiers, and scope filtering"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-20
substrate:
  - maistro-engine#ADR-002
  - maistro-engine#ADR-013
implements:
  - maistro-engine#ADR-013
related:
  - maistro-engine#SPEC-215
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-214: Memory types: Learning, EpisodicMemory, Outcome, tiers, and scope filtering

## Context

maistro-engine had no multi-tier memory data types. ADR-013 decided to port
`Learning` (self-improving correction), `EpisodicMemory` (7-tier weighted
memory), `Outcome` (request outcome), and the supporting `MemoryTier` /
`MemoryScope` enums and weight-bound constants from Stronghold, as plain
stdlib `@dataclass`es (no Pydantic — these are internal types, not API
boundary schemas), with all `stronghold.*` imports removed.

## Goals

- A 7-tier `MemoryTier` enum (`OBSERVATION` → `WISDOM`) with weight bounds
  enforcing that some tiers (`REGRET`, `WISDOM`) cannot decay below a floor.
- A `MemoryScope` enum (`GLOBAL` → `SESSION`) for soft multi-tenancy axes.
- A single source of truth for `WEIGHT_BOUNDS`, `REINFORCE_DELTA`,
  `CONTRADICT_DELTA` so reinforcement/decay deltas aren't re-spelled as
  literals elsewhere.
- Scope-filter helpers (`build_scope_filter`, `matches_scope`) that prevent
  cross-tenant memory leakage.

## Non-goals

- Tier-specific decay deltas (different reinforcement rates per tier) — noted
  in ADR-013 as a possible v1 refinement, not implemented here.
- A CI lint specifically catching inline `delta: float = 0.05` literals
  outside `types/memory.py` (recommended by ADR-013, not yet built).

## Decision

`maistro/types/memory.py`:

```python
class MemoryTier(StrEnum):
    OBSERVATION, HYPOTHESIS, OPINION, LESSON, REGRET, AFFIRMATION, WISDOM

class MemoryScope(StrEnum):
    GLOBAL, ORGANIZATION, TEAM, USER, AGENT, SESSION

WEIGHT_BOUNDS: dict[MemoryTier, tuple[float, float]]
REINFORCE_DELTA: float = 0.05
CONTRADICT_DELTA: float = 0.05

@dataclass class Learning: ...
@dataclass class EpisodicMemory: ...
@dataclass class Outcome: ...
```

`maistro/memory/scopes.py`:

```python
def build_scope_filter(agent_id, user_id, team_id, org_id) -> list[tuple[str, str | None]]: ...
def matches_scope(mem: EpisodicMemory, filters) -> bool: ...
```

`build_scope_filter` always includes a `(GLOBAL, None)` entry so global
memories are visible regardless of caller scope. `matches_scope` enforces
that `TEAM`-scoped memories require both `team_id` and `org_id` to match
the caller, and that a `GLOBAL`-scoped memory carrying an `org_id` is
invisible to callers from a different org — this is the cross-tenant
leakage prevention mechanism.

`REGRET` and `WISDOM` weight floors (`0.6` and `0.9` respectively) are
intentionally high so these tiers are structurally resistant to decay —
regrets and hard-won wisdom should persist even without reinforcement.

## Acceptance criteria

- [x] `WEIGHT_BOUNDS[MemoryTier.REGRET] == (0.6, 1.0)`
- [x] `WEIGHT_BOUNDS[MemoryTier.WISDOM] == (0.9, 1.0)`
- [x] `WEIGHT_BOUNDS[MemoryTier.OBSERVATION] == (0.1, 0.5)`
- [x] `build_scope_filter()` always includes a `(GLOBAL, None)` entry
- [x] `matches_scope()` — `TEAM` scope requires both `team_id` AND `org_id`
      to match
- [x] `matches_scope()` — `GLOBAL` memory with an `org_id` is blocked for
      different-org callers
- [x] `Learning` dataclass round-trips through field access

## Testing

| Test | Covers |
|---|---|
| `test_weight_bounds_regret` | floor ≥ 0.6 |
| `test_weight_bounds_wisdom` | floor ≥ 0.9 |
| `test_build_scope_filter_always_global` | global always present |
| `test_matches_scope_team_requires_org` | cross-tenant leakage prevention |
| `test_matches_scope_global_org_isolation` | different-org global blocked |
| `test_learning_dataclass_fields` | field defaults |

## Open questions

- Whether to add tier-specific decay deltas (deferred per ADR-013).
- Whether to add a CI lint for inline `0.05` literals outside
  `types/memory.py` (recommended, not yet implemented).

## References

- [ADR-002: Porting workflow](../adr/ADR-002-porting-workflow.md)
- [ADR-013: Memory types](../adr/ADR-013-memory-types.md)
- `packages/maistro-core/src/maistro/types/memory.py`
- `packages/maistro-core/src/maistro/memory/scopes.py`
