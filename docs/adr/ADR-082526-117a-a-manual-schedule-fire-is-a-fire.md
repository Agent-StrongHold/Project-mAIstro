---
id: ADR-082526-117a
title: "A manual schedule fire is a fire: it creates a Run, counts against the bound, and moves the cursor"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-25
accepted: 2026-08-25
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_scheduler.py
ac-modules:
  AC-1: packages/hive-conductor/backend/services/scheduler.py
  AC-2: packages/hive-conductor/backend/routes/schedules.py
history:
  - status: Proposed
    date: 2026-08-25
  - status: Accepted
    date: 2026-08-25
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-117a: A manual schedule fire is a fire: it creates a Run, counts against the bound, and moves the cursor

## Context

`POST /v1/schedules/{id}/run` — the "run now" button — did this and nothing else:

```python
schedule = schedule.model_copy(update={"last_run": t, "updated_at": t})
```

No Run was created, no cursor advanced, nothing counted. The schedule then
asserted it had fired with no `run_id` anywhere corresponding to it.

That is the same defect #231 named on the tick path and PR #250 removed there:
a receipt for work that never started. It survived because it lives on the
route rather than in the loop, so the fix to `_fire_schedule` never reached it.

It became more than cosmetic once `max_runs` was expressible (#265). A firing
that does not count is a firing outside the bound, and on a deployment with no
canonical `ScheduleStore` bridge — an explicitly supported degraded mode where
`_canonical_store()` returns `None` — the stamped `last_run` *is* the cursor,
so a manual run silently suppressed the next scheduled occurrence.

## Decision

A manual fire goes through the same path a tick uses. `services.scheduler.
fire_now` resolves the definition, creates the canonical Run via
`_fire_schedule`, and records the cursor via `_record_fire` — the same two
calls, in the same order, that `_evaluate_schedule` makes.

Three consequences follow, and all three are the point rather than side
effects:

1. **It creates a Run.** The stamp names the work behind it.
2. **It counts against `max_runs`.** A bound bounds every firing, not only the
   scheduled ones. An exhausted schedule refuses.
3. **It advances the cursor**, including `last_fired_at`.

A fire that cannot happen — no target, an unregistered template, an exhausted
bound — is refused as `409` rather than stamped anyway. The caller asked for
work to start; if it did not, the schedule must not claim otherwise.

## Consequences

### Positive
- The defect #231 removed from the tick path is removed from the route too,
  rather than left as the one surface that still writes an unbacked receipt.
- `max_runs` means what it says on every path that can fire.
- A refusal is visible to the caller, with the reason, instead of succeeding.

### Negative / Trade-offs
- **Advancing `last_fired_at` gives up backfill of occurrences owed from before
  now.** This is the real cost and it is not hypothetical: a manual run during
  a catch-up window discards the occurrences still owed in it. It is bounded by
  the catch-up window (an hour by default), and the next *scheduled* occurrence
  is unaffected because `next_fire_after(now)` is still that occurrence. The
  alternative — a manual fire that creates a Run but leaves the cursor alone —
  was rejected because it makes "run now" not count as having run, which is
  the ambiguity `last_run` already suffered from.
- `POST /{id}/run` is no longer infallible. A client that ignored its response
  now has a failure mode to handle. That is the honest shape of the operation.

### Neutral
- The endpoint became `async`, since the fire path is.
- On a deployment with no canonical store the behaviour is degraded but
  consistent with the tick path: the row's own fields carry the cursor.

## Acceptance criteria

- [x] **AC-1** A manual fire creates exactly one canonical Run, records it as
  the schedule's `last_run_id`, and counts against `max_runs`. An exhausted
  schedule, a targetless schedule, and one whose template cannot be resolved
  are all refused without moving the cursor or stamping `last_run`.
- [x] **AC-2** The route surfaces a refusal as `409` with the reason, and an
  unknown schedule as `404`. It never returns success for a fire that did not
  produce a Run.
