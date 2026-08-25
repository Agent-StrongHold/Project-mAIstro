---
id: SPEC-080126-9e42
title: "Periodic memory-decay driver — making 'memory must forget' true at runtime"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-08-01
substrate:
  - maistro-engine#ADR-046
  - maistro-engine#ADR-080
implements:
  - maistro-engine#ADR-080
related:
  - maistro-engine#SPEC-240
  - maistro-engine#SPEC-241
  - maistro-engine#ADR-037
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/memory/episodic/test_decay_driver.py
  - packages/hive-conductor/backend/tests/test_memory_decay.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-08-01
  - status: Implemented
    date: 2026-08-01
  - status: Accepted
    date: 2026-08-25
    reason: "M0 strict evidence reconciliation: current acceptance evidence does not support an Implemented completion claim; implementation history remains recorded."

---

# SPEC-080126-9e42: Periodic memory-decay driver

## Context

`README.md:95` tells users the memory subsystem *"decays without reinforcement."*
`CLAUDE.md:180` lists **"Memory must forget"** as key design decision #5.

Neither is true at runtime. `packages/maistro-core/src/maistro/memory/episodic/tiers.py`
defines `decay()` (`:44`) and `tick_decay()` (`:84`), both correct and tested — and **neither
has a single production caller**. Only the test suite invokes them. In a running system,
memory never decays. See **#344**.

[SPEC-240](SPEC-240-memory-decay-reinforcement.md) is not at fault and its `Implemented`
status is correct: it explicitly declared the periodic caller a Non-goal (`:65-66`), shipping
the pure functions it promised and deferring the driver *"once a scheduler subsystem exists
(ADR-046)."* The follow-up simply never happened, and no artifact tracked it — which is how a
documented product behavior came to silently not exist.

## Problem

The decay primitives are inert. Consequences:

- The README makes a claim the product does not deliver — a truth-in-advertising defect
  (workstream D), not merely a missing feature.
- Episodic memory grows without bound in weight terms; nothing reclaims salience from stale
  entries, so retrieval ranking drifts toward whatever was written most, forever.
- The weight floors for wisdom/regrets that decision #5 promises are never exercised, so
  their behavior under real decay is unverified in production conditions.

## Goals

- `tick_decay` runs on a cadence in a deployed system.
- The cadence is configurable and can be disabled.
- Decay activity is observable — an operator can answer "did decay run, and what did it
  touch?"

## Non-goals

- Tuning decay-rate/boost/drop constants. ADR-080 puts curve constants out of scope and
  SPEC-240 defers tuning to a follow-up; this SPEC drives the existing curve, it does not
  reshape it.
- Decay for learnings/outcome stores. Episodic only, matching SPEC-240's scope.
- Backfilling decay for the period during which it never ran (see below).

## Decision

### Not blocked on the scheduler — dependency lifted

