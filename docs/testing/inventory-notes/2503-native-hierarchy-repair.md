---
inventory-delta:
  tests/: +19
---
# #2503: native issue hierarchy reconciliation and workflow-authority tests

Root suite delta for this PR:
- `tests/test_reconcile_issue_hierarchy.py`: 16 pytest nodes, including four
  parameterized invalid-graph cases, plus successful planner and write semantics,
  idempotency, actor-safe dry-run, stale state, capacity and depth refusals.
- `tests/test_check_workflow_inventory.py`: 3 pytest nodes for the distinct
  MANUAL_MAINTENANCE disposition, required operator controls and refusal of
  event-triggered write maintenance.

The test IDs were counted from the declared parameterization and must be
confirmed by `python scripts/check-suite-inventory.py --suite tests/` on the
PR's final candidate head. No inventory baseline changes, weakened gates,
skips, xfails or production runtime changes are authorized.
