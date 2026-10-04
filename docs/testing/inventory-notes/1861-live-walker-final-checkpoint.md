---
inventory-delta:
  packages/maistro-core/tests: +9
---
# Live-walker final-checkpoint recovery regression (#1861)

## What moved

`packages/maistro-core/tests/graph/durable_runs` gains nine collected node IDs:
`test_live_walker_final_checkpoint.py` adds one named regression
(`test_live_walker_final_checkpoint_is_not_claimed_by_recovery`), one
companion crash-oracle case
(`test_crashed_empty_frontier_walker_is_still_recovered_after_quiet_period`),
and one quiet-period boundary case
(`test_live_walker_held_past_quiet_period_is_claimed_and_refused`), each
parametrized over `memory` / `sqlite` / `postgres` backends. The
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

The quiet period is an elapsed-time assumption, not evidence that a walker
stopped, so the third case closes the review's unresolved live-owner question:
it holds a walker alive at the same barrier while recovery evaluates exactly
one tick at an explicit moment past the period (no sleep, no killed walker,
no extra ticks), asserts the claim wins that race (version `v → v+1`,
`resume_at` set), releases the walker, and asserts its own final checkpoint is
refused with `version regression` — while the spine still shows exactly one
terminal NodeRun, one Attempt and one counted execution, and the continuation
is exactly the claim, so a later canonical resume owns the same lineage. The
case passes on the pre-fix tree too (the fall-through predicate claims at any
age), which is what makes it a boundary statement rather than a pass-after
oracle: the guarantee this repair adds is bounded by the settle period, and
that bound is now executed evidence instead of a docstring claim.

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

Independent re-verification (L1861 verify @ `e1c8fa19651a`): the assigned head
`e1c8fa19651a0636c1d906a2c3b6c690e01f0000` (merge of develop base
`4010e69f62cf` into auto-1861) keeps the fix module and this test file
byte-identical to `e30ca1a216fe` — the merge brings in develop's
foreign-harness content only; no `durable_runs`/`runs` store file changes.
Re-ran at this exact head against the lane pgvector (`pg-l1861`,
`127.0.0.1:55186`, alembic head `052` confirmed via `alembic_version`): the
exact acceptance battery plus the new file = **107 passed, 0 skipped**; the
new file verbose = 6 passed —
`test_live_walker_final_checkpoint_is_not_claimed_by_recovery[memory|sqlite|postgres]`
and
`test_crashed_empty_frontier_walker_is_still_recovered_after_quiet_period[memory|sqlite|postgres]`;
full `packages/maistro-core/tests/graph/durable_runs` with real PG = **648
passed** (postgres legs: real `PgRunStore` + `PgGraphContinuationStore`,
recovery instance on an independent asyncpg pool). Fail-before re-proved
without touching the tree: `git archive` of this head with only
`canonical_store.py` reverted to the base `4010e69f62cf` module — the named
regression failed all three backends at the barrier assertion
(`assert await recovery.reconcile_persistence(...) == 0` → `assert 1 == 0`,
one tick claimed the live continuation) while the companion crashed-walker
case passed there, so the repair is not a bare early return. Observed no-op
snapshots (direct observation run at this head, memory composition): barrier
continuation `version=7, status=running, resume_at=null, active_node_ids=[]`
→ recovery tick returns 0 with the continuation model-dump identical →
released walker returns COMPLETED with 1 counted execution, 1 NodeRun with
accepted outcome, exactly 1 Attempt ordinal 1 COMPLETED with result set →
final continuation `version=8, status=completed, resume_at=null` → second
recovery tick returns 0, snapshot identical, canonical Run COMPLETED. Gates
re-run clean at this head: `ruff check .`, `ruff format --check .` (2898
files), `check-suite-inventory.py --suite packages/maistro-core/tests` (ok),
CI-exact vulture ratchet `check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` exit 0 (1340 reviewed
identities = 1340 findings; `git diff --numstat 4010e69f62cf -- quality/`
empty), documented `mypy` command clean (794 source files). No closure
keywords in the branch's commit messages or the PR body.

Repair round (L1861 repair @ `ad0a29201a44`): closes the PR-#1942 proof
checkpoint's unresolved live-owner case. The production module is
byte-identical to `e1c8fa196` (`git diff e1c8fa196..HEAD --
packages/maistro-core/src` empty); this round adds only the deterministic
live-after-quiet-period case
`test_live_walker_held_past_quiet_period_is_claimed_and_refused` (three new
collected legs, one per backend) and this note — exactly the case the
checkpoint specified: the existing final-empty-frontier barrier, the walker
never killed, no sleeps, and exactly one recovery tick evaluated at an
explicit `now` past `TERMINAL_SETTLE_QUIET_PERIOD` via
`reconcile_persistence(now=…)`. Executed at lane pgvector `pg-l1861`
(`127.0.0.1:55186`, alembic head `052` confirmed via `alembic_version`):

- New file `uv run --frozen pytest
  packages/maistro-core/tests/graph/durable_runs/test_live_walker_final_checkpoint.py
  -q -ra` = **9 passed, 0 skipped** (three cases × memory/sqlite/postgres;
  postgres legs real `PgRunStore` + `PgGraphContinuationStore`, recovery on
  its own asyncpg pool).
