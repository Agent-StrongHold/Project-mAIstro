---
inventory-delta:
  packages/maistro-core/tests: 0
  packages/maistro-canvas/tests: 0
  packages/hive-conductor/backend/tests: 0
---

# 2425-restack-p4a-c8b9151-recovered-writer-repositions

Restack of the #2425 / P4b branch onto the moved stacked base
`cursor/m1-b-p4a-recovered-disposition-8551` head `c8b9151de0` (PR #2424 tip).
No tests are added, removed, or modified: every recorded suite inventory is
unchanged (`check-suite-inventory.py` ok for maistro-core, maistro-canvas and
hive-conductor backend at the merge commit).

## Why the hosted gates failed while the branch tree was clean

Hosted CI for head `4c1710216c` runs on GitHub's PR merge ref, which at that
moment was `e6f4aeb3` = merge(`4c1710216c`, `57b4b140` = PR #2424's own merge
ref into develop). The branch and the base had both merged develop
(`fc1bea9936`, then `f626d94fc1`) through different merge parents (criss-cross),
and git auto-merged the #2417 / P3b recovery writers at two different file
positions on the merge ref:

- `maistro/runs/pg_store.py`: `PgRunStore.recover_orphaned_attempt` at both
  2067 and 2215 → hosted `Quality / Ruff` 4x F811.
- `maistro/runs/sqlite_store.py` and `maistro/runs/store.py`: the same
  duplicate-definition shape → hosted mypy (`Quality / Mypy strict`,
  `lint-and-type-check`) and the aggregate `Quality gate` failed on the same
  merged content, not on the branch tree.

Local verification of the branch tree itself (`4c1710216c`) had already passed
all of those gates; the failures existed only on GitHub's merge content. The
repair is the stack fix, not a gate change.

## Merge resolution (commit 6b109f5c94, parents 4c1710216c + c8b9151de0)

Four content conflicts, resolved in place. For each, both sides were diffed:

- `maistro/runs/pg_store.py`, `maistro/runs/sqlite_store.py`,
  `maistro/runs/store.py`: base-side deltas vs `4c1710216c` are pure
  repositions of byte-identical functions (`recover_orphaned_attempt`,
  `apply_recovered_attempt_disposition` in Protocol + InMemory). Kept the
  branch position, one copy each; the resolved files are byte-identical to the
  locally validated `4c1710216c` blobs.
- `packages/maistro-core/src/_vulture_whitelist.py`: identical identity set on
  both sides (the four `apply_recovered_attempt_disposition` entries plus the
  `recover_orphaned_attempt` block); only entry order and the surrounding
  comment differ. Kept the branch comment, which is the accurate one for the
  merged state: P4b's reconciler wire (`runs/reconciliation.py`) calls
  `apply_recovered_attempt_disposition` now, while P4a's still read "the
  reconciler wire is P4b, so packages/*/src does not yet call the method".

Because the base's only substantive new content relative to the branch was the
already-absorbed develop syncs, the merge tree equals the `4c1710216c` tree;
the commit exists to make `c8b9151de0` an ancestor so GitHub's next PR merge
ref equals the validated branch content.

## Re-validation at the merge commit (CI-exact commands)

- `uv run ruff check .` — pass; `uv run ruff format --check .` — pass.
- `uv run mypy --strict packages/maistro-core/src` — 846 files, no issues
  (after `uv sync --locked --all-extras`, matching the quality job env).
- multi-package `uv run mypy packages/...-src` (the `lint-and-type-check` list)
  — 1128 files, no issues.
- Targeted recovery suites (driver's pytest set incl.
  `test_reconciler_recovered_provenance.py`,
  `test_recover_orphaned_attempt.py`, `test_pg_recovered_attempt_disposition.py`,
  canvas `test_canonical_execution.py`) — 437 passed, 144 skipped.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — pass, 1221 reviewed
  identities unchanged.
- `check-suite-inventory.py` for maistro-core, maistro-canvas, hive-conductor
  backend — all ok (no inventory delta).
- `pr-base` continues to fail by design for this stacked PR (ADR-095; the PR
  body documents it and the gate names the retarget requirement).
