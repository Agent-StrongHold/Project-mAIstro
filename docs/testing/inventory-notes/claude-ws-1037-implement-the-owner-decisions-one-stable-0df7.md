---
inventory-delta:
  packages/hive-conductor/backend/tests: +28
---
# claude-ws-1037-implement-the-owner-decisions-one-stable-0df7

#1037 slice: stable Workspace Agent identity and per-user default Workspace
(ADR-092326-7ed7). All +28 node IDs are new, and no existing test was moved,
renamed or removed:

- `tests/test_workspace_agent_identity.py`: 13 node IDs (10 functions, one
  parametrized over 4 malformed persona ids). They cover a stable id per
  Workspace, ten concurrent first calls, persona swap keeping the id, a swap
  racing first materialization, refusals for a missing, deleted or foreign
  Workspace, chat-id squatting, roster hygiene, and a SQLite restart leg.
- `tests/test_default_workspace.py`: 15 node IDs. They cover:
  - first creation, concurrent and later calls, and per-user isolation;
  - deleted, revoked and demoted defaults, including a revoked default that
    stays retired after the caller is re-added;
  - a skipped unreadable claim and a blank-principal refusal;
  - a durable claim lost to another process, both when the winner can be
    composed here and when it cannot (retryable, no duplicate);
  - a SQLite restart leg;
  - `POST /v1/workspaces/default`: repeat-call identity, its
    `workspaces.write` gate refusing a daily account, and a scanner outage
    mapped to 503.
