---
inventory-delta:
  tests/: -3
---

# Develop sync (37b649f36 M3-B3): resolve the duplicated image-lock marker-fork fix

Syncing develop's `37b649f36` (M3-B3 Canvas worker — which carries the #93
marker-fork repair of `scripts/check-image-lock-reconciliation.py`) into this
branch auto-merged the gate script to develop's superset (per-name
`LockedPin` lists, `@image-env@` interpreter-environment capture, stdlib PEP
508 marker evaluator, `_expected_clause` full-accepted-set reporting) but
textually unioned the test file: this branch's earlier parallel fix for the
same hosted red had its own test family, written against the superseded
`parse_expected -> tuple[set, set]` surface. The union collected 79 nodes and
3 failed:

- `test_parse_expected_keeps_every_marker_split_version` — unpacks
  `parse_expected` as a `(required, conditional)` tuple; the merged gate
  returns `dict[str, list[LockedPin]]`.
- `test_marker_split_reconciles_whichever_branch_the_interpreter_chose[.22.9]`
  / `[.23.1]` — behavior green (exit 0, lenient acceptance of either fork
  without an env line) but asserted the lane's `2 marker-conditional pin(s)`
  OK-line phrasing, which the merged gate replaced with the fork-degradation
  phrasing (`no @image-env@ line — lenient`).

## Resolution

Keep develop's implementation and test surface (same precedent as this
branch's `93-1182-image-lock-merge-resolution.md`: the env-aware side is the
superset). The three failing nodes are deleted as superseded — every intent
they pinned is already pinned by passing tests on the merged API:

- parse-level fork retention → `test_parse_expected_keeps_every_forked_variant_of_a_name`
  and `test_parse_expected_keeps_every_version_of_a_split_resolution`
  (dict API + three-way `_classify_expected`).
- either-branch reconcile without env + OK phrasing →
  `test_split_resolution_reconciles_with_whichever_branch_the_image_resolved[*]`
  and `test_conditional_pin_with_multiple_marker_versions_accepts_either_branch`.
- The lane's still-green negative path
  (`test_version_outside_the_marker_split_fails_naming_every_branch`, full
  `one of X, Y` clause + no missing/extra pair) and
  `test_marker_split_pin_absent_from_image_still_gates_nothing` (lenient
  degradation gates nothing) are kept, as are the `test_marker_forked_variants_*`
  and `test_reconcile_variance_*` set-shim pins.

Net node count: -3 (79 collected in the union → 76).

## Evidence

- `uv run pytest tests/test_check_image_lock_reconciliation.py -q` — 76 passed.
- `uv run python scripts/check-suite-inventory.py` — before this note:
  `DRIFT tests/: expected 6034, collected 6031` (exactly the 3 deleted
  nodes; all 20 other suites ok, canvas 636 ok). With this note: expected
  6031 == collected.
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
