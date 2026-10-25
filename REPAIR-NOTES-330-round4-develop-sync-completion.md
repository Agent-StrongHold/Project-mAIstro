# REPAIR-NOTES — #330 round 4: develop-sync conflict resolved, sync completed, re-validated

Branch `auto-330`. Incoming lane brief: "develop sync conflict preserved in
worktree; resolve before verification." Starting head `1f6ee2e23` was mid-merge
with `ffc27cc43` (develop) and two unmerged paths:
`scripts/check-image-lock-reconciliation.py` and
`tests/test_check_image_lock_reconciliation.py`.

## Conflict resolution (merge `fa28518ec`)

Both branches had independently fixed the same marker-fork reconcile defect; the
three-way clean-merge regions had already carried develop's simplified
`parse_expected` (per-pin classification) and its richer `_expected_clause`
(`one of A, B (A or B)`). The resolution kept a coherent superset:

- `main()` calls this branch's `reconcile_variance()` (round-3's dedupe);
  develop's equivalent inline copy is dropped.
- `parse_expected` docstring: develop's mechanics paragraph (accurate for the
  per-pin body) with the #330 / merge-queue-run provenance restored.
- Tests: union of both sides. This branch's four marker-fork tests
  (`test_marker_forked_variants_*`, `test_reconcile_variance_is_order_independent_over_forked_variants`)
  plus develop's two (`test_conditional_pin_with_multiple_marker_versions_*`).
  The one exact-equality assertion was extended by the ` (A or B)` suffix so it
  pins the merged `_expected_clause` contract.
- The +2 tests are the exact pair documented by
  `docs/testing/inventory-notes/issue-5-reconcile-multi-conditional-pins.md`
  (`inventory-delta: tests/: +2`), which arrived with the same merge — no
  duplicate delta note needed, and `check-suite-inventory.py` passes.

## Sync completion (merge `8f0653024`)

After the conflict merge, `git fetch` showed three more develop commits
(`db4d3eb09`, `e6ac8c6d4`, `b1c89cdbc` — hive-conductor Workspace Home/Attention
landing work). Merged cleanly; branch is now 13 ahead / 0 behind
`origin/develop` at head `8f0653024`.

## Re-validation at the new head (all executed here, not inherited)

- `uv run ruff check .` → all clean; `ruff format --check .` → 3505 files clean.
- `uv run pytest tests/ -q` → **5845 passed, 139 skipped**.
- `uv run pytest packages/hive-conductor/backend/tests -q` → **3999 passed,
  25 skipped** (develop's new landing/attention tests included).
- Mutation family: `pytest tests/ -k mutation` → **265 passed**; per-file:
  pr_gate/select_tests/diff_scope/critical/baseline/packet_safety 152, plus
  resume/scheduler/aggregate 21.
- Explicit-failure contract, live probe (not just unit tests): a garbage
  baseline file → `::error::mutation baseline is unreadable: …`, **exit 1**.
- `mutation_critical.py --validate` → 8 sources / 7 domains OK; empty changed
  set → explicit "no mutation-critical files in the changed set".
- CI-parity vulture (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`) → 1297 = 1297, exit 0. **No ledger amendment.**
- `check-suite-inventory.py` → 21 suites match; `check-branch-protection.py`,
  `check-workflow-inventory.py`, `check-required-checks.py` → all OK.
- Focused: `pytest tests/test_check_image_lock_reconciliation.py` → **39 passed**
  (the resolved union).

## Not touched

- Every `quality/*.json` ledger (vulture/leadger repair not needed — gates green
  without amendment).
- No gate weakened; no workflow, ownership or policy file edited this round.
- Not re-executed locally (evidence inherited from the round-2/3 records and the
  all-green hosted checks at `1f6ee2e23`): the four real docker image
  reconciliations and the live 5/5 cosmic-ray kill sweep on the #320 module.
