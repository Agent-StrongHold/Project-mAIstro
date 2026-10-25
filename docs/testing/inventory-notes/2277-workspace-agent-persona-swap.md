---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
  packages/hive-conductor/tests/e2e: +0
---
# 2277 Workspace Agent persona swap

## packages/hive-conductor/backend/tests: +7

- `test_workspace_agent_persona_routes.py` (+6): anonymous 401, non-member
  read/write gates, viewer read-only, owner identity-stable PUT, unshaped
  422, Agent-tool parity with the HTTP route.
- `test_scope_coverage.py` (+1): `PUT …/agent` requires `workspaces.write`.
