# M2 #448 — repair round at de9faebfa (finishes 96381577e)

Lane L448 repair round. Prior round left uncommitted salvage (reap +
drain-visibility in the bounded capture helpers) and red checks. This round
completed and committed it; evidence below.

## What the CI evidence actually was (read, not guessed)

- `coverage (no services)` red at 4b0b81dc6 — job log (run 39116394655 /
  job 117642949118): the evolve leg failed
  `packages/maistro-evolve/tests/test_e2e_sandbox_loop.py::TestSandboxEvolveE2E::test_sandbox_execute_score_promote_and_reuse`
  with `AttributeError: '_FakeProc' object has no attribute 'stdout'`. The
  #1197 bounded-capture contract (drain `process.stdout`/`stderr`, then reap
  via `wait()`) postdates that fake. Fixed by giving the fake the readers and
  `wait()` — it mirrors core's `test_docker.py` mock, as its docstring claims.
  Reproduced locally at 96381577e before the fix.
- ci.yml `test` red at 4b0b81dc6 — job log (run 39116394628 /
  job 117642949176): exactly 1 failure in 5033,
  `deploy/scripts/verify-restore.sh` "[verify-restore] VERIFIER FAIL: scratch
  postgres did not become ready" — infra flake in the restore oracle, zero
  relation to this branch (root `tests/` does not touch the capture helpers;
  `grep -rl 'communicate_bounded|run_bounded' tests/` → no matches).
  Environmental; not repaired in-tree.
- `gates-ran` red is the aggregator (#262 AC-2): it follows the producers.

## This round's changes (commit de9faebfa)

1. Salvage completed: `communicate_bounded` reaps after EOF (core + RSI
   mirror), `run_bounded` snapshots drained bytes incrementally so a
   descendant holding the pipes past the child's exit no longer forfeits the
   output; close only drains that reached EOF.
2. Fake contracts: evolve `_FakeProc` + readers/wait; core docker `_FakeProc`
   + wait (driver battery showed the miss).
3. `test_container_sandbox_output_bound.py` reformatted (committed ruff drift
   from 96381577e).
4. Suite delta recorded: `inventory-notes/auto-448-a9e4.md` (+3 core = the
   salvage's reap/wait_for/descendant tests; +3 bootstrap = 96381577e's
   read_file/edit_file tests, note written late).

## Validation executed (all green)

- `uv run ruff check .` / `uv run ruff format --check .`
- Publish-set suites, CI's per-package partition (`--timeout=30 -q`):
  core 15380 passed/1074 skipped/3 xfailed; canvas 465/75; evolve 998/6;
  rsi 1631/4; bootstrap 238/7.
- `python scripts/check-suite-inventory.py` (CI exact, all suites): 17 ok,
  31437 unique node IDs, 0 duplicates.
- `python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: rc=0, no ledger amendment needed.
- mypy core+rsi: only environmental import-not-found (evolve/bootstrap not
  installed in this worktree venv) + 5 pre-existing no-any-return in files
  this branch never touched; CI lint job green at 4b0b81dc6.

## Residual risks

- The `test` job's verify-restore flake can recur on the next CI run; it is
  not addressable from this branch and unrelated to the sandbox slice.
- Local skips (1074 core) exceed CI's (1048) because docker/bwrap/pg legs
  skip here; the bounded-capture paths themselves ran (test_docker,
  test_capture, mirror, microvm, bootstrap builder suites).
