---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/maistro-core/tests: +0
---

# M2 #1061 canonical username allocation

Three focused tests cover many case-variant writers across two independent SQLite
state writers, rollback of a claim when the user insert fails, and quarantine of
historical duplicate usernames. The first test is intentionally a real
multi-writer race rather than a process-local lock test.
