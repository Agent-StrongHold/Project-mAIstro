---
inventory-delta:
  packages/hive-conductor/backend/tests: +8
  packages/maistro-core/tests: +0
---

# M2 #1061 canonical username allocation

Eight focused tests cover many case-variant writers across two independent
SQLite state writers, rollback of a claim when the user insert fails, release
of a claim and account as one rollback transaction, the live atomic storage
seam, setup rollback after a post-allocation failure, voice
resolution through the canonical quarantine, historical duplicate quarantine,
and a mutation guard against restoring the old scan-then-random-write
registration path. The first test is intentionally a real multi-writer race
rather than a process-local lock test.