- Exact acceptance battery plus the new file (`test_crash_window_invariants.py`
  + `test_recovery_completion_budget.py` +
  `test_cross_store_crash_reconciliation.py` +
  `test_canonical_recovery_contract.py` + this file, `-q -ra`) = **110
  passed, 0 skipped**; full `packages/maistro-core/tests/graph/durable_runs`
  with real PG = **651 passed**.
- Fail-before re-proved without touching the tree (`git archive` of this head
  with only `canonical_store.py` reverted to the develop base `2ef76025`
  module): the named regression failed all three backends at
  `assert await recovery.reconcile_persistence(now=...) == 0` → `assert 1 == 0`
  while the crashed companion and the new boundary case passed there — the
  boundary case is a statement about the quiet-period race, which the
  fall-through predicate loses identically, so it is expected to pass on both
  trees.
- Observed claim-race snapshots (direct observation run at this tree, memory
  composition): barrier continuation `version=7, status=running,
  resume_at=null` → one tick at `now = wall clock + 1h` returns 1 and stores
  `version=8, status=running, resume_at=<that moment>` → released live walker
  raises `version regression: stored=8 incoming=8` (the historical #1715
  signature, now deterministically reproduced against a live walker) → spine
  after refusal: Run `running`, 1 terminal NodeRun, exactly 1 Attempt
  `completed` ordinal 1, 1 counted execution → continuation equals the claim
  exactly → a second tick past the period returns 0 with the snapshot
  identical.
- Gates re-run at this tree: `ruff check .` clean; `ruff format --check .`
  (2898 files); `check-suite-inventory.py --suite
  packages/maistro-core/tests` ok against the updated `+9` delta; documented
  six-package `mypy` command clean (794 source files); CI-exact vulture
  ratchet exit 0 (1340 reviewed identities = 1340 findings, `git diff
  --numstat origin/develop -- quality/` empty — no ledger amendment needed;
  this round touches `packages/*/src` not at all).

Independent re-verification (L1861 verify @ `fb5fad4e38d4`): the assigned head
`fb5fad4e38d4192f7f8318541c85a30de884beca` is the merge of develop base
`680329c960cd` into auto-1861; the fix module
`canonical_store.py` and this test file are byte-identical to the
`ea180743fdce` versions this note already records (`git diff ea180743f..HEAD`
touches neither), but the merge also brings develop's #1940 store content
(`runs/pg_store.py`, `runs/wiring.py`, `tasks/*`), so the proof was re-executed
at this exact head rather than inherited. Diff scope vs base: exactly three
files (this note, the `canonical_store.py` predicate, this test file);
`packages/maistro-core/tests/runs/` and the four acceptance files are
byte-identical to base; `git diff --numstat 680329c960cd..HEAD -- quality/`
empty. Executed against lane pgvector `pg-l1861` (`127.0.0.1:55186`, alembic
head `052` confirmed via `alembic_version`), `MAISTRO_TEST_PG_DSN` set:

- New file `uv run --frozen pytest
  packages/maistro-core/tests/graph/durable_runs/test_live_walker_final_checkpoint.py
  -q -ra` = **9 passed, 0 skipped** (three cases × memory/sqlite/postgres;
  the 6-legged no-DSN driver run skipped exactly the three `[postgres]` ids).
- Exact acceptance battery plus the new file (`test_crash_window_invariants.py`
  + `test_recovery_completion_budget.py` +
  `test_cross_store_crash_reconciliation.py` +
  `test_canonical_recovery_contract.py` + this file, `-q -ra`) = **110 passed,
  0 skipped**; full `packages/maistro-core/tests/graph/durable_runs` with real
  PG = **651 passed**. Postgres legs: real `PgRunStore` +
  `PgGraphContinuationStore`, recovery instance on an independent asyncpg pool.
- Fail-before re-proved without touching the tree (`git archive` of this head
  with only `canonical_store.py` replaced by the develop base `680329c960cd`
  module): `test_live_walker_final_checkpoint_is_not_claimed_by_recovery`
  failed all three backends at the barrier assertion
  (`assert await recovery.reconcile_persistence(now=...) == 0` →
  `assert 1 == 0`, one tick claimed the live continuation) while the crashed
  companion and the quiet-period boundary case passed there.
- Observed snapshots (direct observation script at this head, memory
  composition): barrier continuation `{version: 7, status: running,
  resume_at: None, active_node_ids: []}` → recovery tick returns 0, model
  equal → released walker COMPLETED, 1 counted execution, 1 NodeRun completed
  with accepted outcome, exactly 1 Attempt ordinal 1 COMPLETED with result →
  final continuation `{version: 8, status: completed, resume_at: None}`
  (original lineage) → second tick returns 0, snapshot identical, canonical
  Run completed. Claim race at the same barrier: one tick at
  `now = wall clock + 1h` returns 1 and stores `{version: 8, resume_at set}`;
  the released live walker raises `version regression: stored=8 incoming=8`;
  spine afterwards: Run `running`, 1 terminal NodeRun, 1 Attempt ordinal 1,
  1 execution; continuation equals the claim; second tick returns 0 unchanged.
- Gates re-run at this head: `ruff check .` and `ruff format --check .` clean
  (driver logs), `check-suite-inventory.py --suite packages/maistro-core/tests`
  ok (`+9` delta), documented six-package `mypy` command clean (795 source
  files), CI-exact vulture ratchet exit 0 (1340 reviewed identities = 1340
  findings, baseline base `680329c960cd` → candidate `fb5fad4e38d4`),
  `check-reachability.py` exit 0. No closure keywords in the branch's commit
  messages or the PR body.
