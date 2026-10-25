---
inventory-delta:
  tests/: +0
---
# 1838-image-lock-reconciliation-beartype-split

## What moved

CI-repair for the L1838 lane (issue #1838, branch `auto-1838`): the
`security.yml` `containers` job — "Container scan + SBOM + cosign" — failed at
head `08dfd6f25b0fec7e50f40e1176c1cd96ece61a11` in its "Reconcile installed
packages to uv.lock" step (CI run `40097563262`, job `120882902208`):

```
image maistro-engine:pr-2269 does NOT reconcile to the lock:
  version mismatch     : beartype==0.22.9 (image) != beartype==0.23.1
```

The image was right and the gate was wrong. The #1838 round-5 lock change
upgraded `fastmcp` 4.0.11→4.1.3, whose resolution splits `beartype` by
interpreter (`0.22.9 ; python_full_version < '3.15'`, `0.23.1 ; >= '3.15'`)
via `py-key-value-aio` → beartype. `uv export` lists both entries; pip's marker
evaluation on the image's python 3.13.16 correctly installs `0.22.9`. But
`scripts/check-image-lock-reconciliation.py` keyed its expected pins by
canonical name, so the later export line overwrote the earlier one and the
gate compared the image's legitimate `0.22.9` against the `0.23.1` alternative
only — a red reconciliation for an image that shipped exactly the locked set.

`beartype` is the only multi-version name across all four CI reconciliation
exports on this tree (engine, hive-conductor, research, rsi-runner), so fixing
the gate's parser covers every invocation of the step.

## Repair

`parse_expected` now returns conditional pins grouped by name (every
alternative kept), and the reconcile step accepts a shipped split name against
ANY of its locked alternatives — the image's interpreter decides which marker
applies, and each alternative is a version the lock prescribes for some
environment the scanners audit. A version the lock never named is still a
named version mismatch, reporting every alternative it was measured against.
The gate's documented lenient-conditional contract ("matches either way — its
version is still checked when it does ship") is unchanged in strength for
single-version names; the defect was the last-line-wins collapse, not the
leniency.

## Superseded by the origin/develop sync (round 9): delta now +0

The round-8 tests above carried `tests/: +3`. The subsequent
`origin/develop` sync (`f956a8142`, PR #2285) landed an **independent fix of
the identical defect** under issue #1182, with its own tests and inventory
note (`1182-image-lock-split-resolution.md`, `tests/: +5`). The sync conflict
on `scripts/check-image-lock-reconciliation.py` and
`tests/test_check_image_lock_reconciliation.py` (the only two files both
sides touched since merge-base `4de7e906d`) was resolved by taking develop's
canonical implementation and test file verbatim:

- Behavior is equivalent: both sides keep every marker-conditional
  alternative of a split name, reconcile a shipped split name against any of
  its locked versions, and still reject a version the lock never named.
  Develop's side additionally keeps
  `test_split_resolution_leaves_single_pin_skews_and_requirements_alone`
  (single-pin report format pinned).
- The round-8 tests (`+3`) are the same regressions with a different internal
  shape (`parse_expected` returning a name→set dict; `a or b` mismatch
  format) and are fully covered by develop's five. Keeping both would
  double-count one regression in the suite inventory.
- The round-8 implementation remains reviewable at `475f42562`.

Net effect: this note's delta is `tests/: +0`; the surviving split coverage
is owned by `1182-image-lock-split-resolution.md` (+5).

## Historical record: the original +3 node IDs

`tests/test_check_image_lock_reconciliation.py` (superseded by develop's
variants, same three regressions):

- `test_parse_expected_keeps_every_version_of_a_python_version_split` — the
  split export (hash continuations included) parses to both alternatives.
  → develop: `test_parse_expected_keeps_every_version_of_a_split_resolution`.
- `test_python_version_split_reconciles_the_interpreter_appropriate_pin` —
  the CI regression reduced: split lock + image on the `< 3.15` side
  reconciles exit 0.
  → develop:
  `test_split_resolution_reconciles_with_whichever_branch_the_image_resolved`.
- `test_python_version_split_still_rejects_a_version_the_lock_never_named` —
  the lenient comparison is not a waive: `0.19.0` (never locked) skews,
  naming both alternatives.
  → develop: `test_split_resolution_still_fails_on_a_version_neither_branch_pins`.

## Structural regression proof (round 8, branch implementation)

All four split tests failed against the pre-fix parser (old parse collapses
the beartype alternative set to the last line; old reconcile compares against
`0.23.1` only) and passed against the fixed script. Develop's merged tests
were proven the same way in its own round (real-gate/real-Docker evidence in
`1182-image-lock-split-resolution.md`); both are re-proven on the merged tree
below.

## Merged-tree re-validation (round 9)

At the merged head, with develop's script and tests in the tree: the
round-8-style structural proof is re-run — all of develop's split tests fail
against the pre-fix parser (`fe733ae4e` copy) and pass against the merged
tree (see the round-9 repair notes for the executed commands).
