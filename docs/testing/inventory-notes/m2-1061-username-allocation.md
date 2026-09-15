---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
  packages/maistro-core/tests: +0
---

# M2 #1061 canonical username allocation

Four focused tests cover many case-variant writers across two independent SQLite
state writers, rollback of a claim when the user insert fails, quarantine of
historical duplicate usernames, and a mutation guard against restoring the old
scan-then-random-write registration path. The first test is intentionally a
real multi-writer race rather than a process-local lock test.
