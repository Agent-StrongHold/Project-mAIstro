---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---

Added two focused inspection tests for issue #1036: a WAITING projection remains
non-terminal and refresh observes canonical recovery to COMPLETED, and the
shared inspection list includes a canonical Run with no Conductor history row.
