# REPAIR NOTES — issue #1893 round at 807dfacca (job c29d9c1a)

## Frozen scope

Only issue #1893, branch `auto-1893`, worktree `/home/dev/Git/wt/auto-1893`.
Exact starting HEAD `807dfacca04fe3b42cf160d8b32be46f2c0557b0` (verified; tree
clean). Merge-queue named failure: `test: failure`. Nothing else in scope. No
gate, ledger, grant, or workflow edits; no test additions (suite inventory
delta 0, no note required); no GitHub mutations.

## Root cause (established from the tree, not from scanner guesses)

`tests/test_check_convergence_matrix.py::test_the_shipped_matrix_matches_the_shipped_code`
reproduces locally at the starting head: `check-convergence-matrix.py.main([])`
returns 1 on exactly two stale rows —

- Run / NodeRun / Attempt lifecycle: Unreachable says `few`, code says `none` (0 of 32)
- Task queue and runner: Unreachable says `few`, code says `none` (0 of 15)

History: `4cb757ce8` moved the Task-queue row `none`→`few` (and #1851's
`ac0b821ac` the Run row) to match `maistro.tasks.admission_codec` /
`maistro.runs.admission_identity` being banked unreachable.
`a58ebb24c` then classified both modules as intentionally-unreachable contract
leaves in `scripts/check-reachability.py` `_EXCLUDED_PACKAGE_PYTHON` and pruned
them from `quality/reachability-baseline.json` — but never moved the two matrix
words back. The matrix went stale relative to the code; the gate is doing its
job ("Update the matrix row (or the code) so the two agree").

## Repair

`docs/architecture/CONVERGENCE-MATRIX.md`: the two disposition-table rows'
Unreachable cells `few` → `none`. Docs describing the tree truthfully; no other
column touched. This is not a gate or ledger change.

## Executed validation (long timeouts, read output not just exit codes)

- `uv run python scripts/check-convergence-matrix.py` → exit 0: "OK: 52
  subsystems classify all 1437 production modules; 157 unreachable modules are
  attributed" (the Quality / Convergence matrix step's exact command,
  quality.yml:2051).
- `uv run pytest tests/test_check_convergence_matrix.py -q` → 60 passed.
- CI-exact `test` job root suite `uv run pytest tests/
  --ignore=tests/tools/registry -q` → 5488 passed, 139 skipped (was: failed on
  the single convergence node).
- `uv run python scripts/check-reachability.py` → exit 0 (1437 modules, 157
  unreachable); `uv run python scripts/check-reachability-dispositions.py` →
  exit 0 (47 groups / 157 modules).
- CI-exact vulture `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 0
  (1320 reviewed / 1315 findings, zero unbanked) — the lane-permitted
  `quality/vulture-baseline.json` amendment has no target; not touched.
- `uv run ruff check .` → all checks passed; `uv run ruff format --check .` →
  3419 files already formatted.
- `uv run python scripts/check-suite-inventory.py --suite tests` → ok, no
  duplicate evidence (driver check-4 also ok for maistro-core; no test files
  changed, inventory delta 0).

## Hosted-gate reconciliation (read-only `gh` API evidence)

At HEAD `807dfacca` (run 39686526131/39686526172, 2026-10-21T22:26Z):
- **Gate C — canonical clean install: success.** The round's carried Gate C
  failure was at the earlier evaluation commit `a3956e9b1`; it is green at the
  current head and needs no branch change.
- **Vulture Ratchet: success.**
- CI `test` = failure and Quality {Convergence matrix, Quality gate
  (dependency), Coverage gate (producers)} = failure — all four traced to the
  single convergence-matrix node fixed above (prior findings show the same
  FAILED excerpt inside the coverage gate's scripts producer; the other two
  jobs are dependency/cascade failures).
- "RuntimeError: Event loop is closed" lines in hosted logs are aiosqlite
  worker-thread warnings from passing SQLite suites (pre-existing; also present
  locally as warnings with zero failures), not gate failures.

## Handoff

Branch left committed and clean; the convergence matrix now matches the code
the reachability gate measures. No issue closure actions, no push.
