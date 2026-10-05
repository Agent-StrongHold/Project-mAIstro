---
inventory-delta:
  packages/maistro-core/tests: +2
---

# PostgreSQL rejects provider claims on canonical evidence identities

Two native PostgreSQL cases pass nonzero revisions with `canonical-terminal`
and `canonical-reconciliation` evidence identities to the trusted provider
reconciliation entry point. Both must raise the reserved-identity error before
changing the existing reservation or allocation, releasing its hold, or
persisting evidence.

Local validation covers collection and a pure pre-database rejection probe.
Native PostgreSQL execution requires the CI test database; local checks do not
claim native backend coverage.
