---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# claude-issue-251-hive-consumer-wiring

Adds one end-to-end scheduler tick test proving the configured Hive scheduler
runs the canonical consumer after `ScheduleRunAdmitter` creates a queued Run.
The test uses a real core `Container` and asserts the Run, NodeRun, and Attempt
reach completion; it covers the production reachability seam rather than
mocking the consumer call.
