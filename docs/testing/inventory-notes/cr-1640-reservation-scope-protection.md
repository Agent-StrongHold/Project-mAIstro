---
inventory-delta:
  tests/: +2
---
# CR-1640: a reservation protects its named tasks' declared scope

Suite: `tests/`
Delta: +2 collected cases in `tests/test_plan_delivery.py`
(`test_reservation_protects_its_named_tasks_declared_scope`,
`test_reservation_with_multiple_named_tasks_protects_each_declared_scope`);
no existing tests removed, renamed, skipped or weakened.

Repairs the Codex P2 review finding on the delivery planner (review of
`1c48ec7923`, filed at `tools/plan_delivery.py:248`): collision checking used
only a reservation's own listed paths/resources, so a reservation that names an
active task but spot-checks a narrower path let a higher-ranked unowned task be
selected inside the reserved task's declared scope while the owner's slice went
unselected with its reservation still active — recommending overlapping work.

Fix in `tools/plan_delivery.py` `reservations()`: each reservation's protected
surface is the union of its own scope and every named task's declared
paths/resources, so `recommendation()`'s existing conflict check sees the full
protected surface with no signature change. Both new cases were executed
against the pre-fix planner (`HEAD:tools/plan_delivery.py` loaded from git) and
fail there exactly as the finding describes; they pass after the fix. The
shipped seed carries zero reservations, so its plan output is unchanged, and
selection there stays suppressed by its deliberate incomplete-census flags.

No baseline or workflow change.
