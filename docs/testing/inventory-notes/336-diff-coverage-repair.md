---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  tests/: +4
---
# Issue 336 — diff-coverage repair (coverage-gate round)

The merge-queue run at `b637299` failed exactly one job, `Coverage gate
(publish-set floor + diff coverage)`, and its failing step was the per-file
diff gate (`scripts/check-diff-coverage.py`), not the 87% floor (which passed
at 93%) and not a missing producer (all three uploaded; the
"contributed no coverage data" lines in the failure digest were script text,
and the `RuntimeError: Event loop is closed` lines were
`PytestUnhandledThreadExceptionWarning`s in runs that passed). Two files fell
below the per-file floors:

- `packages/hive-conductor/backend/services/permission_policy.py` — 82.6% of
  23 statement lines: the body of `permission_for_ui_action` (lines 217-220)
  executed nowhere in any measured run. The function is the policy's
  fail-closed resolver for UI action names; the repair gives it the tests its
  contract claims — every advertised `UI_MUTATIONS` action round-trips to its
  own permission, and an unknown action raises `KeyError` instead of guessing.
- `scripts/check-conductor-permission-matrix.py` — 0% of 39 statement lines.
  The script runs as a quality.yml workflow step, which records no coverage;
  the repo convention (see `tests/test_check_api_route_contracts.py`'s
  docstring) is that every `scripts/` gate also gets an in-process root-suite
  proof. The new `tests/test_check_conductor_permission_matrix.py` drives the
  gate's logic in process: the shipped tree passes with the middleware table
  generated from the one policy source, a hand-edited middleware table is
  refused, a UI action the frontend never ships is refused on all three
  drift checks (unreferenced path, unnamed permission, absent from the API
  policy), and the frontend scan covers both arcs of the #2273 lib-restructure
  branch (trees with and without `lib/`).

Local proof at the repair head, reproducing the gate's own arithmetic:
`coverage run --branch --source=packages/hive-conductor/backend -m pytest
packages/hive-conductor/backend/tests --timeout=30 -q` (4600 passed, 117
skipped) combined with the new root test under `--source=scripts`, then
`uv run python scripts/check-diff-coverage.py <xml> --base 80242f28` exits 0
with the same scope line CI printed (4 changed files measured, 2 exempt).
