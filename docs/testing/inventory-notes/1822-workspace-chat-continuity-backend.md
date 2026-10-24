---
inventory-delta:
  packages/hive-conductor/backend/tests: +8
---
# 1822 workspace chat continuity backend

Backend-first slice for #1822: Workspace-scoped conversation session metadata
plus SessionStore transcripts. No second transcript store; legacy
`stores.chat_sessions` is left in place but not auto-migrated.

## packages/hive-conductor/backend/tests: +8

- `test_conversation_sessions.py` (+6): create/list Workspace scope, foreign
  Workspace isolation, append+get roundtrip, turn_id idempotence, optional
  workspace match on `require_owned`, legacy unscoped quarantine.
- `test_chat_session_ownership.py` (−1 net): `_create` now mints a Workspace and
  passes `workspace_id`; Welcome-seed class replaced by empty Workspace list /
  cross-Workspace isolation (−1 case).
- `test_chat_routes.py` (+3): list/create require `workspace_id`; foreign
  Workspace create is 404; append/get assert against conversation_sessions +
  SessionStore rather than `stores.chat_sessions`.
