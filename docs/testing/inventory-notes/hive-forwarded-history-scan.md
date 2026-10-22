---
inventory-delta:
  packages/hive-conductor/backend/tests: +28
---
# Scan all caller-supplied chat history before model dispatch

Adds 28 parameterized cases in `test_chat_scan_forwarded_history.py` covering
streaming/non-streaming refusal of hostile trailing or no-user assistant/tool/
system messages, benign history, cross-role split payloads, tool-call metadata,
text/node/depth scan budgets, and cancellation before model dispatch.

The pre-existing assistant-history refusal assertion is unchanged. The new
fixture uses the canonical typed Principal, with no added role or permission.
