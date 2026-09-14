---
inventory-delta:
  packages/maistro-core/tests: +8
---
# #1156 Learning scope and provenance parity

The learning persistence conformance suite adds cross-backend round-trip, exact
mutation, and scope-isolation nodes (one per backend parameter), plus machine checks requiring
an explicit disposition for each dataclass field and matching SQLite/PostgreSQL
persistence contracts. The SQLite upgrade test proves that legacy rows retain
NULL scope/provenance storage rather than receiving invented values. The repair
also checks case-folded matching and promoted-learning scope parity.
