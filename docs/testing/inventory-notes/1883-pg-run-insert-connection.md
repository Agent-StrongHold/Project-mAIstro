---
inventory-delta:
  packages/maistro-core/tests: +3
---
# Issue #1883 PG connection-owned Run insert proof

Adds `packages/maistro-core/tests/runs/test_pg_run_insert_connection.py` with the
three proof nodes issue #1883 specifies for the connection-owned Run-insert seam:
`test_outer_rollback_removes_inserted_run`,
`test_helper_counts_and_locks_on_supplied_connection`,
`test_create_run_uses_connection_helper`. No production code changed.

Reconciliation (recorded, per the issue's "re-read develop and record" rule):
the issue was pinned to baseline `045cfdfb` (and re-reviewed at #1325
`bfd34223`), where `create_run` still performed validation and the INSERT inline
and asked for a new internal helper named `insert_run_on_connection`. At this
lane's base `4aa68edc0b6b85ae23f97e611d693927218863dc` the seam already exists,
landed by merged PR #1940 (commit `680329c96`), as the public
`PgRunStore.insert_prepared_run(conn, run)` — root-admission advisory locks, the
canonical_runs INSERT and the root ceiling count on the caller's connection, no
pool acquisition, no own transaction, no commit — called by `create_run` inside
its unchanged READ COMMITTED transaction and injected verbatim into
`PgRootAdmissionCoordinator` by `runs/wiring.py`. The outcome ("one
connection-owned operation for the real caller and the coordinator") is
therefore already realized; a second name for the one operation, or a rename
rippling through the coordinator wiring, is out of this leaf's permitted-file
scope and would be the duplication the codebase treats as the worse diff. This
lane pins the issue's contract against the realized seam. #1882's
`prepare_root_run` outcome is likewise already landed, as
`PgRunStore.prepare_run`; the two lanes' seams (validation hoist vs insert
extraction) are disjoint and both present.

Evidence (real PostgreSQL, pgvector pg18, disposable database migrated with
`alembic upgrade head` to 062, production JSON codecs via the shared `pg_pool`
fixture, DSN `postgresql://maistro:maistro@127.0.0.1:55933/maistro_test`):

- Source SHA under test: `4aa68edc0b6b85ae23f97e611d693927218863dc` plus this
  test file only; `git diff` on `pg_store.py` empty after the mutation check.
- Collected nodes: the three listed above (unparametrized), collected with
  `uv run pytest packages/maistro-core/tests/runs/test_pg_run_insert_connection.py -q`
  → `3 passed`.
- Expected pre-fix failure: at the issue's pinned baseline the seam does not
  exist (the helper and its name are absent), so the file cannot import — the
  pre-fix state is "no connection-owned seam", which is why the issue called the
  helper a proposed contract. The regression path at this head is proven by
  mutation instead: a mutant `insert_prepared_run` that inserts on a second pool
  connection (implicit commit, the issue's "commits internally or uses a second
  connection" class) fails `test_outer_rollback_removes_inserted_run` (the row
  survives the caller's rollback) and
  `test_helper_counts_and_locks_on_supplied_connection` (pool acquisition
  recorded; statements bypass the supplied connection), then was reverted
  byte-identical.
- Injected boundary: the test owns the real asyncpg connection, opens the outer
  transaction itself, calls the helper inside it, and raises `_InjectedFailure`
  after asserting — through the same connection — that the inserted row is
  visible in-transaction (guards against a vacuous rollback pass). No sleeps;
  single-writer, so no barrier races.
- Instrumentation depth (strengthened after first handoff): the recording
  connection keeps each statement's positional arguments, so the instrumented
  node pins the four statements by index and proves the lock namespaces from
  their actual arguments (`_WORKSPACE_ADMISSION_LOCK`/`_PRINCIPAL_ADMISSION_LOCK`
  with `_admission_lock_key(workspace)`/`_admission_lock_key(principal)`), the
  INSERT's first bound argument is the candidate run_id, and the ceiling count
  is bound to `(workspace, principal)` — a reordering that keeps the statement
  multiset can no longer pass. The wrapper also records `transaction()` calls,
  and the node asserts the helper entered none: a helper-owned `transaction()`
  would only nest a savepoint on the same connection, which the statement
  record and pool counter cannot see.
- Independent re-verification (verify lane, PG at `127.0.0.1:55933` migrated to
  062): both mutation classes re-executed and both source mutants reverted
  byte-identical (sha256-checked). (A) a second-connection/implicit-commit
  mutant fails `test_outer_rollback_removes_inserted_run` and
  `test_helper_counts_and_locks_on_supplied_connection` (2 failed, 1 passed);
  (B) a helper-owned-savepoint mutant — invisible to the statement record and
  the pool counter — fails only the strengthened `transactions == []`
  assertion (1 failed, 2 passed). CI's exact inventory invocation
  (`python scripts/check-suite-inventory.py`, whole tree) reports 17 suites
  matching, and the focused command re-run on this verify lane: 67 passed.
- Review-followup (recorder owns the transaction boundary too):
  `_RecordingConnection.transaction()` now records calls and the instrumented
  test asserts `recording.transactions == []` — a helper-owned
  `async with conn.transaction()` would only nest a savepoint, leaving
  statements on the supplied connection, pool acquisitions at zero and the
  outer rollback still cleaning up, so the pre-fix recorder passed it silently.
  Proven by mutant: a wrapper opening `conn.transaction()` around the real
  helper passes all three nodes on the pre-fix recorder and fails
  `test_helper_counts_and_locks_on_supplied_connection` on the fixed one
  (`assert [((), {})] == []`); `pg_store.py` reverted byte-identical after.
- SQL row/identity counts: rollback case — in-transaction count 1 for the
  candidate run_id, 0 on a second connection after the rollback; capacity case —
  helper refuses with `RunConcurrencyExceeded` at a saturated ceiling (limits
  1/1, slot-holder committed first), candidate count 0 afterwards, slot-holder
  count 1; wiring case — the wrapped helper is invoked exactly once on a
  connection already in transaction, and exactly one durable Run remains.
- Focused command (the issue's): `uv run pytest
  packages/maistro-core/tests/runs/test_pg_run_insert_connection.py
  packages/maistro-core/tests/runs/test_run_concurrency_limits.py -q` →
  67 passed.
- Adjacent suite against the same server: `uv run pytest
  packages/maistro-core/tests/runs -q` → 1498 passed, 3 skipped (pre-existing
  conditional skips; the three new nodes executed, not skipped). Without a DSN
  the new file skips cleanly, matching the convention of
  `test_pg_admission_atomicity_live.py` — the plain (no-PG) coverage job runs
  this directory and a hard failure there would break an unrelated leg; the
  durability claims above were executed, not skipped, in the recorded run.
- `uv run ruff check` / `ruff format --check` clean on the new file. mypy is
  src-only in CI (`packages/*/src`); the new test file introduces no new mypy
  signal beyond the environmental import-untyped noise any test file shows
  under a standalone invocation.
