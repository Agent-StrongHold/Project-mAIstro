# M8-A7 research note — real-PostgreSQL concurrency invariant racing

Leaf: #887. Epic: #880. Initiative: #879.

## Hypothesis (as filed)

Process-local asyncio locks and ordinary integration tests cannot establish
distributed invariants across multiple workers; concurrent transactions against
real PostgreSQL can expose races in claims, idempotency, ordering, and
terminal-state transitions.

## Baseline (what already existed at this head)

The repo is not naive about PostgreSQL races; the M0-M7 owners shipped real
guards plus race tests against a shared pool on one event loop:

- `ClaimingPgRunStore.claim_consumer_run` — one `SELECT … FOR UPDATE` before the
  claim writes (`packages/maistro-core/src/maistro/runs/consumer_claim.py`);
  raced by `test_consumer_claim_recovery.py::test_concurrent_claims_have_one_physical_winner`.
- `transition_attempt(COMPLETED)` re-reads the parent Run under `FOR SHARE`
  inside the write transaction (#1335), parent-first lock order everywhere
  (#1888, `test_pg_result_repair_lock_order.py` even proves blocking via
  `pg_blocking_pids`).
- `claim_run_by_effect` — read + `ON CONFLICT DO NOTHING` over the partial
  unique index `ix_canonical_runs_effect` (migration 041).
- `PgInvocationStore.claim` / `PgConsumerCursorStore` — single-statement
  conditional upserts whose `WHERE` clause is the exclusion test.
- Schedule admission races (#220/#850) in `test_pg_admission.py`.

The shared-pool/one-loop shape is the gap the hypothesis names: those tests
cannot prove that a claim's lock wait crossed *database backends*, cannot place
a deterministic window between a read and its insert, and several durable seams
(invocation terminal exclusion, cursor fencing, event-log ordering under
concurrency) had no race test at all.

## Experiment

`packages/maistro-core/tests/runs/test_m8a7_pg_race_harness.py` — 9 races, each
staging four **independent sessions**: one OS thread, one asyncio loop, one
private `asyncpg` pool per actor. Separate backend sessions (not shared-pool
tasks) are the unit PostgreSQL actually serializes on; none of the guards under
test depend on process identity, so thread-per-actor is the bounded stand-in for
process-like workers, and it keeps the harness inside one pytest process.
Runtime ~2.3s for all nine.

The harness is self-validating about *actually racing* — the design decision
this note is mostly about:

- **Contention witness.** The claim race holds the Run row lock on an
  independent connection and polls `pg_stat_activity` until every actor backend
  appears in a `pg_blocking_pids` wait chain rooted at the holder, then releases.
  Directly observed Postgres behavior worth recording: `pg_blocking_pids`
  reports **direct** blockers, so on a four-waiter row queue only the first
  waiter names the holder — waiters 2-4 name the waiter ahead of them
  (`wait_event_type=Lock`, `tuple` vs `transactionid`). The witness therefore
  checks "every actor lock-waiting, wait graph internal to the race, holder is
  the chain root", not "every waiter names the holder". A liveness poll, not a
  timing bound.
- **Deterministic window.** The effect-claim race puts a `threading.Barrier`
  between the read-none SELECT and the INSERT inside each actor's transaction —
  read-none/read-none/insert is *constructed*, not hoped for.
- **Interleaving witness.** The event race requires the four actors' id ranges
  to overlap; per-session serialization would produce disjoint contiguous
  blocks and the test fails itself before it can pass vacuously.

## Results

**Zero product defects found.** Every invariant held on PostgreSQL 18.6:

| Invariant (issue's candidate list) | Seam raced | Verdict |
| --- | --- | --- |
| one canonical active claim | `claim_consumer_run` × 4 sessions | held: 1 winner, 3 `ConsumerClaimLost`, one NodeRun/one RUNNING Attempt |
| uniqueness/idempotency across sessions | read-none/read-none/insert + `claim_run_by_effect` × 4 | held: exactly one canonical run, one `claimed=True`, shared identity |
| terminal state not overwritten by stale writers | stale Attempt-COMPLETED under FAILED Run; dueling COMPLETED/FAILED | held: refused in-transaction; exactly one terminal lands |
| exactly-once dispatch | `PgInvocationStore.claim` × 4 | held: one winner; terminal never re-claimed; attempts stay 1 |
| recovery-lease fencing | cursor re-claim after expiry | held: stale `advance` refused, position monotone |
| durable event ordering | 4 × 25 concurrent appends | held: unique ids, one total order, clean pagination |

**Mutation detection (the oracle works).** Three surgical breaks, each detected
by a named case within ~1.5s:

1. `FOR UPDATE` dropped from the claim SELECT → duplicate claims collide on
   `uq_canonical_node_runs_run_ordinal`; exactly-one-winner fails.
2. Invocation claim's terminal exclusion (`status <> ALL(...)`) removed → a
   SUCCESS invocation is re-dispatched (`attempts=2` handed to a claimant).
3. `ix_canonical_runs_effect` dropped → the read-none window inserts **four**
   canonical runs for one effect key. This is the issue's hypothesized defect
   class, reproduced on demand, and it settles the constraints-vs-locks
   question for this seam: no application lock was involved — the unique index
   *is* the invariant.

**DB constraints vs application locks** (the issue's evidence ask):

- Enforced by database constraint/statement atomicity: effect uniqueness
  (partial unique index), physical claim singularity (row lock + `UNIQUE
  (run_id, ordinal)` + one-active-attempt), invocation exactly-once (one
  conditional upsert), cursor fencing (token-guarded `UPDATE` + `GREATEST`),
  event id uniqueness/order (sequence).
- Enforced by application logic riding database locks: lifecycle legality
  (transition tables), earned completion, terminal-Run parent re-reads. These
  are only as strong as the lock discipline; the lock-order suite
  (#1888) is what pins that discipline.

**Runtime/flakiness:** 9 passed in 2.17-2.39s across four consecutive runs,
zero flakes; skip path (no `MAISTRO_TEST_PG_DSN`) is 9 skips in ~1.1s and the
module still collects (inventory delta +9 recorded in
`docs/testing/inventory-notes/887-m8a7-pg-race-harness.md`).

**Database-version sensitivity:** evidence is single-version — PostgreSQL 18.6
(Ubuntu 18.6-0ubuntu0.26.04) locally, matching CI's `pgvector/pgvector:pg18`
service. Behavior on PG ≤ 16 (e.g. `pg_blocking_pids` granularity, speculative
insert waiting) is **UNVERIFIED** here; the harness runs unmodified wherever
`MAISTRO_TEST_PG_DSN` points.

**False positives:** five harness drafts failed for researcher-induced reasons
(illegal `created → failed` transitions, `RunEffectClaim.claimed` vs
`.created`, an unstaged-actor slot returned by `join`, a witness predicate
contradicting `pg_blocking_pids` direct-blocker semantics, a fixture object
passed where a DSN string was required). All were harness bugs, fixed before
any verdict; none indicated product defects.

## Disposition: INCUBATE

- What it catches that existing gates do not: races that only exist across
  backends (proved by the wait-graph witness), windows that must be
  constructed to be seen (barrier-between-statements), and seam coverage no
  existing race test had (invocation terminal exclusion, cursor fencing,
  event-log ordering). Existing shared-loop races would catch mutation 1 too —
  this harness's marginal value is determinism, contention *proof*, and
  breadth, not a brand-new failure class.
- Why not GRADUATE yet: zero new defects on a seam set the M0-M7 owners
  already guard well; a standing multi-actor framework per seam is
  maintenance the evidence doesn't yet force. Incubate as the pattern for new
  durable seams: every new `FOR UPDATE`/upsert guard lands with one
  independent-session race using these witnesses.
- Why not REJECT/WATCH: 3/3 mutations detected, ~2.3s CI cost on substrate CI
  already runs (a migrated PostgreSQL), and the read-none window experiment is
  the only known on-demand reproduction of the duplicate-effect defect class.
- Follow-ups if incubated: a true multi-process leg (subprocess actors) to
  close the "process-like" gap entirely; a PG 14/16 matrix leg for the
  version-sensitivity gap; fold the witness helpers into the shared test
  spine if a third suite needs them.

Defect routing: nothing to route — no live defect was found. The mutation
reproductions are harness-side evidence, not product regressions.
