---
inventory-delta:
  packages/maistro-core/tests: +6
---
# fix-m1-chat-admission-stranded-running-3b7c

Adds `Container.recover_stranded_chat_admissions()` (#338): a new operator
tick that compensates a chat Run stuck RUNNING with no NodeRun after a
process crash between admission reaching RUNNING and `ChatAttemptExecutor`
persisting the turn's first NodeRun.

`packages/maistro-core/tests` (+6): new cases in `test_container_chat_runs.py`
cover the stranded-Run-gets-cancelled case, a still-in-flight Run within its
grace period being left alone, a RUNNING Run that already has a NodeRun
being left alone (a long-running turn, not a crash), scoping to `CHAT_SOURCE`
only, idempotency across repeated sweeps, and the `limit` bound across
multiple stranded Runs in one tick.
