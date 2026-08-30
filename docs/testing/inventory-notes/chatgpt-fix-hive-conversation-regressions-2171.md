---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# chatgpt-fix-hive-conversation-regressions-2171

One new test in `packages/hive-conductor/backend/tests/test_chat_routes.py`,
closing the diff-coverage gap this PR opened at 75.0% branch coverage (needed
80%) on `routes/chat.py:146`:

- `test_stream_preserves_caller_provided_system_message` — the two existing
  `/stream` tests only ever sent messages without a `system` role, so the
  "insert a safe system message unless the caller already supplied one"
  check's skip-insert branch was never exercised for the streaming route
  (the non-streaming `/complete` route already tested both branches).
