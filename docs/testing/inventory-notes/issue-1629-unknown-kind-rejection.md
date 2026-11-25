---
inventory-delta:
  tests/: +1
---
# #1629: an unknown work kind must not be silently classified

Suite: `tests/`
Delta: +1 collected case in `tests/test_plan_delivery.py`
(`test_unknown_work_kind_is_not_silently_classified`); no existing tests
removed, renamed, skipped or weakened.

Verifier-repair round for the already-merged delivery planner
(#1629/#1640, develop `8e7d7d316547`): the audit of the acceptance criterion
"classify residual slices separately as implementation, integration,
verification, or decision work" found that every other validation branch in
`tools/plan_delivery.py` has a focused adversarial case, but the
`task.kind in {implement, integrate, verify, decision}` rejection had none —
a snapshot with `kind: "refactor"` would take an untested path. The new case
asserts the planner raises `PlanError` ("unknown kind") instead of silently
continuing, matching the issue's reject-rather-than-continue contract.

No production code changed; the existing rejection already behaved correctly.
No baseline or workflow change.
