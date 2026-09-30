---
inventory-delta:
  packages/maistro-core/tests: +20
  packages/hive-conductor/backend/tests: +15
---

# 1200-bounded-schedule-catchup

**+35 across two suites** — the bounded catch-up work contract (#1200): the
engine's catch-up walk gained host-selected window/step/time bounds with
truthful incompleteness semantics, `parse_cron` gained a bounded memoization
so walking no longer reparses per occurrence, the schedule definition model
caps the catch-up window at seven days, and the Hive `/v1/schedules` product
surface enforces an operator-configured frequency floor and window cap, both
bounded at startup.

`packages/maistro-core/tests` (+20):

- `tests/scheduling/test_enumeration_limits.py` (+13, new) — the contract
  tests: the default step bound is derived from the window bound (7 days of
  per-minute cron = 10,144 steps, the whole possible backlog), out-of-bounds
  and boundary `EnumerationLimits` values, a zero budget stopping before any
  work, an expired budget and a tight step bound each marking the evaluation
  `enumeration_incomplete` with the exact stop point, every reported
  occurrence proved to lie within the examined range (the unexamined range is
  never claimed as fired or skipped), the host window clamp reported and
  honored by the public `enumeration_start`, a seven-day (50k-class) backlog
  evaluating in bounded wall time under the default limits, a fully examined
  minutely hour, and explicit limits leaving ordinary catch-up decisions
  byte-identical.
- `tests/scheduling/test_cron.py` (+2) — `parse_cron` is memoized per
  expression (identity across calls, distinct for distinct expressions) and
  parse errors are not cached, so probing invalid expressions costs no memory
  and cannot poison the cache.
- `tests/scheduling/test_admission.py` (+3, `TestBoundedEnumeration`) — the
  admission half: an incomplete walk runs nothing, writes nothing, keeps the
  due cursor and reports where it stopped; a complete walk advances the
  cursor to the fired occurrence and the due cursor to the next one.
- `tests/scheduling/test_model.py` (+2) — the definition model refuses a
  catch-up window past the seven-day ceiling while accepting the ceiling
  itself (one new test, plus one `catchup_window_seconds` case in the
  parametrized invalid-definition matrix).

`packages/hive-conductor/backend/tests` (+14):

- `test_schedule_frequency_floor.py` (+11, new) — the product floor and cap:
  a per-minute create is a 422 naming `schedule_min_frequency_gap_s` and
  files nothing; `0,5,10 * * * *` is refused because `minimum_gap` measures a
  five-minute real gap (list forms are not read as hourly); `*/15` is
  accepted at the reference floor; raising the operator floor refuses a
  recurrence-touching update while a rename of the same row stays legal (the
  floor applies to the effective recurrence, not to any edit); a window over
  the operator cap, over the seven-day substrate ceiling, and a negative
  window are all 422s; a window within the cap reaches the canonical row and
  a window update is projected to it; floor/cap settings outside the safe
  startup bounds (300–604800 for the floor, 3600–604800 for the cap) fail at
  startup instead of clamping, and the boundary values themselves load.
- `test_scheduler_bounded_tick.py` (+4, new) — the live tick through
  `_ScheduleRunner._tick()` and the real `ScheduleRunAdmitter` seam: a walk
  cut short by a host-selected zero budget logs the truthful backlog warning,
  runs nothing, leaves the cursor alone, and the next tick under ordinary
  limits re-examines the same occurrence and fires it; a seven-day window
  under a one-hour host bound fires normally and logs that the configured
  window was not the one applied; a seven-day-stale per-minute backlog
  completes the whole tick in bounded wall time with at most the newest 512
  occurrences consumed per evaluation; and a legal zero window reaches the
  canonical definition as zero ("never backfill" honored — the tick projects
  a missing column to the default, never a falsy zero).
