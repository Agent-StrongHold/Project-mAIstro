---
id: ADR-082126-f69c
title: "Recurrence produces Runs: schedules are definitions, not a second runtime"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-08-21
created: 2026-08-21
substrate:
  - maistro-engine#ADR-081226-a66b
  - maistro-engine#ADR-081426-1f7c
implements: []
related:
  - maistro-engine#ADR-037
  - maistro-engine#ADR-038
  - maistro-engine#ADR-056
  - maistro-engine#ADR-062
supersedes:
  - maistro-engine#ADR-046
blocks: []
blocked-by: []
contracts:
  - behavioral
  - boundary
tests:
  - packages/maistro-core/tests/scheduling/test_cron.py
  - packages/maistro-core/tests/scheduling/test_engine.py
  - packages/maistro-core/tests/scheduling/test_enumeration_limits.py
  - packages/maistro-core/tests/scheduling/test_admission.py
  - packages/maistro-core/tests/scheduling/test_store.py
  - packages/hive-conductor/backend/tests/test_scheduler.py
  - packages/hive-conductor/backend/tests/test_schedule_frequency_floor.py
  - packages/hive-conductor/backend/tests/test_scheduler_bounded_tick.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-08-21
  - status: Accepted
    date: 2026-08-21
---

# ADR-082126-f69c: Recurrence produces Runs

**Status:** Accepted
**Date:** 2026-08-21
**Supersedes:** [ADR-046](ADR-046-scheduler.md)

## Context

[ADR-046](ADR-046-scheduler.md) was accepted on 2026-06-10 and specified a
recurring-task scheduler: Postgres persistence via Alembic, a single
APScheduler `AsyncIOScheduler`, `max_runs` auto-disable, a fires counter, an
OTel span `schedule.fire` parenting `task.run`, and a field set built around
`task_template` and `last_task_id`.

Eighteen days later a scheduler shipped inside an unrelated coverage PR,
citing nothing, and diverged from that specification on every point: an
in-memory dict, a hand-rolled cron matcher on a thirty-second loop, no
`max_runs`, no metric, no span. That drift is issue #343, and
[SPEC-080126-3a7c](../specs/SPEC-080126-3a7c-durable-scheduler.md) was written
to close it by implementing ADR-046 — then blocked itself pending the #343
decision, because implementing an ADR is only correct if the ADR is still
right.

**This ADR answers #343, and answers it toward neither of them**, because the
ground moved between June and now. The canonical execution spine —
Run/NodeRun/Attempt with execution leases, traversal checkpoints, crash
recovery and orphaned-Attempt reconciliation — landed *after* ADR-046 was
accepted. ADR-046 is a well-engineered scheduler for a codebase that has no
durable execution engine. This codebase now has one, and that changes the
answer rather than merely delaying it.

## Decision

### 1. A Schedule is a definition; firing produces a Run

A `Schedule` is a recurrence rule plus a pointer to a `GraphTemplate` and its
inputs, filed in a Project. It owns no execution concept. Firing instantiates
the template and starts a canonical Run, exactly as every other work producer
does.

The consequences are the point:

- Scheduled work is the same durable, resumable, auditable object as
  interactive work. One execution identity, one recovery model, one place to
  look when something did not happen.
- "Did we miss a fire?" is answered from Run history in the scope, not from a
  separate job store's misfire table.
- Long-running and human-in-the-loop agent work — a recurring research Run
  that pauses for approval and resumes hours later — needs no scheduler-side
  support at all, because the Run already does that.

Concretely, this rejects ADR-046's `task_template` and `last_task_id`. Those
bind recurrence to the Task lifecycle, which is itself a parallel island the
convergence program is dissolving; a durable schema is the most expensive
place to encode the wrong execution noun. The pointer is `graph_template_id`;
the back-reference is `last_run_id`.

### 2. No second execution runtime

**APScheduler is rejected.** Not on dependency grounds — on the grounds that
APScheduler with a persistent job store *is a second durable execution
engine*: its own store, its own recovery-on-startup, its own misfire grace and
coalescing, its own opinion about what is currently running. Placing that
beside a spine that already answers those questions produces two answers to
"what happened while the process was down", which will disagree, and the
disagreement will be discovered in production.

That is a direct violation of the convergence exit criterion that no
specialized package may create another universal runtime.

What replaces it is smaller: schedules carry a `next_due_at`, and the loop
polls an index for what is due. Both this ADR and ADR-046 rule out sub-minute
cadence, so APScheduler's in-memory timer precision buys nothing while costing
a second state machine. The poll is the better engineering choice here, not
merely the cheaper one.

The unused `scheduling` extra that anticipated this dependency is removed.

### 3. One cron dialect, and it is verified

