---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/hive-conductor/tests/e2e: +0
---
# 1822 workspace chat continuity UI

Frontend + Home projection follow-through for #1822 after the backend
session index landed.

## packages/hive-conductor/backend/tests: +0

- `test_home_routes.py`: chat section seed rewritten onto
  `conversation_sessions` + SessionStore (same assertions; no new cases).

## packages/hive-conductor/tests/e2e: +0

- No Playwright cases added in this slice. Chat page wires durable
  `/v1/chat/sessions` hydrate, `session_id` on stream, abort-on-switch, and
  `?session=` deep-link from Home.
