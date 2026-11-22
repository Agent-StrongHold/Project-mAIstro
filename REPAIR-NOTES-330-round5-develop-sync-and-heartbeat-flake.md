# REPAIR-NOTES — #330 round 5 (branch `auto-330`)

Job `6d947371ea2041088cad1c9136956e0f`, 2026-10-25. Incoming head
`aa1581274`; develop base for this round `9cc09cd57`. Two blocks carried in:
the preserved develop-sync conflict, and the red `coverage (no services)` /
`gates-ran` checks from the last merge-queue evaluation.

## 1. Develop sync (the preserved conflict block)

`origin/develop` had advanced one commit past the round-4 sync:
`9cc09cd57` "fix(security): clear CodeQL findings and shrink DevSkim alert
backlog (#2288)". Merged with:

```
git merge origin/develop
```

One conflict, union-resolved in `tests/test_mutation_baseline.py`: this
branch's `test_skipped_rows_never_enter_the_denominator` and develop's
`test_ci_error_annotation_strips_non_allowlisted_characters` both appended
after `test_baselined_source_regression_fails`; both are kept, and the merged
`scripts/check_mutation_baseline.py` carries both the SKIPPED-row denominator
adjustment and the allowlisted `_ci_error_annotation` helper (verified by
reading the merged file; `tests/test_mutation_baseline.py` → 6 passed).
`quality/` ledgers: `git diff --numstat origin/develop -- quality/` shows only
this branch's intended additions (mutation-critical-files.json +64,
branch-independence +8, reachability/dispositions/workflow-inventory edits) —
no silent row loss.

## 2. Salvage of the incoming uncommitted work

The worktree arrived with an uncommitted mutation of
`packages/maistro-core/src/maistro/privilege.py`
(`if self.ttl_seconds <= 0` → `if not self.ttl_seconds <= 0`) plus untracked
cosmic-ray/mutation experiment artifacts (`cosmic-ray-privilege-*.toml`,
`mutation-*.jsonl/.tsv`) — leftovers of the prior round's timed-out cosmic-ray
sweep on that exact file (`mutation-targets-pending.tsv` names it). The mutant
inverts the TTL-expiry guard and would break `ElevationGrant.validate()`; it
is a written-out mutant, not salvageable work.

Preserved before any edit: `git diff` and all untracked artifacts copied to
the job directory under `salvage/` (`incoming-330-mutant-leftover.patch`,
`privilege.py.mutated`, and the five artifact files). The mutant was then
reverted by a targeted edit (no git restore/clean used) and the artifacts
moved out of the tree into `salvage/`.

## 3. `coverage (no services)` red — root cause and fix

Fetched the actual job log read-only (run 40142381555, job 121016624638).
Two quoted errors, one real:

- **Docker pull line is a red herring.** The pre-pull step *succeeded*
  ("Status: Downloaded newer image for python:3.12-slim"); the
  `::error::could not pull...` text in the log is the step's own script echo
  rendered by the runner, not an executed error.
- **The real failure is one flaky test**:
  `test_a_resumed_schedule_attempt_is_leased_and_reclaimed_after_worker_death[sqlite]`
  — "a live resumed Attempt was not renewed by the heartbeat" after the full
  150-poll budget.

Diagnosis: the polls completed all 150 iterations inside the 30s timeout, so
the loop was turning — yet the heartbeat (ttl/3 ≈ 0.167s with the test's
0.5s lease) never produced a visible renewal. A first tick that lands after
the expiry boundary is refused by `renew_attempt_lease`
(packages/maistro-core/src/maistro/runs/lifecycle.py:422) and the heartbeat
exits permanently (`runs/execution.py:_beat`) — correct production behavior
for a worker silent past its TTL. A 0.5s lease is simply shorter than a
coverage-instrumented runner's worst-case loop latency.

**Reproduction (throwaway harness, deleted after use).** Replaying the
renewal-poll section with a 1s event-loop stall injected right after the
resumed node starts: ttl=0.5s fails with the exact CI error on the memory and
sqlite legs; ttl=5.0s passes the identical stall.

**Fix**: `ttl = timedelta(seconds=5)` in the test, with the constraint
documented at the site. The recovery/reclaim boundary stays deterministic via
the explicit clock (`now=live_lease.expires_at + 1µs`); every assertion
recomputes from the `ttl` variable.

Downstream closure: coverage-unit red ⇒ `Coverage gate` skipped (it `needs`
coverage-unit) ⇒ `gates-ran` red ("present but did not execute to a verdict
(1): Coverage gate (publish-set floor + diff coverage)", run 40144573969).
Fixing the test fixes both.

## 4. Validation performed this round

- `uv run pytest packages/maistro-core/tests --timeout=30 -q` (the coverage
  job's first producer, post-fix): **16687 passed, 1213 skipped, 7 xfailed**
  — identical counts to the pre-fix baseline run, confirming the zero
  inventory delta.
- `uv run pytest packages/maistro-core/tests/runs -q --timeout=60`: 1495
  passed, 368 skipped.
- `uv run pytest tests/test_mutation_baseline.py -q` (conflict-resolved file):
  6 passed.
- `uv run pytest tests/test_mutation_{pr_gate,critical,diff_scope,select_tests}*.py
  tests/test_mutation_packet_safety.py tests/test_check_image_lock_reconciliation.py -q`:
  147 passed (mutation gate suites after the develop merge).
- Vulture with CI's exact args (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): 1297 = 1297, exit 0; no ledger amendment needed (this
  round touches a test file only).
- `check-workflow-inventory.py`, `check-branch-protection.py`,
  `check-suite-inventory.py`: clean (develop's devskim/release workflow edits
  are covered by existing dispositions).
- `uv run ruff check .` / `uv run ruff format --check .`: clean.

## 5. Residual risks

- The `[postgres]` leg of the fixed test needs `MAISTRO_TEST_PG_DSN`; it was
  skipped locally and is exercised by the `coverage (PostgreSQL)` job.
- CI runner load beyond ~5s stall between resume and the first heartbeat tick
  could in principle still outrun the lease; 30× headroom over the observed
  failure mode makes that implausible without a new failure signature.
- The salvaged mutant's source session (prior round's cosmic-ray sweep) timed
  out mid-run; its evidence value is superseded by the committed
  5/5-kill sweep recorded in round 1's notes.
