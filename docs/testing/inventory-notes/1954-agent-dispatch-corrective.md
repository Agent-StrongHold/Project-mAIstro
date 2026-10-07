---
inventory-delta:
  packages/maistro-core/tests: +73
  packages/hive-conductor/backend/tests: +35
---
# Restore boot Agent model-backed tool dispatch

Adds 19 Agent identity tests, 54 admitted model/SDK tests, and 35 Hive tool
integration cases. Coverage includes configured authority, logical ToolCall
identity and replay, adapter catalog isolation, deadlines, UNKNOWN outcomes,
request options, and ordinary executor/search compatibility. HTTP is replaced
with MockTransport; Hive integration uses isolated SQLite fixtures.
