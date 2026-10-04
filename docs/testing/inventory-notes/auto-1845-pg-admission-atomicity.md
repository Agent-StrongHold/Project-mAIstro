---
inventory-delta:
  packages/maistro-core/tests: +21
---

# auto-1845 — PG admission atomicity tests

## What changed

Four test files back the #1845 atomic admission lane (two new files, one new
live-PG file, one test appended to an existing file); no existing test was
removed or renamed, and no existing test's assertions were relaxed.

- `test_pg_root_admission_coordinator.py` (12 tests): the coordinator's fenced
  decisions at its own seam, using the repo's fake-asyncpg pattern
  (`test_idempotency_durable.py`). Pins the joint write (insert + binding on
  one acquired connection, one READ COMMITTED transaction, row lock before
  insert), the fences (409 on fingerprint mismatch, bound-row replay without
  minting, replaced-generation refusal without insert or delete, missing row),
  the ambiguity rule (connection failure resolved by a fresh-connection reread
  of the durable row), the generation-fenced release, the unrefreshed replay
  window, and that a prepared Run enters the insert QUEUED with its
  provenance.
- `test_admission_commit_atomicity.py` (6 tests): the queue-level failure
  class from the issue — commit a Run, lose the completion, reopen,
  resubmit — which must now yield exactly one Run and one receipt on the
  coordinator lane. Also pins that the atomic path never awaits `complete`,
  replay independence from lease ownership, bounded re-claim without releasing
  a successor's row, release-only-own-generation after a failed preparation,
  and the untouched legacy path where no coordinator is wired.

- `test_pg_admission_atomicity_live.py` (2 tests, skipped without
  `MAISTRO_TEST_PG_DSN`): the production wiring — PG claim store,
  `TaskRunAdmitter.prepare_run`, `PgRunStore.insert_prepared_run` — against a
  real server: the joint commit lands and a resubmit-after-death replays
  without minting, and a server-refused insert (duplicate run_id) rolls the
  binding back with the Run.
- `test_admission.py` (+1): `TaskRunAdmitter.prepare_run` stamps the
  entry-point `admission_source` last, like `admit` does, so the atomic lane's
  Runs carry the audit provenance the legacy lane's do.

## Why these counts

Each test pins one behavior the issue names: one-commit admission, no
successor interference, replay-not-remint, and the legacy contracts the lane
must preserve. The coordinator's statement shapes are asserted against the
real SQL strings the module issues; transaction semantics themselves are not
re-proven here (that is the live PG tier's job), and the queue-level stub's
decisions mirror the unit-pinned ones, so the two files do not double-count
the same behavior at different seams without saying so.
