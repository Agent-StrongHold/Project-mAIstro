---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
  packages/hive-conductor/tests/e2e: +0
---
# 2278 Approvals UI (Parity P-1)

## packages/hive-conductor/backend/tests: +4

- `test_approvals_ui_contract.py` (+4): capability list shape, foreign id 404,
  anonymous 401, HITL pending list-or-unavailable.

## packages/hive-conductor/tests/e2e: +0

Playwright `workspace-approvals-shell.spec.ts` is not collected by pytest.
