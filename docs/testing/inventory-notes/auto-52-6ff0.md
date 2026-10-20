---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# auto-52-6ff0

We added a new test function `test_a_full_run_ceiling_is_backpressure_429_not_a_500` in `packages/hive-conductor/backend/tests/test_design_scope.py` to verify that a full canonical root-Run ceiling results in admission backpressure (HTTP 429 with Retry-After) rather than a server error (500). This test is part of the work for issue #52 to converge Design Studio/Canvas execution onto canonical Graph/Run.

Additionally, we reformatted one test file (`packages/hive-conductor/backend/tests/test_design_service_startup.py`) with ruff to fix formatting issues.
