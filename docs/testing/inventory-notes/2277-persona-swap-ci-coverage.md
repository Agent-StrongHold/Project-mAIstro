---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# 2277 persona swap CI coverage

Diff-coverage follow-up for #2277 / PR #2292: cover GET/PUT and Agent-tool
error paths the coverage gate flagged after the happy-path suite landed.

## packages/hive-conductor/backend/tests: +3

- `test_workspace_agent_persona_routes.py` (+3): GET maps
  `WorkspaceNotFound`/`WorkspaceAgentConflict`; PUT handler authz + service
  failures after the scope gate; tool error returns (no context, invisible,
  non-owner, ValueError, not-found, conflict).
