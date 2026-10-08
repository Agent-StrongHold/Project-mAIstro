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

Each race stages its own actor count (recorded per case in the research
note's topology table — four actors for the claim, window, store-effect,
invocation and event races; two for dueling terminalization; one reclaimer
plus the fixture holder for cursor fencing; sequential for the stale-writer
and terminal-spine cases): independent sessions, one OS thread, one asyncio
loop, one private asyncpg pool per actor — a strictly stronger coordination
than the existing shared-pool `asyncio.gather` races, because every statement
runs on its own backend with its own locks and snapshot. The module is
self-validating about actually racing: the consumer-claim race holds the Run
row lock on an independent connection and requires every actor backend to
appear in the `pg_blocking_pids` wait graph before release (a liveness poll on
one shared predicate, `_contention_proved`, used both to stop polling and in
the final assertion; note `pg_blocking_pids` reports direct blockers, so the
witness checks the chain is rooted at the holder, not that every waiter names
it); both effect-claim races put a `threading.Barrier` between the read-none
SELECT and the INSERT to make the read-none/read-none/insert window
deterministic (at the store level via the `_require_locked_parent_scope` seam
inside the real method); the event-ordering race requires two distinct actors'
id ranges to overlap pairwise, which per-session serialization cannot produce.

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
→ 9 passed in ~2.2s, stable over repeated runs, and 3/3 green under full CPU
saturation after the repair below) and all nine skip cleanly without a DSN.
Three mutation experiments are recorded in the research note; two were
re-verified live at this repair on a scratch database: dropping
`ix_canonical_runs_effect` makes both effect-window cases insert four canonical
runs for one effect key (assert `4 == 1`), and dropping the claim SELECT's
`FOR UPDATE` fails the claim race within ~1.3s — the production edit was
reverted bit-identical afterwards. The third (removing the invocation claim's
terminal exclusion) is pinned by the terminal re-claim leg reading the claim
upsert's `WHERE status <> ALL(...)` guard directly. No product code changed in
this delta.

CI repair at this head (the harness's first and only real flake): quality.yml
run 37789491251 (`coverage (PostgreSQL)`) failed `test_invocation_claims_...`
with "exactly one dispatch … got 2" — the race used a 50 ms lease, and
`PgInvocationStore.claim` correctly re-claims a PENDING invocation whose lease
has lapsed, so a slow actor became a second legitimate winner (reproduced
locally under CPU saturation before the fix: re-claim landed 111 ms after
creation). The dependent "Coverage gate" job then skipped (`needs:
coverage-postgres`), which `gates-ran` reads as a required gate that never
executed. The repair makes the verdict load-independent: the race phase now
leases for 30 s (no in-race re-claim can be legitimate) and expiration is
exercised deterministically afterwards, sequentially. Node identities are
unchanged — the +9 delta and every node ID are exactly as first recorded.

Environment trap worth recording (pre-existing, not introduced here): 17 node
IDs elsewhere in `packages/maistro-core/tests` appear in collection only when
`MAISTRO_TEST_PG_DSN` is set (collect-with-DSN 15324 vs collect-without 15307
at this change). The gate's collector job (ci.yml `test`) does not set the
DSN, so the recorded convention is collect-without-DSN — this module collects
its 9 identically either way, but anyone running the gate with a DSN exported
in their shell will see a +17 DRIFT that is not inventory drift.
