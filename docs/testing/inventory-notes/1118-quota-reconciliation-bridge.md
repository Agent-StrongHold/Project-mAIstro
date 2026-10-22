---
inventory-delta:
  packages/maistro-core/tests: +9
---

# Invocation reconciliation reaches the quota ledger

The original UNKNOWN observation used immutable `canonical-terminal` evidence
at quota revision 0. Canonical NOT_APPLIED/APPLIED reconciliation then reused
that identity with different bytes, causing QuotaEvidenceConflict and leaving
its reservation unresolved. The new SQLite regression fails on that exact
conflict against the unchanged dependency snapshot.

The original evidence is preserved. A conclusive canonical reconciliation has
one stable `canonical-reconciliation` identity, whose positive quota revision
is allocated once under the existing backend transaction/lock. Replays recover
that recorded revision, so later trusted provider corrections are not overwritten.
INDETERMINATE remains the original unknown accounting fact and keeps its hold.

Seven new SQLite cases cover applied/not-applied/indeterminate outcomes,
normal replay/reattempt, immutable original evidence, provider corrections before
and after settlement, reserved evidence identities, restart repair and concurrent
connections. Two new cases in the existing native PostgreSQL suite cover both
conclusive dispositions and correction ordering. Local PostgreSQL tests require
MAISTRO_TEST_PG_DSN; skips are not native backend evidence.
