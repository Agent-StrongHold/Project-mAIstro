---
inventory-delta:
  packages/maistro-core/tests: +5
---
# #1156 Learning scope and provenance parity

The learning persistence conformance suite adds three cross-backend round-trip
nodes (one per backend parameter), plus two machine checks requiring
an explicit disposition for each dataclass field and matching SQLite/PostgreSQL
persistence contracts. The existing SQLite upgrade test now also proves that
legacy rows retain NULL scope/provenance storage rather than receiving invented
values.
