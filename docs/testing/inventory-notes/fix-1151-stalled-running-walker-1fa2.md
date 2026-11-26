---
inventory-delta:
  packages/maistro-core/tests: +18
---
# fix-1151-stalled-running-walker-1fa2

Six end-to-end cases in
`tests/graph/durable_runs/test_cross_store_crash_reconciliation.py`, each run
against the memory, SQLite and PostgreSQL continuation stores (6 x 3 = +18)
over develop's file. An earlier revision of this note recorded +30 (ten
cases); the merge reconciliation below removed four of them, so the net
delta against the baseline is +18.

They hold the #1151 windows to their contract end to end: a walker whose
recovery claim was cleared by its first frontier checkpoint and which then
died leaves a RUNNING Run the due index never lists. Three drive the real
executor into that state. Two assert the shipped due tick finishes the Run
without re-running committed nodes: the last node settled but the Run did
not, and a two-node walk that died between frontiers. The third, a walk that
died inside its second node, asserts the Run is left alone while that
Attempt's lease is live and made due once it lapses (resuming it needs the
lease lapsed in wall time, which the executor reads itself). The other three
pin the repair's shape at the store boundary: the stranded continuation is
made due with an elapsed claim (version+1) and a second tick is idempotent,
the continuation is not claimed while the spine moved within the
terminal-settle quiet period, and a recovering walker's own claim is never
reclaimed.

## Merge reconciliation (supersession)

The branch originally added a separate per-version-observation repair
(`_reconcile_stalled_walk`) for the same RUNNING/RUNNING unclaimed state.
develop's reviewed stalled-active-frontier repair (#1942, with the #1861
quiet-period protection) owns that state and runs first, which made the
branch's repair unreachable and its four remaining cases contradictory with
the landed design:

- the restarted-replica stanza (no claim on a first tick past the quiet
  period) contradicts `test_crashed_empty_frontier_walker_is_still_recovered_
  after_quiet_period`, which requires exactly that single-tick recovery;
- the lease-less stanza (an open Attempt with no lease is never presumed
  dead) contradicts the reviewed `has_live_execution_lease` stance the
  frontier repair is built on;
- the two bookkeeping cases poked `_stalled_first_seen`, an attribute of the
  removed repair.

Those four cases were removed with the unreachable repair; canonical_store.py
is byte-identical to develop's. The strict-xfail markers in
`test_canonical_durable_store.py` continue to hold (verified: 4 xfailed, none
xpass).

Each surviving guard was checked to fail when the behaviour it names is
refused: the lease-lapse case fails if the lapsed continuation is not made
due; the quiet-period case fails if the continuation is claimed before the
period elapses; the elapsed-claim case fails if the repair does not advance
the version exactly once.
The PostgreSQL leg needs `MAISTRO_TEST_PG_DSN` and runs in quality.yml's
`coverage-postgres` job.

## Proof scope

The cross-store file's PostgreSQL parametrization exercises the
`PgGraphContinuationStore` against an in-memory Run spine: it pins the
continuation-store SQL and the repair shape, not a process restart. Durable
canonical-spine recovery (both authorities on PostgreSQL, independent pools,
no shared objects) is proven separately in
`tests/runs/test_pg_spine_crash_windows.py`, including the stalled-frontier,
terminal-spine, continuation-before-mirror, elapsed-claim and bounded-sweep
windows. The PR #1626 body's "10 cases" count is stale relative to this
proof-only branch: the per-version-observation repair it described was
superseded by develop's stalled-active-frontier repair (#1942, #1861) and
removed during the merge, leaving six cases.

## Verification record (2026-10-26 repair round)

Re-executed against this branch's head, with the PostgreSQL legs live against
a real PostgreSQL 18 (pgvector, migrated to head):

- `test_cross_store_crash_reconciliation.py`: **72 passed** — all three legs,
  so the six cases above also hold against the `PgGraphContinuationStore` SQL.
- `tests/runs/test_pg_spine_crash_windows.py`: **16 passed** — the durable
  canonical-spine proof (both authorities on PostgreSQL, recovery through an
  independently built pool, new physical work refused at the recovery replica)
  is green on the same server. The cross-store file pins the continuation SQL
  and repair shape; this suite owns the restart-across-pools proof.
- `test_canonical_durable_store.py`: 16 passed, **4 xfailed, none xpassed**.
- Guard sabotage from outside the tree (a `/tmp` pytest plugin, no repo edit):
  forcing `_spine_is_quiet` true fails `test_a_walk_whose_spine_just_moved_is
  _left_to_its_walker`; forcing `has_live_execution_lease` false fails
  `test_a_walker_that_died_inside_a_later_node_is_recovered_once_its_lease
  _lapses`; making `_reconcile_stalled_active_frontier` a no-op fails
  `test_the_repair_gives_an_elapsed_claim_and_is_idempotent`.
- Gates: `ruff check` / `ruff format --check` clean; `check-suite-inventory`
  21 suite(s) match; `check-vulture-baseline` with CI's exact arguments
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) reports
  1253 reviewed identities -> 1253 findings (no unbanked debt);
  `check-release-consistency`, `check-retired-guidance` and
  `check-workflow-inventory` all clean.

## Verification record (2026-10-26 develop-sync round)

Re-executed after merging origin/develop (`10f872fa7`, admission replay
generations) into the branch; the only conflict was the CodeQL CHANGELOG line,
resolved to develop's wording (`#2359; follow-up to #2357`), which supersedes
the branch's own `#2359` edit. `canonical_store.py` remains byte-identical to
develop's (verified by diff against the develop tip). All PostgreSQL legs ran
against a fresh `pgvector/pgvector:pg18` container migrated to head
(`alembic upgrade head`):

- `test_cross_store_crash_reconciliation.py`: **72 passed, 0 skipped** (all
  three legs; the six cases above hold against the `PgGraphContinuationStore`
  SQL on PostgreSQL 18).
- `tests/graph/durable_runs/` whole directory: **811 passed, 4 xfailed**.
- `tests/runs/test_pg_spine_crash_windows.py`: **16 passed** — the durable
  canonical-spine proof still green on the merged tree.
- `test_canonical_durable_store.py`: 16 passed, 4 xfailed, none xpassed.
- Guard sabotage re-proven from a `/tmp` pytest plugin (no repo edit), each on
  all three store legs: forcing `_spine_is_quiet` true fails
  `test_a_walk_whose_spine_just_moved_is_left_to_its_walker`; making
  `_reconcile_stalled_active_frontier` a no-op fails
  `test_the_repair_gives_an_elapsed_claim_and_is_idempotent`; forcing
  `has_live_execution_lease` true fails
  `test_a_walker_that_died_inside_a_later_node_is_recovered_once_its_lease
  _lapses`.
- Gates: `ruff check` / `ruff format --check` clean; `mypy --strict` over all
  seven `packages/*/src` trees clean (953 files); `check-suite-inventory` 21
  suite(s) match; `check-vulture-baseline` (CI's exact arguments) now reports
  **1248 reviewed identities -> 1248 findings, exit 0** — develop's
  `#2169`/`#2287` commits removed banked dead identities, lowering the count
  from the 1253 recorded above; the ledger still matches the scan with no
  unbanked debt. `check-release-consistency`, `check-retired-guidance` and
  `check-workflow-inventory` all clean.
