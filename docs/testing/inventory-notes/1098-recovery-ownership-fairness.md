---
inventory-delta:
  packages/maistro-core/tests: +14
  tests/: -8
---
# 1098-recovery-ownership-fairness

Eight collected regression tests cover durable Graph queued and due recovery
with a foreign prefix larger than `limit`, assert the owner/admission-source
predicate reaches persistence before the bounded query limit, and exercise the
owner-filtered due query across memory, SQLite, and PostgreSQL contracts.
The repair also covers exclusive due cursors, upgrades a pre-ownership
SQLite run schema while retaining its admission provenance, and exercises both
optional PostgreSQL purge-evidence table branches.

The `tests/` correction records the pre-existing eight-node drift present at
this round's develop tip; no root tests were removed by this repair.
