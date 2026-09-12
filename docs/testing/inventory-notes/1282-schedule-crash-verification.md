---
inventory-delta:
  packages/maistro-core/tests: +10
---
# Schedule winner linkage: process-loss and overlap verification

Additional verification for #1059 on PR #1282, beyond the original +24 delta.

- `tests/runs/test_schedule_winner_linkage.py` expands the existing restarted
  overlap case from SKIP to SKIP, BUFFER_ONE and CANCEL_OTHER on the same
  memory/SQLite/PostgreSQL fixture. This adds six collected cases, preserves
  the existing SKIP assertions, and checks buffering preserves the owed
  occurrence and cancellation is requested against a live recovered winner.
- `tests/persistence/test_schedule_winner_crash.py` adds three PostgreSQL
  process-kill cases, one for each non-overlapping policy. A separate worker
  uses the public admitter, commits the Run, and signals immediately before
  `record_fire`. The parent sends SIGKILL, proves the persisted schedule still
  lacks the winner pointer, then recovers through fresh store objects on a
  different connection and verifies the next overlap decision.
- The same persistence module adds one PostgreSQL race through two separate
  pools and ScheduleRunAdmitter instances, verifying one admitted Run and a
  common schedule cursor, winner pointer and firing count.

The four PostgreSQL-only cases live under `tests/persistence` deliberately:
that is the suite explicitly collected by the existing PostgreSQL 17/18 CI
jobs. A green PostgreSQL job that did not collect a Run-directory test would
not be execution evidence for that test. With no PostgreSQL DSN, the four cases
skip honestly. The process-kill cases also require POSIX SIGKILL.

CANCEL_OTHER assertions cover the admitter's cancellation decision, not a
claim that the admitter itself performs physical cancellation.
