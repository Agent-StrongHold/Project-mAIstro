---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# claude-issue-251-hive-consumer-wiring

Adds one end-to-end scheduler tick test proving the configured Hive scheduler
runs the canonical consumer after `ScheduleRunAdmitter` creates a queued Run.
The core consumer tests cover terminal NodeRun/Attempt execution; this test
covers the production reachability seam that invokes that tick.
