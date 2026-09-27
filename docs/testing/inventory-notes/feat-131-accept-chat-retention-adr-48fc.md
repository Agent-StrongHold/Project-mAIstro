---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# feat-131-accept-chat-retention-adr-48fc

#131's Workspace chat-window sweep adds three hive-conductor behavioral
tests in `test_chat_run_admission.py`: the admitter forgets completed turns
when the turn ends (not only on the next admission), a still-running turn is
not swept, and admission records the request id. No other suite count moved.
