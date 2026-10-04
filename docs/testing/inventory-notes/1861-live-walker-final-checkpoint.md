---
inventory-delta:
  packages/maistro-core/tests: +6
---
# Live-walker final-checkpoint recovery regression (#1861)

## What moved

`packages/maistro-core/tests/graph/durable_runs` gains six collected node IDs:
`test_live_walker_final_checkpoint.py` adds one named regression
(`test_live_walker_final_checkpoint_is_not_claimed_by_recovery`) and one
companion crash-oracle case
(`test_crashed_empty_frontier_walker_is_still_recovered_after_quiet_period`),
each parametrized over `memory` / `sqlite` / `postgres` backends. The
PostgreSQL parametrization runs a real `PgRunStore` plus
`PgGraphContinuationStore`, with the recovery instance on its own asyncpg pool
so the tick reads the walker's writes through an independent connection.

## Why

A live canonical walker that has committed its final empty-frontier checkpoint
but not yet written its terminal Run checkpoint presents an active frontier of
zero NodeRuns — every NodeRun is terminal, no Attempt holds a lease, the
continuation reads RUNNING with no `resume_at`. `_has_stalled_active_frontier`
fell through `True` for that state (the guard #1715 removed while inlining the
lease helper), so one recovery tick re-queued the continuation under the live
walker: `resume_at` set, version advanced, and the walker's terminal
checkpoint died on `version regression: stored=N incoming=N`. The named test
drives the real executor into exactly that barrier, holds it while a second
`CanonicalDurableRunStore` instance over the same authorities runs one
recovery tick, and asserts the tick changes nothing before releasing the
walker to complete on its original Attempt.

