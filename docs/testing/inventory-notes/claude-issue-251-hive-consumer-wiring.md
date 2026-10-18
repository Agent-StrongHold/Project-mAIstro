---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# claude-issue-251-hive-consumer-wiring

Adds one end-to-end scheduler tick test proving the configured Hive scheduler
runs the canonical consumer after `ScheduleRunAdmitter` creates a queued Run.
The end-to-end test uses a real core `Container` and asserts the Run, NodeRun,
and Attempt reach completion; the companion test covers the scheduler's
failure containment, standalone compatibility, and empty-queue paths without
mocking the production call.