Two hand-rolled matchers existed and disagreed with each other and with POSIX.
Both bugs were user-visible:

- Day-of-week was indexed by Python's `date.weekday()` (Monday=0) against a
  cron field that is Sunday=0, so `0 9 * * 0` — "9am Sunday" to anyone who has
  written cron — fired **Monday**.
- Day-of-month and day-of-week were ANDed. POSIX **ORs** them when both are
  restricted, so `0 0 1 * 1` meant "the 1st, and only when it is a Monday" —
  roughly once every seven months instead of about five times a month.
- Meanwhile the other implementation validated a day-of-week range of 0–7,
  accepting expressions the matcher could never fire.

`maistro.scheduling.cron` is the single dialect: POSIX semantics including the
OR rule and Sunday=0, three-letter names, ranges, lists and steps. Its
next-fire search advances a whole month, day or hour when a coarse field
cannot match — which is what makes it fast and what could make it skip a fire
— so it is checked against a brute-force minute-by-minute oracle under
Hypothesis. The parser is verified, not merely reviewed.

A cron *library* would have been a defensible alternative; a cron *runtime*
was not. The verification above is what makes writing it the better trade.

### 4. Recurrence is evaluated in wall time, with explicit DST rules

Schedules carry an IANA timezone and are evaluated in wall time, so "07:00
every weekday" stays 07:00 across a transition instead of drifting an hour.
Two cases need a stated answer rather than an accident:

- A wall time that **does not exist** (spring-forward gap) is **skipped**. The
  schedule fires at its next valid occurrence rather than silently at a time
  nobody asked for.
- A wall time that occurs **twice** (fall-back) fires **once**, on the first
  occurrence.

### 5. Overlap and catchup are first-class

Neither predecessor specified these, and for agent work they are not edge
cases: a twenty-minute research Run on a fifteen-minute schedule meets the
overlap question every cycle, and any deploy meets the catchup question.

- **Overlap policy**, per schedule: `skip` (default), `allow`,
  `cancel_other`, `buffer_one`.
- **Catchup window**, per schedule, defaulting to one hour: occurrences missed
  inside the window are backfilled and marked as catchup; occurrences older
  than it are deliberately dropped, because replaying a day of missed fires is
  a stampede, not a recovery.
- **Bounded recurrence**: `max_runs` with `runs_so_far`, auto-disabling on
  exhaustion. Kept from ADR-046.

These are pure functions of (schedule, now, whether a Run is in flight), so
they are asserted directly instead of being emergent behaviour of a polling
loop. A property holds that every occurrence which came due is either fired or
carries a reason it was not — nothing vanishes silently.

### 6. Durability behind a protocol

Schedules persist. The store is a protocol with an in-memory implementation
for tests and a **SQLite** implementation for the single-conductor deployment
ADR-046 targeted; a Postgres implementation satisfies the same protocol where
a server already exists. Requiring Postgres for a homelab conductor was
heavier than the problem.

There is deliberately no schedule-side execution table. A fire advances a
cursor on the schedule (`last_fired_at`, `last_run_id`, `runs_so_far`) and the
execution lives in Run history, so this store never becomes a second place
that believes it knows what is running.

### 7. Rate floors are product policy

The substrate measures; the product decides. `minimum_gap()` computes the
shortest interval an expression can produce from real consecutive fire times —
so list, range and step forms are measured correctly, where the previous guard
estimated from the minute and hour fields alone and let `0,5,10 * * * *`
through. The 15-minute floor is applied by the product that wants it.

### 8. Catch-up work is bounded, and a stopped walk says so (#1200)

The audit behind #1200 measured one evaluation of a stale per-minute schedule
taking ~0.64s of synchronous event-loop time — 50,000 cron reparses in a
single catch-up walk — long enough to stall unrelated work sharing the loop.
Three bounds close that, all host-selected via
`engine.EnumerationLimits`, and the shipped host (the core Container wiring
the live scheduler) uses their safe defaults:

- **Window.** A definition may not file a `catchup_window_seconds` above
  `model.MAX_CATCHUP_WINDOW_SECONDS` (seven days) — before the cap, the walk
  grew with whatever window the definition asked for. A host may clamp
  further at evaluation time; the clamp is reported as `window_clamped` on
  the evaluation and admission, and the live tick logs it.
- **Occurrences.** The walk stops at a derived step bound (window ÷ 60 + a
  tick's slack — cron's finest cadence is one fire per minute, so the window
  implies the step count; no unexplained constant). Occurrences beyond the
  per-evaluation fire cap keep the existing `TRUNCATED` semantics: reported,
  and the cursor stays on them.
