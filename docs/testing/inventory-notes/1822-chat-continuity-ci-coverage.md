---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---
# 1822 chat continuity CI coverage

Diff-coverage follow-up for #1822 / PR #2290: cover the new SessionStore
persist edge paths the coverage gate flagged on the chat continuity branch.

## packages/hive-conductor/backend/tests: +4

- `test_chat_routes.py` (+2): `_history_as_messages` skips unknown roles;
  `append_message` with `system` returns 200 without SessionStore persist.
- `test_chat_run_admission.py` (+2): `_persist_conversation_turn` skips
  non-string model content; swallows `append_turn` failures without raising.