The empty frontier is also what a walker that *died* in the same window leaves
behind, and that residue must still be recovered. A bare
`if not active_node_runs: return False` (the pre-#1715 guard) keeps the live
walker safe but strands the dead one forever: a RUNNING continuation with no
`resume_at` is invisible to the due index, so nothing ever settles it. The
companion case pins that oracle — it fails under the bare early return (proved
against this branch) and passes under the repair, which claims the empty
frontier only once the spine has been quiet past
`TERMINAL_SETTLE_QUIET_PERIOD`, the same span past which no live walker is
assumed anywhere else in the store. Both tests count one physical node
execution and exactly one Attempt with an accepted outcome, so a duplicate
effect or a second Attempt cannot hide behind a green assertion.

## Verification record (L1861 verify @ cccf9d49a7f8)

Verifier/writer re-run at head `cccf9d49a7f827707a33bc10f4beb5ecf623e57f`
(fix commit `8d635a8fd`, develop base `928993dda1c9`), `MAISTRO_TEST_PG_DSN`
pointed at the lane pgvector (127.0.0.1:55186, migrated to alembic head 052).
Collected node IDs: the six listed under "What moved" —
`test_live_walker_final_checkpoint_is_not_claimed_by_recovery` and
`test_crashed_empty_frontier_walker_is_still_recovered_after_quiet_period`,
each over `memory` / `sqlite` / `postgres`; all six executed, zero skipped.
Backend/store composition: postgres legs run real `PgRunStore` plus
`PgGraphContinuationStore` with the recovery instance on an independent
asyncpg pool (`recovery_pool`, separate from `walker_pool`); the acceptance
battery also re-ran unmodified.

Fail-before/pass-after: with the predicate's empty-frontier branch temporarily
restored to the pre-fix fall-through (`return True`), the named regression
failed on all three backends at the barrier assertion
`assert await recovery.reconcile_persistence(now=...) == 0` → `assert 1 == 0`
— one tick claimed the live continuation; reverting the probe restores the
pass (worktree byte-identical afterwards, clean `git diff`).

Battery (exact acceptance command plus the new file, `-q -ra`):
`test_crash_window_invariants.py` + `test_recovery_completion_budget.py` +
`test_cross_store_crash_reconciliation.py` +
`test_canonical_recovery_contract.py` + `test_live_walker_final_checkpoint.py`
= 107 passed, 0 skipped; full `packages/maistro-core/tests/graph/durable_runs`
= 648 passed with real PG. Observed no-op snapshots (memory observation run,
matching the asserted equalities): barrier continuation `{version: 7,
status: running, resume_at: None}` → one recovery tick returns 0 and the
continuation compares equal (byte-identical) → released walker returns
COMPLETED with 1 counted execution and final continuation `{version: 8,
status: completed, resume_at: None}` (original lineage, exactly one Attempt
ordinal 1 COMPLETED) → second recovery tick returns 0, snapshot identical.

Gates: `ruff check .` clean; `ruff format --check .` clean (2889 files);
`check-suite-inventory.py` ok (14 suites match the recorded inventory);
documented full-package `mypy` command clean (792 files); CI-repair round
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` exits 0 — 1342 findings, all reviewed identities banked,
no unbanked identities and no `quality/` delta vs develop
(`git diff --numstat origin/develop -- quality/` empty), so the per-identity
ledger needed no amendment for this change.

Independent re-verification (L1861 verify @ `decb1fbb62a1`): fix content is
byte-identical to `cccf9d49a7f8` (the docs commit adds only this note). The
exact acceptance battery plus the new file, run against the lane pgvector
(`MAISTRO_TEST_PG_DSN=127.0.0.1:55186`, alembic head `052`) = **107 passed,
0 skipped**; full `packages/maistro-core/tests/graph/durable_runs` = **648
passed**. Fail-before re-proved without touching the tree: `git archive` of
develop base `928993dda1c9` plus this test file — the named regression failed
all three backends at `assert await recovery.reconcile_persistence(...) == 0`
→ `assert 1 == 0` (one tick claimed the live continuation) while the companion
crashed-walker case passed there; the repaired tree passes. Also re-run clean:
`ruff check .`, `ruff format --check .`, the CI-exact vulture ratchet
(1342 reviewed identities = 1342 findings, no `quality/` delta vs develop),
and the documented nine-package `mypy` command (792 source files).

Independent re-verification (L1861 verify @ `e30ca1a216fe`): fix content is
byte-identical to `8d635a8fd` (the two commits after merge `cccf9d49a7f8` add
only this note). The exact acceptance battery plus the new file, run against
the lane pgvector (`MAISTRO_TEST_PG_DSN=127.0.0.1:55186`, alembic head `052`
confirmed via `alembic_version`): `uv run --frozen pytest
packages/maistro-core/tests/runs/test_crash_window_invariants.py
packages/maistro-core/tests/runs/test_recovery_completion_budget.py
packages/maistro-core/tests/graph/durable_runs/test_cross_store_crash_reconciliation.py
packages/maistro-core/tests/graph/durable_runs/test_canonical_recovery_contract.py
packages/maistro-core/tests/graph/durable_runs/test_live_walker_final_checkpoint.py
-q -ra` = **107 passed, 0 skipped** — all six new legs executed, real PG
included (recovery on its own asyncpg pool). Fail-before re-proved without
touching the tree: `git archive` of develop base `928993dda1c9` plus this test
file, same DSN — the named regression failed all three backends at
`assert await recovery.reconcile_persistence(now=...) == 0` → `assert 1 == 0`
(one tick claimed the live continuation at the barrier) while the companion
crashed-walker case passed there; the repaired tree passes. Observed no-op
snapshots (direct observation run at this head, memory composition): barrier
continuation `version=7, status=running, resume_at=None` → one recovery tick
returns 0 with the continuation unchanged → released walker returns COMPLETED
with 1 counted execution and final continuation `version=8, status=completed,
resume_at=None` (original lineage, exactly one Attempt ordinal 1 COMPLETED
with result set, 1 accepted NodeRun) → second recovery tick returns 0,
snapshot unchanged. Gates re-run clean at this head: `ruff check .`,
`ruff format --check .` (2889 files already formatted),
`check-suite-inventory.py --suite packages/maistro-core/tests` (ok). No
closure keywords in the branch's commit messages or the PR body.
