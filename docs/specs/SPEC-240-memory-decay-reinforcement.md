---
id: SPEC-240
title: "Memory decay + reinforcement dynamics (ADR-080 part A)"
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
  - maistro-engine#SPEC-241
  - maistro-engine#SPEC-242
  - maistro-engine#SPEC-243
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/memory/episodic/test_decay.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-240: Memory decay + reinforcement dynamics

## Context

ADR-080 part (A) specifies that episodic memories weight-decay over time unless refreshed by
access, that feedback steers both weight and decay rate, and that cumulative feedback can promote
a memory to WISDOM or demote it to REGRET. Today `maistro.memory.episodic.tiers` only has
flat-delta `reinforce()`/`decay()` helpers (`packages/maistro-core/src/maistro/memory/episodic/tiers.py`)
called explicitly by callers — there is no time-based decay, no access-refresh, no per-memory decay
rate, and no tier-reclassification function. `EpisodicMemory`
(`packages/maistro-core/src/maistro/types/memory.py`) has no `decay_timer`/`decay_rate` fields.

This SPEC scopes the narrowest of ADR-080's four pieces — decay + reinforcement — to ship first,
since the tier/weight-bound primitives it builds on already exist and are tested.

## Goals

- Add `decay_timer: datetime` and `decay_rate: float` fields to `EpisodicMemory`.
- `on_access(memory) -> EpisodicMemory`: refresh `decay_timer` to now.
- `on_feedback(memory, signal: Literal["up", "down"]) -> EpisodicMemory`: boost weight + slow decay
  rate on "up"; drop weight + speed decay rate on "down" (clamped to tier bounds via the existing
  `clamp_weight`).
- `reclassify(memory) -> MemoryTier`: cumulative positive feedback (`reinforcement_count`) promotes
  to WISDOM past a threshold; cumulative negative feedback (`contradiction_count`) demotes to
  REGRET past a threshold. Threshold constants live alongside `REINFORCE_DELTA`/`CONTRADICT_DELTA`
  in `maistro/types/memory.py`.
- `tick_decay(memory, *, now) -> EpisodicMemory`: apply time-based weight decay scaled by
  `decay_rate` and elapsed time since `decay_timer`, clamped to tier floor — this is the "memory
  must forget" mechanism; WISDOM/REGRET floors (0.9/0.6) are already structurally enforced by
  `clamp_weight` + `WEIGHT_BOUNDS`, so no separate floor logic is needed here.

## Non-goals

- The consolidation engine (merge/contradiction-review) — ADR-080 part (B), tracked in SPEC-241.
- Cross-scope sharing + consent gating — ADR-080 part (C), tracked in SPEC-242.
- Hybrid BM25+vector retrieval ranking — ADR-080 part (D), tracked in SPEC-243.
- A scheduler/cron that calls `tick_decay` on a cadence — this SPEC ships the pure functions;
  wiring a periodic caller is a follow-up once a scheduler subsystem exists (ADR-046).
- Tuning the actual decay-rate/boost/drop constants beyond reasonable defaults — ADR-080 already
  marks concrete curve constants as out of scope, follow-up tuning SPEC.

## Decision

All functions are pure (return a new `EpisodicMemory`, matching the existing `reinforce()`/`decay()`
style in `tiers.py`) — no store/IO coupling, so `memory/episodic/store.py` callers decide when to
persist.

```python
# maistro/types/memory.py — new fields + constants
DEFAULT_DECAY_RATE: float = 0.01          # weight lost per hour at rate=1.0
BOOST_RATE: float = 1.5                    # weight multiplier on thumbs-up
DROP_RATE: float = 0.5                     # weight multiplier on thumbs-down
SLOW_DECAY: float = 0.5                    # decay_rate multiplier on thumbs-up
FAST_DECAY: float = 2.0                    # decay_rate multiplier on thumbs-down
WISDOM_PROMOTE_THRESHOLD: int = 5          # reinforcement_count to promote -> WISDOM
REGRET_DEMOTE_THRESHOLD: int = 5           # contradiction_count to demote -> REGRET

# EpisodicMemory gains:
#   decay_rate: float = DEFAULT_DECAY_RATE
#   (decay_timer reuses existing last_accessed_at — no new field needed)
```

```python
# maistro/memory/episodic/tiers.py — new functions

def on_access(memory: EpisodicMemory, *, now: datetime | None = None) -> EpisodicMemory: ...

def on_feedback(memory: EpisodicMemory, signal: Literal["up", "down"]) -> EpisodicMemory: ...

def reclassify(memory: EpisodicMemory) -> MemoryTier: ...

def tick_decay(memory: EpisodicMemory, *, now: datetime | None = None) -> EpisodicMemory: ...
```

`on_feedback` composes `reinforce`/`decay` (for the weight step) with a `decay_rate` adjustment, then
calls `reclassify` and returns a copy with `tier` updated if it changed.

## Acceptance criteria

- [x] `on_access` updates `last_accessed_at` to `now` and leaves weight/tier unchanged.
- [x] `on_feedback(m, "up")` increases weight (clamped to tier ceiling) and decreases `decay_rate`.
- [x] `on_feedback(m, "down")` decreases weight (clamped to tier floor) and increases `decay_rate`.
- [x] `reclassify` returns WISDOM once `reinforcement_count >= WISDOM_PROMOTE_THRESHOLD`, REGRET once
      `contradiction_count >= REGRET_DEMOTE_THRESHOLD`, else the memory's current tier.
- [x] `tick_decay` reduces weight proportionally to `decay_rate * elapsed_hours`, never below the
      tier floor (REGRET >= 0.6, WISDOM >= 0.9, per existing `WEIGHT_BOUNDS`).
- [x] A memory promoted to WISDOM or demoted to REGRET keeps that tier's floor on subsequent
      `tick_decay` calls (no regression below floor even after many decay ticks).

## Testing

- `packages/maistro-core/tests/memory/episodic/test_decay.py` (new) — unit tests for `on_access`,
  `on_feedback` (both signals), `reclassify` (both promotion and demotion thresholds), `tick_decay`
  (decay over elapsed time, floor enforcement at WISDOM/REGRET).
- Existing `packages/maistro-core/tests/` coverage for `clamp_weight`/`reinforce`/`decay` continues
  to pass unmodified — this SPEC adds functions, it does not change the existing ones.

## Open questions

- Whether `decay_rate` should itself decay back toward `DEFAULT_DECAY_RATE` over time after a
  feedback spike, or stay permanently adjusted — left as permanently adjusted for this SPEC;
  revisit if memories oscillate unrealistically in practice.

## References

- `packages/maistro-core/src/maistro/memory/episodic/tiers.py`
- `packages/maistro-core/src/maistro/types/memory.py`
- [ADR-080: Memory Dynamics](../adr/ADR-080-memory-dynamics.md)
