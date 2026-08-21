---
id: SPEC-227
title: "EpisodicMemory: 7-tier weight clamping, reinforce/decay, and InMemoryEpisodicStore"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-20
substrate: []
implements:
  - maistro-engine#ADR-016
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-core/tests/memory/episodic/test_episodic.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-227: EpisodicMemory tiers, weight clamping, and store

## Context

ADR-016 decided to port a 7-tier episodic memory model (with weight floors/ceilings per
tier) and an in-memory store with keyword retrieval and scope-aware filtering. This is
implemented and tested in `maistro-core`; this SPEC documents the shipped shape.

## Goals

- Document the actual `EpisodicMemory` dataclass, the 7 `MemoryTier` values and their
  weight bounds, the `clamp_weight`/`reinforce`/`decay` functions, and
  `InMemoryEpisodicStore`'s `store`/`retrieve`/`reinforce` methods.
- Provide a traceable mapping from ADR-016 acceptance criteria to real tests.

## Non-goals

- Persistence backends other than the in-memory store (PostgreSQL episodic persistence,
  if/when it exists, is a separate SPEC).
- Cross-org sharing policy beyond the existing team-requires-org-match check.

## Decision

Implementation lives in `packages/maistro-core/src/maistro/memory/episodic/`:

- `store.py` — `InMemoryEpisodicStore` with:
  - `async store(self, memory: EpisodicMemory) -> str`
  - `async retrieve(self, query: str, *, agent_id=None, user_id=None, team_id=None, org_id=None, limit: int = 5) -> list[EpisodicMemory]`
  - `async reinforce(self, memory_id: str, delta: float = 0.05) -> None`
- `tiers.py`:
  - `clamp_weight(tier: MemoryTier, proposed: float) -> float`
  - `reinforce(memory: EpisodicMemory, delta: float = REINFORCE_DELTA) -> EpisodicMemory`
  - `decay(memory: EpisodicMemory, delta: float = REINFORCE_DELTA) -> EpisodicMemory`
- `retrieval.py` — keyword/word-overlap scoring used by `retrieve()`.

Canonical types live in `packages/maistro-core/src/maistro/types/memory.py`
(`packages/maistro-core/src/maistro/memory/types.py` is a re-export shim, no duplicate
logic). `EpisodicMemory` fields: `memory_id`, `tier: MemoryTier`, `content`,
`weight: float = 0.3`, `org_id`, `team_id`, `agent_id`, `user_id`,
`scope: MemoryScope`, `source`, `context: dict[str, str]`, `reinforcement_count: int`,
`contradiction_count: int`, `created_at`, `last_accessed_at`, `deleted: bool = False`.

The 7 tiers and weight bounds (`types/memory.py:16-36`):

| Tier | Floor | Ceiling |
|---|---|---|
| OBSERVATION | 0.1 | 0.5 |
| HYPOTHESIS | 0.2 | 0.6 |
| OPINION | 0.3 | 0.8 |
| LESSON | 0.5 | 0.9 |
| REGRET | 0.6 | 1.0 |
| AFFIRMATION | 0.6 | 1.0 |
| WISDOM | 0.9 | 1.0 |

`retrieve()` enforces scope: a `team_id`-scoped query requires `org_id` to match,
blocking cross-org leakage; deleted memories (`deleted=True`) are excluded from results.

Note: `EpisodicMemory` and `retrieve()` carry/filter on `org_id`, which appears to
predate ADR-068's clarification (CLAUDE.md design decision #7) that *soft* scope axes
(including `org`) are allowed in core — only *hard* tenancy is Stronghold-only. The
package-level `maistro-core/CLAUDE.md` "no org_id in core" phrasing is stale relative to
this and should be reconciled separately; it is not a defect in this implementation.

## Acceptance criteria

- [x] `clamp_weight(REGRET, 0.0)` returns 0.6 (floor enforced)
- [x] `clamp_weight(WISDOM, 0.5)` returns 0.9 (floor enforced)
- [x] `clamp_weight(OBSERVATION, 0.8)` returns 0.5 (ceiling enforced)
- [x] `reinforce()` returns new `EpisodicMemory` with weight increased, clamped
- [x] `decay()` returns new `EpisodicMemory` with weight decreased, clamped to floor
- [x] `store()` + `retrieve()` returns matching memories by keyword
- [x] `retrieve()` blocks cross-org memory leakage (team scope requires org match)
- [x] `retrieve()` scores by weight x word-overlap
- [x] `reinforce()` (store method) updates the stored memory weight
- [x] Deleted memories are excluded from retrieval

## Testing

`packages/maistro-core/tests/memory/episodic/test_episodic.py`:
`test_regret_floor_enforced`, `test_wisdom_floor_enforced`,
`test_observation_ceiling_enforced`, `test_within_bounds_unchanged`,
`test_all_tiers_clampable`, `test_reinforce_increases_weight`,
`test_reinforce_increments_count`, `test_reinforce_respects_ceiling`,
`test_decay_decreases_weight`, `test_decay_to_floor_for_regret`,
`test_decay_increments_contradiction_count`, `test_reinforce_returns_new_object`,
`test_store_and_retrieve`, `test_retrieve_no_match_returns_empty`,
`test_retrieve_excludes_deleted`, `test_retrieve_team_scope_requires_org`,
`test_retrieve_team_correct_org`, `test_reinforce_updates_weight`.

## Open questions

- Should `maistro-core/CLAUDE.md`'s "no org_id" language be updated to match ADR-068's
  soft-scope-axes clarification, given `EpisodicMemory` already carries `org_id`?
- A duplicate test file exists at `/home/user/maistro-engine/tests/memory/episodic/test_episodic.py`
  outside the package tree; worth deduplicating in a follow-up.

## References

- `packages/maistro-core/src/maistro/memory/episodic/store.py`
- `packages/maistro-core/src/maistro/memory/episodic/tiers.py`
- `packages/maistro-core/src/maistro/memory/episodic/retrieval.py`
- `packages/maistro-core/src/maistro/types/memory.py`
- `packages/maistro-core/tests/memory/episodic/test_episodic.py`
