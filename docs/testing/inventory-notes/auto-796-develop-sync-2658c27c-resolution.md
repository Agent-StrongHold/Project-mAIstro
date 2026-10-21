---
inventory-delta:
  packages/maistro-core/tests: +0
---

# auto-796-develop-sync-2658c27c-resolution

Repair round for #796 ([M7-A7] Map Evolve/RSI as consumers of the same eval; forbid a
second loop). The round resolved the preserved `origin/develop` sync conflict in the
worktree and re-validated the M7-A7 contract on the merged head. **No test was added or
removed** — the suite count is unchanged (`packages/maistro-core/tests` keeps the +7
recorded in `m7-a7-eval-consumer-map.md`).

## Conflict resolved

`git merge origin/develop` (`e20e9f52ea94`, merge-base `64ea662cb015` and
`c5e070d97d`) left nine files unmerged. The merge base used for those paths was
`c5e070d97d`, whose blobs still carry upstream's committed `Temporary merge branch`
conflict-marker lines; both sides had cleaned them up differently, so every hunk
overlapped.

Our side carried **no** change in eight of the nine files — `HEAD:0cfd4579f` was
byte-identical to `64ea662cb015` for

- `deploy/scripts/verify-restore.sh`,
- `docs/install/deployment-topology.md`,
- `packages/maistro-core/src/maistro/graph/durable_runs/attempt_executor.py`,
- `packages/maistro-core/src/maistro/persistence/pg_audit.py`,
- `packages/maistro-core/src/maistro/persistence/sqlite_audit.py`,
- `packages/maistro-core/src/maistro/security/sentinel/audit.py`,
- `packages/maistro-turing/backend/routes/chat.py`,
- `tests/cross_product_parity/harness.py`,

and `64ea662cb015` is an ancestor of `e20e9f52ea94` — develop's tip is the
forward-evolved truth for those paths, so develop's version was taken verbatim (no
content of ours was lost, because we had none there).

`docs/architecture/CONVERGENCE-MATRIX.md` was the only file this branch had actually
edited: it carries the #796 "One scoring loop…" section. Resolution = develop's newer
document (its ownership census moved 52/73/31) with our section re-inserted verbatim
above `## Related`. The merged document differs from `e20e9f52ea94` by exactly that
section (`git diff --numstat e20e9f52ea94 HEAD -- docs/architecture/CONVERGENCE-MATRIX.md`
→ 21 added lines, 0 removed).

Resolution commit: `2658c27c5825` (`Merge commit 'e20e9f52ea94…' into auto-796`,
parents `0cfd4579f19c` and `e20e9f52ea94`).

## Ledger integrity through the merge

- Our arc touched no `quality/` file, and the merged tree is byte-identical to
  `e20e9f52ea94` for `quality/` (`git diff --numstat e20e9f52ea94 HEAD -- quality/` is
  empty) — no per-identity ledger row was lost in the merge.
- The vulture ratchet re-bases on `merge-base(origin/develop, HEAD)`, which the merge
  moved from `64ea662cb015` to `e20e9f52ea94`; with develop's tip as the base the
  scan is `1326 reviewed identities -> 1326 findings` (exit 0), i.e. develop's five
  newly banked `admission_identity` rows are now the trusted baseline instead of new
  debt.

## Re-validation on the merged head (`2658c27c5`)

- `uv run pytest packages/maistro-core/tests/fitness/test_m7_a7_eval_consumer_map.py -q`
  → 7 passed (the M7-A7 contract: design loop imports no RSI/Evolve, Evolve/RSI never
  reach the design Rubric domain, `maistro_design` declares no scoring/promotion
  surface, no design-quality score outside the canonical homes, `RubricEval` anchor,
  the M5 pin, and the negative controls).
- `uv run pytest packages/maistro-core/tests/fitness/ -q` → 34 passed.
- `uv run pytest packages/maistro-rsi/tests/test_non_production_reachability.py -q`
  → 13 passed (M5 invariant unchanged).
- `uv run pytest packages/maistro-design/tests -q` → 575 passed, 1 skipped.
- `uv run ruff check .` → clean; `uv run ruff format --check .` → 3363 files formatted.
- `uv run mypy <7 src trees>` → no issues in 906 source files.
- `uv run python scripts/check-convergence-matrix.py` → OK (52 subsystems / 1417
  production modules).
- `uv run python scripts/check-suite-inventory.py` → ok (21 suites match).
- `uv run python scripts/check-doc-links.py` → 0 broken links.
- `uv run python scripts/check-contract-markers.py` → OK.
- `uv run python scripts/check-merge-markers.py` → ok (no conflict markers in any
  tracked file — upstream's committed `Temporary merge branch` lines are gone with the
  merged content).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's exact arguments) → exit 0, 1326 identities.

## Pre-existing upstream condition (not this branch's)

`uv run python scripts/check-reachability.py` fails with one newly unreachable module,
`maestro.runs.admission_identity`. It reproduces **identically on `origin/develop`'s tip
alone** (`git archive e20e9f52ea94` into a scratch tree → same single offender), and
this branch's delta against develop touches no `packages/*/src` file
(`git diff --numstat e20e9f52ea94 HEAD -- 'packages/*/src'` is empty). Banking that
module in `quality/reachability-baseline.json` is develop's call, not this issue's, so
the ledger was left untouched.
