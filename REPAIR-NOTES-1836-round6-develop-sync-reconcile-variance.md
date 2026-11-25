# REPAIR-NOTES-1836 — round 6: develop sync completion (reconcile_variance + security.yml)

Assigned block: "develop sync conflict preserved in worktree; resolve before
verification." Starting head `2c24647c7` carried an in-progress merge with
`ebb5dc030` (a develop ancestor) and two unmerged files; develop's tip
`e12e11288` was not yet in the branch.

## What was done

1. **Merge 1 — `ebb5dc030` (commit `e52291011`).** Resolved
   `scripts/check-image-lock-reconciliation.py` +
   `tests/test_check_image_lock_reconciliation.py`: develop's
   `reconcile_variance()` pure function adopted, but with the branch's
   name-keyed `missing` rule — develop's `required - actual` formula
   false-reports a required pin missing when the image ships that name's
   marker-conditional alternate (executed discrimination: resolution returns
   `[]`, develop formula returns `['widgetlib==1.0']` on the same input).
   Both sides' fork tests unioned; 44 passed.
2. **Merge 2 — `origin/develop` `e12e11288` (commit `e7fb53454`).** One
   conflict, `.github/workflows/security.yml`: kept the branch's detached
   build-cache + per-run `SECURITY_PATCH_KEY` stamp defense over develop's
   one-shot `-r2` scope rotation (supersession noted in the step comment).
   YAML validated. Branch now fully contains `origin/develop`.
3. **ac-state note — no edit needed.** The prior round's finding (banked
   `design_coverage 44.2377` stale after sync) is resolved by the sync itself:
   develop's history carries the `#166` grant authorizing the measured 39.641
   floor, and `check-ac-state.py --run-tests --ratchet` is rc 0 at the merged
   head (floor read from the merge base per the two-merge rule). No
   ledger/grant edits made.
4. **Vulture CI-repair clause — vacuous.** CI's exact scan
   (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) → rc 0,
   1263 identities == 1263 findings. `quality/vulture-baseline.json` not
   amended.

## Validation battery at `e7fb53454` (all rc 0)

ruff check / format --check; targeted pytest (image-lock 44; ac-state,
workflow-inventory, image-pins, image-inventory, suite-inventory suites: 381);
suite-inventory (21 suites match); ac-state `--run-tests --ratchet`; vulture
(CI args); radon; reachability; reachability-dispositions; promotion-surface;
direct-effects; frontend-typed-client; workflow-inventory; image-pins;
branch-protection; merge-markers; ratchet-provenance.

SPEC-101826 golden vectors V-1 … V-18 re-executed at this head: 54/54
assertions pass (v2 recipe inline per the spec; v1 via the unmodified
production `approval_request_digest`; V-18 `DurableApproval` fallback
end-to-end).

Residual: SPEC-101826 remains a Proposed (unaccepted) decision-gate artifact —
owner acceptance on issue #1836 is intentionally open and is the only
non-environmental residual.
