---
inventory-delta:
  packages/hive-conductor/backend/tests: +23
---
# claude-ws-1037-implement-the-owner-decisions-one-stable-0df7

#1037 slice: stable Workspace Agent identity and per-user default Workspace
(ADR-092326-7ed7). All +23 node IDs are new, and no existing test was moved,
renamed or removed:

- `tests/test_workspace_agent_identity.py`: 13 node IDs (10 functions, one
  parametrized over 4 malformed persona ids). They cover a stable id per
  Workspace, ten concurrent first calls, persona swap keeping the id, a swap
  racing first materialization, refusals for a missing, deleted or foreign
  Workspace, chat-id squatting, roster hygiene, and a SQLite restart leg.
- `tests/test_default_workspace.py`: 10 node IDs. They cover first creation,
  concurrent and later calls, per-user isolation, deleted and revoked defaults,
  blank principal refusal, a durable claim lost to another process, a SQLite
  restart leg, and `POST /v1/workspaces/default`: the route's repeat-call
  identity, and its `workspaces.write` gate refusing a daily account.