This SPEC originally declared `blocked-by: SPEC-080126-3a7c` (the durable scheduler), on the
reasoning that decay would live in the scheduler's store, which is in-memory and loses
records on restart (#343).

**That blocker was too strong and has been lifted.** It conflated two different things.
Decay is a *system-level cadence*, not a user-created schedule: nobody creates it, nobody
edits it, and nothing is lost if no record of it survives a restart. It does not need a
durable schedule row — it needs a periodic tick that starts on boot. A background task
started from the app lifespan has exactly that lifetime: it restarts with the process, which
is all the durability a system cadence requires.

So this is **not** built on `/v1/schedules` or `maistro/scheduling/store.py`. It follows the
shape already established by `packages/hive-conductor/backend/services/scheduler.py` —
a module-level singleton started from `main.py`'s lifespan and stopped on shutdown.
SPEC-080126-3a7c remains worth doing for *user-created* schedules, where losing the record
genuinely is data loss; it is simply not a prerequisite for this.

### First-run hazard: not applicable under this deployment model

An earlier draft treated the first tick as the dangerous part: decay has never run, so on a
store carrying months of history the first sweep would bill all of that accrued time at once
and flatten episodic salience in a single pass. That concern was real in the abstract and
**does not apply here**, for two independent reasons:

1. **Deployment model.** This is an MVP with a single user (the maintainer) and a fresh
   install every time. There is no upgrade path carrying old data forward, so there are no
   entries with stale timestamps for a first tick to punish.
2. **There is no durable episodic store.** `InMemoryEpisodicStore` is the only
   implementation of the episodic protocol and `container.py` wires it unconditionally, in
   the SQLite branch as well. Episodic entries cannot outlive the process, so
   `last_accessed_at` can never predate process start — the accrued gap a tick can bill for
   is bounded by uptime, and the driver ticks hourly from boot.

No first-run mitigation is therefore implemented: no per-tick clamp, no timestamp rebase, no
staged rollout. Dormant mitigation code for a scenario that cannot occur would later read as
a real safeguard, which is worse than not having one.

**Revisit this if reason 2 stops holding.** A durable (SQLite/Postgres) episodic store would
reintroduce the hazard directly, and that is the trigger to reopen this section rather than
assume it stays moot.

### Loud when disabled

Following the F3 precedent (#302): if decay is configured off, that is a degraded mode and
must be visible, not a silent no-op that looks identical to today's bug.

## What shipped

- `maistro/memory/episodic/decay_driver.py` — `EpisodicDecayDriver`: cadence loop,
  `run_once()`, `start()`/`stop()`, and `status()` for health reporting.
- `EpisodicStore.apply_decay()` (new `DecayableEpisodicStore` protocol) — sweeps every live
  entry through the existing `tick_decay` and returns a `DecaySweep`
  (`scanned` / `decayed` / `at_floor`).
- `hive-conductor` `services/memory_decay.py`, started and stopped from `main.py`'s lifespan
  alongside `start_scheduler()`.
- `MEMORY_DECAY_INTERVAL_S` (default 3600, `<=0` disables). Disabled is loud: a startup
  warning naming the knob, plus `degraded: true` and `memory_decay.state: "disabled"` on
  `/health`, matching the `ALLOW_STUB_LLM` precedent.
- Observability via the surrounding logging convention (`episodic_decay_tick scanned=… 
  decayed=… at_floor=…`). No ADR-037 metric names were invented — per SPEC-228 none of them
  exist yet.

## Acceptance criteria

- [x] With the driver enabled, `tick_decay` demonstrably runs on its cadence against a real
      store, and affected entries' weights change.
- [x] Weight floors for wisdom/regrets hold across repeated ticks — an entry at the floor
      does not decay below it no matter how many cycles run.
- [x] Reinforcement between ticks measurably offsets decay (the "without reinforcement"
      qualifier in the README is load-bearing and must be true).
- [x] The cadence is configurable and can be disabled; disabling is surfaced as degraded,
      not silent.
- [x] Decay activity is observable — at minimum a count of entries touched per tick.
- [x] `README.md:95` and `CLAUDE.md:180` are true once this ships. **If this SPEC does not
      ship for v1, those lines must be corrected instead** and a `KNOWN-GAPS.md` entry added
      — the claim cannot stand unbacked either way.

## Testing

- Unit: floors hold across N ticks; reinforcement offsets decay; disabled driver performs no
  mutation.
- Integration: driver started → cadence fires → store reflects decayed weights. Must exercise
  the real scheduling path, not call `tick_decay` directly — calling it directly is what the
  existing tests already do, and it is exactly the coverage that let this gap survive.
- No migration/first-run test: see "First-run hazard" above. There is no stale-timestamp
  scenario to characterise under this deployment model.

## References

- #344 — the gap this SPEC closes
- #343 — the scheduler drift that kept it invisible
- [SPEC-240](SPEC-240-memory-decay-reinforcement.md) — ships the primitives; this drives them
- [SPEC-080126-3a7c](SPEC-080126-3a7c-durable-scheduler.md) — formerly the blocking
  dependency; no longer a prerequisite (see "Not blocked on the scheduler" above)
