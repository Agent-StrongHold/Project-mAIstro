---
inventory-delta:
  packages/maistro-core/tests: +8
---
# 1098-recovery-ownership-fairness

Eight collected regression tests cover durable Graph queued and due recovery
with a foreign prefix larger than `limit`, assert the owner/admission-source
predicate reaches persistence before the bounded query limit, and exercise the
owner-filtered due query across memory, SQLite, and PostgreSQL contracts.
Existing recovery coverage remains unchanged.
