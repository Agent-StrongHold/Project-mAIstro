---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# M2 #1099 - rejected HITL attribution

Added one end-to-end test in `packages/hive-conductor/backend/tests/test_hitl_door.py`.
It submits scanner-rejected answers as independently authenticated Alice and Bob,
proves their `hitl_answer_blocked` audit records remain distinguishable, checks
that no successful approval audit is emitted, and verifies raw credential-shaped
input is absent from the response and audit evidence.
