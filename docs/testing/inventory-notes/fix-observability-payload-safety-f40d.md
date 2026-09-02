---
inventory-delta:
  packages/hive-conductor/backend/tests: +25
  packages/maistro-core/tests: +15
---
# fix-observability-payload-safety-f40d

Telemetry payload-safety adds observability contract tests in maistro-core
(+15) and hive-conductor backend (+19 for the PR, +6 more for streaming
span-path coverage in test_chat_streaming.py).
