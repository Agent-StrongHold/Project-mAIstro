---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
---
# claude-ws-1049-read-time-workspace-attention-projection-ef2c

Adds `packages/hive-conductor/backend/tests/test_attention_projection.py`
(+7) for the read-time Workspace Attention projection (#1049). The tests drive
the real in-memory durable run store, the canonical Workspace authority, and a
real wired Container for the failed-Run source: Workspace isolation between
two members, the missing-Workspace answer for a non-member, deadline-horizon
classification (age alone never promotes), approval pauses as decisions that
name the blocked Run, machine waits excluded, byte-identical store records
after a read, failed-Run error evidence, and the HTTP route's 404/403 posture.
No existing test was removed or changed.
