---
inventory-delta:
  packages/maistro-core/tests: +6
---
# Issue 1062 recovery event failure isolation

Added six collected cases covering the recovery/event boundary:

- Four parameterized Container recovery batches inject compatibility handler
  failures in the first, middle, and multiple positions, plus the all-success
  path. Every reclaimed Attempt still parks its NodeRun and the next tick has
  no active Attempt to strand.
- One EventBus case proves subscriber failures are reported after healthy
  subscribers run instead of being logged as success.
- One canonical publisher case proves persistence failure prevents the
  compatibility projection and propagates to the caller.
