---
inventory-delta:
  packages/maistro-core/tests: +9
---
# 887 M8-A7: real-PostgreSQL race/invariant research harness (+9)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #887 (epic #880) asked for a bounded experiment racing the durable stores
against real PostgreSQL from multiple independent actors, with a
GRADUATE/INCUBATE/REJECT/WATCH disposition. The research record is
`docs/research/887-postgresql-concurrency-race-harness.md`; this change adds its
harness: `packages/maistro-core/tests/runs/test_m8a7_pg_race_harness.py` (+9 node
IDs, all PostgreSQL-gated on `MAISTRO_TEST_PG_DSN` — collected unconditionally,
skipping as a whole without a DSN, so the delta holds in every environment).

Each of the 9 races stages `ACTORS = 4` independent sessions (one OS thread, one
asyncio loop, one private asyncpg pool per actor) — a strictly stronger
coordination than the existing shared-pool `asyncio.gather` races, because every
statement runs on its own backend with its own locks and snapshot. The module is
self-validating about actually racing: the consumer-claim race holds the Run row
lock on an independent connection and requires every actor backend to appear in
the `pg_blocking_pids` wait graph before release (a liveness poll; note
`pg_blocking_pids` reports direct blockers, so the witness checks the chain is
rooted at the holder, not that every waiter names it); the effect-claim races put
a `threading.Barrier` between the read-none SELECT and the INSERT to make the
read-none/read-none/insert window deterministic; the event-ordering race requires
per-actor id ranges to interleave, which per-session serialization cannot
produce.

The cases: duplicate consumer claims elect one physical winner (Run RUNNING,
exactly one NodeRun, one RUNNING Attempt); the raw read-none/read-none/insert
window against `ix_canonical_runs_effect` elects exactly one row; the real
`claim_run_by_effect` from four stores returns `claimed=True` once and one shared
canonical run; stale Attempt-COMPLETED under a terminal Run is refused while the
documented FAILED-record asymmetry holds; dueling terminalizations from two
stale actors land exactly one legal terminal status; `(trigger, event)`
invocation claims dispatch exactly once across sessions and a terminal
invocation is never re-claimed (attempts stay 1); concurrent event-log appends
yield unique ids in one paginatable total order; a reclaimed cursor lease fences
the stale holder's advance and position never moves backwards; no new NodeRun
under a terminal Run from a stale session.

All nine were executed green against a real migrated PostgreSQL 18.6
(`uv run pytest packages/maistro-core/tests/runs/test_m8a7_pg_race_harness.py`
→ 9 passed in ~2.3s, stable over repeated runs) and all nine skip cleanly
without a DSN. Three mutation experiments are recorded in the research note:
dropping the claim's `FOR UPDATE`, dropping the invocation claim's terminal
exclusion, and dropping `ix_canonical_runs_effect` each make specific cases fail
loudly — the last produces four canonical runs for one effect key, the exact
defect class the issue hypothesizes. No product code changed in this delta.
