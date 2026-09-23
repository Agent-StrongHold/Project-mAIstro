---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# claude-ws-1152-canvas-eval-make-a-foreign-canonical-run-2953

`tests/test_canvas_model_egress.py` (#1152). Canvas eval now authorizes a
canonical Run by Workspace membership instead of by who started it.

- Removed `test_canvas_route_refuses_run_owned_by_another_principal`. It
  asserted a 403 for a Run another principal started, which no longer holds:
  a Run started by another member of the same Workspace is now allowed.
- Added `test_canvas_route_answers_foreign_workspace_run_exactly_like_missing_run`,
  `test_canvas_route_gives_admin_no_bypass_of_workspace_membership` and
  `test_canvas_route_lets_workspace_member_evaluate_run_started_by_another_member`.
- Kept `test_canvas_route_refuses_run_without_execution_principal`, rewritten
  to assert the same body a missing Run gets.

Net +2.