- **Time.** The walk reads the monotonic clock on a fixed stride and stops at
  its budget (default 0.1s), so an evaluation's event-loop cost is a stated
  property, not an accident of backlog size. `evaluate` is a pure function
  of its arguments, so a latency-critical host may also offload it to a
  worker thread.

A walk stopped by the budget or step bound is never silent and never
dishonest: the evaluation carries `enumeration_incomplete` and where it
stopped, the unexamined range is *not* reported as skipped occurrences (they
were never enumerated), and admission treats an incomplete walk like a
buffered occurrence — the due cursor stays put, so the next tick re-examines
exactly the range this one did not. The live tick logs an incomplete walk as
backlog owed.

On top of the substrate's measurement, the shipped Hive product enforces the
frequency floor this ADR anticipated: `/v1/schedules` create and every
recurrence-touching update refuse a cron whose `minimum_gap` is below the
operator's `schedule_min_frequency_gap_s` (default 900s). The floor and the
product's own catch-up window cap (`schedule_max_catchup_window_s`, default
one day) are configurable only within safe startup bounds (floor 300s–7d,
cap 1h–7d); out-of-range configuration fails at startup rather than clamping,
and ordinary clients cannot request an effectively busy-loop schedule at any
setting.

## Consequences

- Scheduled work becomes visible to every tool that understands Runs, and
  needs no scheduler-specific observability to be debuggable or billable.
- Schedules *can* survive a restart: the durable store exists and both
  implementations are held to the same tests. The failure is not yet closed
  end to end, because Hive's `/v1/schedules` routes still write the in-memory
  `stores.schedules`. That migration is the remaining step and is tracked in
  `KNOWN-GAPS.md` rather than claimed here.
- Two reachability islands (`maistro.scheduling`, `maistro.scheduling.store`)
  join the spine.
- The `/v1/schedules` HTTP contract is unchanged; only the semantics moved.
- Hive's schedule rows carry no timezone column yet, so recurrence there is
  evaluated in UTC until one is added. The definition already supports it.
- A schedule row naming no target is skipped rather than "fired" into nothing.

## What this keeps from ADR-046

Durable persistence, `max_runs` with auto-disable, timezone as a first-class
field, and observability of fires. ADR-046 was right that all four were
missing; it was overtaken on *how* to provide them.

## Implementation status (2026-08-21)

| Element | State |
|---|---|
| POSIX cron with tz + verified next-fire | Shipped (`maistro/scheduling/cron.py`) |
| Schedule definition pointing at a GraphTemplate | Shipped (`model.py`) |
| Overlap / catchup / bounded recurrence | Shipped (`engine.py`) |
| Bounded catch-up work + truthful incompleteness (#1200) | Shipped (`engine.py` `EnumerationLimits`, `admission.py`) — window ≤ 7d at definition time, host-selected window/step/budget bounds, an incomplete walk holds the due cursor and is logged by the live tick |
| Product frequency floor + catch-up window cap (#1200) | Shipped (`routes/schedules.py`, `config.py`) — `schedule_min_frequency_gap_s` (default 900s) refused below at create/update, `schedule_max_catchup_window_s` (default 1d), both bounded 300s–7d / 1h–7d at startup |
| Store protocol + in-memory + SQLite | Shipped (`store.py`) |
| Hive `/v1/schedules` rows on the durable store | **Not yet** — the routes still write `stores.schedules`, which is in memory, so schedules created through the live API still do not survive a restart. The durable store exists and is tested; migrating the CRUD path behind the unchanged HTTP contract is the next step |
| Hive runner evaluating through the engine | Shipped (`services/scheduler.py`) |
| Fires produce canonical Runs | Shipped — via `services/dag_agents.py` |
| Postgres store implementation | **Not yet** — the protocol is the seam |
| Hive `/v1/schedules` timezone column | **Not yet** — UTC until added |
| `maistro_schedule_fires_total` + `schedule.fire` span | **Not yet** — declared by ADR-037's registry contract; the Run correlation exists in the audit trail today |

## References

- [ADR-046: Scheduler — recurring agent tasks](ADR-046-scheduler.md) — superseded by this decision
- [SPEC-080126-3a7c](../specs/SPEC-080126-3a7c-durable-scheduler.md) — the implement-ADR-046 plan this supersedes
- [ADR-081226-a66b: Run/NodeRun/Attempt lifecycle](ADR-081226-a66b-run-noderun-attempt-lifecycle.md) — the execution identity a fire produces
- [ADR-081426-1f7c: ExecutionRuntime contract](ADR-081426-1f7c-execution-runtime-contract.md)
- [ADR-037: Observability taxonomy](ADR-037-observability-taxonomy.md) — owns the metric/span naming contract
- #343 — the drift record this ADR answers
