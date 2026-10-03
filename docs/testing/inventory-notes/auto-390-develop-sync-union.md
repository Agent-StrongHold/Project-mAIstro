---
inventory-delta:
  tests/: +18
---
# auto-390-develop-sync-union

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

## Develop-sync merge union on the root suite (tests/)

The in-flight merge of develop (`b4b9e187e`) into `auto-390` united two test
trees that had each moved the root suite independently. The merged `tests/`
directory is exactly the union of both parents' `tests/` directories (verified
by `git ls-tree` comparison: 226 files on the auto-390 parent, 233 on the
develop parent, 233 in the merge, union == merged, nothing deleted or moved).
The union collects 18 more node IDs than baseline + the summed deltas of both
sides' notes record, because each side's notes were true against its own tree,
not against the union.

The seven develop-side files new to this branch are
tests/security/test_sentinel_permission_table_armed.py,
tests/test_check_closure_targets.py, tests/test_check_image_pins.py,
tests/test_check_principal_identity.py, tests/test_check_route_permissions.py,
and tests/test_check_workspace_retirement.py (plus a shared-file change). No
test was added or removed by this lane; the delta records the merge arithmetic.
