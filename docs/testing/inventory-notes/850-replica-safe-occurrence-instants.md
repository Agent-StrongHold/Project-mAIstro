---
inventory-delta:
  packages/maistro-core/tests: +7
---

Adds coverage for occurrence claims surviving a schedule timezone edit (#850). A
crashed winner's claim on one instant must still answer after the schedule's
timezone is edited in either direction, and a non-UTC schedule must write the
instant (UTC) rather than its wall-clock rendering, on the in-memory reference
store, on SQLite, and on real PostgreSQL. A new two-replica race on real
PostgreSQL gathers two admitters holding snapshots from opposite sides of a
timezone edit over the same due window and requires exactly one Run per
instant, every claim stored as the canonical instant, and one converged
schedule row (`runs_so_far == 3`, `last_fired_at` at the newest occurrence).
