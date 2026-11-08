---
inventory-delta:
  tests/: +0
---

# Develop-sync merge: reconcile_variance unioned into the image-lock gate (L1836 repair round)

Resolving the two preserved `origin/develop` sync conflicts (merges of
`ebb5dc030` and `e12e11288` into auto-1836) in
`scripts/check-image-lock-reconciliation.py` +
`tests/test_check_image_lock_reconciliation.py`, plus one
`.github/workflows/security.yml` conflict.

## Image-lock gate: develop's refactor, branch's semantics

develop's `af2e36e24` refactored the inline skew logic in `main()` into a pure
`reconcile_variance(required, conditional, actual)` helper (auto-merged into
this tree unconflicted); the branch had independently evolved the same logic
with per-line required/conditional classification and a name-keyed missing
rule. The resolution keeps both parents' intent:

- `parse_expected` keeps the branch's per-line classification (strictly
  stronger: a name carrying one unconditional and one marked line still gates
  presence by name).
- `reconcile_variance` keeps develop's pure-function shape — which develop's
  `test_reconcile_variance_is_order_independent_over_forked_variants` calls
  directly — but its `missing` computation is the branch's name-keyed rule,
  not develop's `required - actual`.

Executed discrimination (in-process, both formulas on the same input
`required={widgetlib==1.0}`, `conditional={widgetlib==2.0}`,
`actual={widgetlib==2.0}`): the resolution returns `missing=[]` (shipping a
name's marker-conditional alternate reconciles), develop's `required - actual`
formula returns `missing=['widgetlib==1.0']` — it would false-fail a correct
image. The branch's
`test_required_name_with_conditional_alternate_is_missing_only_when_absent`
encodes exactly this and discriminates the two parsers; this executes the
parser-swap discrimination a prior round recorded as UNVERIFIED for the
equivalent earlier merge.

Test suite: both sides' fork tests unioned — the branch's `_fork_export`
quartet (per-line classification, both fork directions, single named skew,
conditional-alternate presence gating) plus develop's `_MARKER_FORKED_EXPORT`
quartet (hash-continuation export lines, a parse path `_fork_export` does not
exercise, and the `reconcile_variance` order-independence pin over the
`(a or b)` clause). 44 passed in the file at the merge head.

## tests/: +0 against the recorded inventory

The union adds develop's four node IDs relative to the branch's pre-merge
suite, but develop's landing (`af2e36e24`) already banked the same rows in the
shared inventory baseline, so the recorded count already includes them and the
gate confirms it: `check-suite-inventory.py` reports 21 suite(s) matching with
no delta. `tests/: +0` is recorded to make that explicit; a delta here other
than zero would double-count.

## security.yml: detached cache supersedes the `-r2` rotation

develop's `e12e11288` rotated the rsi-runner buildx cache scope to
`rsi-runner-r2` (PR #2283) against the same stale-cache replay class the
branch had already eliminated by not reading or writing any GHA cache scope
for the scanned build and asserting the per-run `SECURITY_PATCH_KEY` stamp.
The resolution keeps the branch's mechanism (strictly stronger: rotation
severs the class once, detached scope + per-run stamp sever it permanently and
fail loudly on any replay) and records the supersession in the build step's
comment. YAML re-validated post-resolution.

## Executed evidence at the merged head (e7fb53454)

- `uv run pytest tests/test_check_image_lock_reconciliation.py -q` → 44 passed.
- Vulture per-identity ledger, CI's exact arguments
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) → rc 0,
  1263 reviewed identities == 1263 findings; no ledger amendment needed or
  made.
- `check-suite-inventory.py` rc 0 (21 suites match); `check-ac-state.py
  --run-tests --ratchet` rc 0 — the develop sync carries the `#166` grant that
  authorizes the `design_coverage` 39.641 floor from the merge base, so the
  previously stale branch-side bank needed no re-banking; ruff check and
  format --check clean; radon/reachability/reachability-dispositions/
  promotion-surface/direct-effects/frontend-typed-client/workflow-inventory/
  image-pins/branch-protection/merge-markers/ratchet-provenance all rc 0.
- SPEC-101826 golden vectors V-1 … V-18 re-executed at this head (54
  assertions, 0 failures), including v1 digests via the unmodified production
  `approval_request_digest` and the V-18 `DurableApproval` legacy-fallback
  resolution end-to-end.
