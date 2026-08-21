---
id: SPEC-080126-3a7c
title: "Durable recurring-task scheduler — reconciling the shipped runner with ADR-046"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-08-01
substrate:
  - maistro-engine#ADR-018
  - maistro-engine#ADR-021
  - maistro-engine#ADR-046
implements:
  - maistro-engine#ADR-046
related:
  - maistro-engine#ADR-037
  - maistro-engine#ADR-086
  - maistro-engine#SPEC-240
  - maistro-engine#SPEC-241
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - boundary
tests:
  - packages/hive-conductor/backend/tests/test_scheduler.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-08-01
---

# SPEC-080126-3a7c: Durable recurring-task scheduler

## Context

[ADR-046](../adr/ADR-046-scheduler.md) (Accepted 2026-06-10) specifies a recurring-task
scheduler. A scheduler ships — `routes/schedules.py` mounted at `/v1/schedules`,
`services/scheduler.py`, and `maistro/scheduling/store.py` — but it is **not** the one
ADR-046 specifies, and the divergence was never recorded as a decision. All three files
arrived in commit `d1b85b14`, a coverage PR ("Phase 17 complete: maistro-core coverage
floor"), eighteen days after the ADR was accepted, citing nothing. See **#343**.

This SPEC closes that gap by specifying the work to bring the implementation to ADR-046,
per the governance rule that an implementation contradicting an ADR is either drift — fix
the code — or intentional, in which case a superseding ADR is required.

> **Contingent on the #343 decision.** This SPEC assumes the drift is resolved *toward*
> ADR-046. If the maintainer instead decides the smaller shipped scheduler is what the
> product wants, this SPEC is void and a superseding ADR replaces ADR-046 rather than this
> implementing it. Do not begin work here until #343 is answered.

## Problem

Six ADR-046 acceptance criteria, none met:

| ADR-046 requires | Shipped today |
|---|---|
| Postgres persistence via Alembic; re-register `enabled=true` schedules on restart | `_tasks: dict` — in-memory; **schedules vanish on restart** |
| Single APScheduler `AsyncIOScheduler` | hand-rolled cron matcher on a 30 s asyncio loop; no APScheduler dependency |
| `max_runs` enforced, auto-disable after Nth fire | absent — uncapped `run_count` only |
| `maistro_schedule_fires_total{schedule_id, outcome}` | absent |
| OTel span `schedule.fire` parenting `task.run` | absent (an audit log `schedule_fire` exists, which is not a span) |
| `profile_id`, `cron`, `timezone`, `task_template`, `runs_so_far`, `last_task_id`, `last_fired_at` | `user_id`, `schedule`, `prompt`, `agent`, `delivery`, `run_count`, `last_run_at` |

The user-visible consequence is the first row: a person who creates *"every weekday at 7am,
run the morning briefing"* gets something that silently stops existing at the next deploy,
with no error and no indication.

## Goals

- Schedules survive a restart, and `enabled=true` schedules re-register before the app
  accepts traffic.
- `max_runs` is enforced.
- Fires are observable as metrics and traces, not only as audit rows.
- The `/v1/schedules` surface keeps working across the migration — this is a live API.

## Non-goals

- Distributed/multi-instance scheduling (leader election, lock coordination). Single
  conductor process, as ADR-046 states.
- Sub-minute cadences.
- Backfill of missed fires while the process was down. **Explicitly out of scope** — decide
  and record the catch-up policy, but do not implement replay.

## Decision

### Migration, not replacement

The `/v1/schedules` routes are live. The existing store is swapped behind the router rather
than the surface being rebuilt, so the endpoint contract is unchanged for callers.

### Field reconciliation

The shipped model and ADR-046's disagree on names and content. Reconciling means choosing
per field, not renaming wholesale — `prompt`/`agent`/`delivery` carry real behavior the ADR's
`task_template: dict` would subsume. The SPEC's implementer must produce a field-by-field
mapping table and get it reviewed **before** writing the migration, because this is the
irreversible part: a migration that drops `delivery` silently breaks every existing schedule.

### Persistence

Postgres via Alembic, per ADR-046, reusing the migration conventions already in
`maistro/persistence/`. The in-memory store remains the fallback when no database is
configured — consistent with how the rest of the tree degrades — but that fallback must be
**loud** (see ADR-073126 / F3 precedent: a degraded mode that looks like success is the
defect, not the degradation).

### Scheduling mechanism

ADR-046 names APScheduler. The shipped hand-rolled matcher is a real deviation, but a
*defensible* one — it avoids a dependency. The implementer must either adopt APScheduler as
the ADR states, or, if keeping the hand-rolled matcher, **that becomes an intentional
deviation requiring a superseding ADR** rather than a silent choice. It cannot stay
undocumented a second time.

## Acceptance criteria

- [ ] A schedule created before a restart still exists, is still `enabled`, and fires on its
      next cron tick after the process comes back.
- [ ] `max_runs` auto-disables the schedule after the Nth fire; `runs_so_far` is accurate.
- [ ] Pause stops fires within one cycle; resume restarts on the next tick.
- [ ] `maistro_schedule_fires_total{schedule_id, outcome}` increments per fire, both outcomes.
- [ ] An OTel span `schedule.fire` parents the resulting task span.
- [ ] Every existing `/v1/schedules` test passes unchanged, or its change is justified as a
      correction rather than an accommodation.
- [ ] A schedule created under the old store is readable after migration (or the migration
      explicitly and loudly discards them, documented in `KNOWN-GAPS.md`).
- [ ] The catch-up policy for fires missed while down is documented, even though replay is
      out of scope.

## Testing

- Unit: cron matching, `max_runs` boundary (N-1, N, N+1), pause/resume.
- Integration: create → restart the app → confirm re-registration and next fire. **This is
  the test that pins the actual defect** and must not be simulated by calling the
  re-register function directly; it has to survive a real process boundary.
- Migration: fixture DB at the old schema → migrate → schedules intact.
- Negative: invalid cron rejected at `POST`, not at fire time.

## References

- [ADR-046: Scheduler — Recurring agent tasks](../adr/ADR-046-scheduler.md)
- #343 — the drift record this SPEC responds to
- #344 — memory decay, one of the consumers blocked behind a scheduler
- [SPEC-240](SPEC-240-memory-decay-reinforcement.md), [SPEC-241](SPEC-241-memory-consolidation.md)
  — both defer periodic work to ADR-046
