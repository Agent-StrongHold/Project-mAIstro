---
inventory-delta:
  packages/maistro-core/tests: +4
---

# Reconciliation usage is representable before its immutable write

The canonical quota conversion now has one shared pure owner, consumed by both
SQLite and PostgreSQL observation and by Invocation reconciliation before it
persists evidence. Out-of-range token counts, token sums and micro-USD cost
conversion are rejected while the Invocation is still UNKNOWN and its hold is
unchanged. Four real SQLite cases cover the previously irreparable APPLIED
settlement failures. Historical oversized usage remains readable and can only be accepted after
valid replacement evidence is supplied. No global deserialization constraint is
added. No numeric range or accounting conflict rule is relaxed.
