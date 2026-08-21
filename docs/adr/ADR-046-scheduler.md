---
id: ADR-046
title: Scheduler — Recurring agent tasks
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-13
substrate:
  - maistro-engine#ADR-018
  - maistro-engine#ADR-021
implements: []
related:
  - maistro-engine#ADR-047
  - maistro-engine#ADR-048
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-13
---

# ADR-046: Scheduler — Recurring agent tasks

**Implementation status (2026-08-01, #343):** this decision is **not implemented**, and a
*different* scheduler ships in its place. `routes/schedules.py` (`/v1/schedules`),
`services/scheduler.py`, and `maistro/scheduling/store.py` provide recurring tasks, but
diverge from this ADR on every material axis: an in-memory dict rather than Postgres +
Alembic (so **schedules do not survive a restart**), a hand-rolled cron matcher rather than
APScheduler, no `max_runs`, no `maistro_schedule_fires_total` counter, no `schedule.fire`
span, and a different field set. **None of the acceptance criteria below are met.**

This is unrecorded drift, not a superseded decision — the divergent implementation landed in
commit `d1b85b14` (a coverage PR) eighteen days after this ADR was accepted, citing nothing.
Per the governance rule that an implementation contradicting an ADR is either drift (fix the
code) or intentional (write a superseding ADR), the maintainer has decided to **keep this ADR
as the target** and correct the code post-v1. The status therefore stays `Accepted`; it is
deliberately not moved to `Deferred` or `Superseded`.

Tracking: [SPEC-080126-3a7c](../specs/SPEC-080126-3a7c-durable-scheduler.md); the restart-loss
behaviour is recorded in [KNOWN-GAPS.md](../../KNOWN-GAPS.md).

The empty `maistro/scheduler/` placeholder referenced in the Context below was removed in
D1/#289 — it was a husk, distinct from the real `maistro/scheduling/` package.

## Context

`src/maistro/scheduler/` (removed — see the implementation-status note above) existed as an empty package. Product repos (Project_mAIstro household automations, AgentTuring autonoetic-loop reflections) need recurring agent invocations — "every weekday at 7am, run the morning briefing", "every 15 min, poll the inbox". Today they would have to roll their own cron-runner per product, duplicating queue-submission, retry, and observability code that already lives in `TaskQueue` / `conductor.py`.

Hermes-desktop ships this as a first-class user feature: `src/renderer/src/screens/Schedules/Schedules.tsx` + `src/main/cronjobs.ts` give frequency presets (minutes / hourly / daily / weekly / custom cron), pause/resume/trigger-now, `last_status`, `last_error`, repeat counter, and per-job skill selection. The patterns transfer cleanly to a substrate API.

## Problem

No first-class "schedule a recurring agent task" primitive. Each product reinvents cron + retry + status surfacing.

## Solution sketch

A `Schedule` model + worker that re-submits to the existing `TaskQueue` on cron fire. Reuses `TaskResponse` for `last_run` / `last_error` surfacing — no new status taxonomy. Single APScheduler `AsyncIOScheduler` instance owned by the conductor process, schedules persisted in Postgres via Alembic migration.

Lifecycle:

1. `POST /v1/schedules` writes row, registers job with APScheduler.
2. On fire, worker constructs a `TaskCreate` from the schedule's `task_template` and submits to `TaskQueue`. Schedule row's `last_task_id` updated.
3. `last_status` / `last_error` derived from joining the resulting `TaskRecord` (no schedule-local status duplication).
4. Pause flips `enabled=false` and removes the APScheduler job; resume re-registers.
5. Trigger-now submits a one-off task without altering the schedule cadence.

## Data model (sketch)

```python
class Schedule(Base):
    id: UUID                         # primary key
    profile_id: str                  # tenant/profile scoping
    name: str                        # human label
    cron: str                        # standard 5-field cron, UTC
    timezone: str = "UTC"            # IANA tz, applied to cron
    task_template: dict              # frozen TaskCreate payload
    enabled: bool = True
    max_runs: int | None             # repeat counter cap; None = unlimited
    runs_so_far: int = 0
    last_task_id: UUID | None
    last_fired_at: datetime | None
    created_at: datetime
    updated_at: datetime
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/schedules` | Create schedule |
| `GET` | `/v1/schedules` | List (filterable by `profile_id`, `enabled`) |
| `GET` | `/v1/schedules/{id}` | Detail, includes `last_status` from joined `TaskRecord` |
| `PATCH` | `/v1/schedules/{id}` | Edit cron / template / enabled |
| `DELETE` | `/v1/schedules/{id}` | Remove |
| `POST` | `/v1/schedules/{id}/pause` | Convenience: set `enabled=false` |
| `POST` | `/v1/schedules/{id}/resume` | Convenience: set `enabled=true` |
| `POST` | `/v1/schedules/{id}/trigger` | One-off run, returns `task_id` |

## Acceptance criteria

- [ ] Creating a schedule with cron `*/5 * * * *` produces a `TaskRecord` every 5 min for at least 3 cycles in a 20-min integration test.
- [ ] Pause stops fires within one cycle; resume restarts on next cron tick.
- [ ] `max_runs` enforced — schedule auto-disables after Nth fire.
- [ ] On conductor restart, all `enabled=true` schedules re-register from Postgres before accepting traffic.
- [ ] Prometheus counter `maistro_schedule_fires_total{schedule_id, outcome}` increments on each fire.
- [ ] OTel span `schedule.fire` parents the resulting `task.run` span via the existing `@trace_agent` decorator.

## Resolved decisions (v0)

1. **Per-schedule concurrency → `overlap_policy` enum, default `skip`.** If a schedule fires while its previous task still runs, the default is **skip**. `overlap_policy: skip | queue | cancel_previous` is a recipe-overridable field.
2. **Multi-process → single-conductor v0.** In-memory APScheduler for the single-conductor case. Multi-replica leader election (Postgres advisory-lock leader) is **deferred** to a follow-up ADR.
3. **Time-zone → IANA-on-row, applied at fire time.** Store the IANA tz string on the schedule row and apply at fire time (DST-correct); do **not** normalize to UTC at create time.
4. **Skills-per-schedule → no separate column.** Skill ids ride on the `task_template`; add a dedicated column only if skill-policy ever diverges from task-policy.

## Source references

- `hermes-desktop:src/renderer/src/screens/Schedules/Schedules.tsx` — UX surface (frequency presets, pause/resume/trigger-now, repeat counter, last_error)
- `hermes-desktop:src/main/cronjobs.ts` — in-process cron runner
- `maistro-engine:packages/maistro-core/src/maistro/scheduler/` — target package (the empty placeholder was removed; recreate on implementation)
- `maistro-engine:src/maistro/tasks/runner.py`, `tasks/queue.py` — reused submission path

## Out of scope

- Multi-replica leader election (revisit when conductor goes horizontal).
- UI — substrate exposes API only; product repos own the schedules screen.
- Backfill / catch-up after long downtime — missed fires are dropped.
