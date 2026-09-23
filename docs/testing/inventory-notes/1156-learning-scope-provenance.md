---
inventory-delta:
  packages/maistro-core/tests: +5
---
# #1156 Learning scope and provenance parity

The learning persistence conformance suite adds the cross-backend round-trip
node (one per backend parameter: memory, SQLite, PostgreSQL) plus two machine
checks requiring an explicit disposition for each dataclass field and matching
SQLite/PostgreSQL persistence contracts. The existing SQLite schema-upgrade
test was strengthened to prove legacy rows keep NULL `team_id`/`source_query`
storage — assertion changes only, no new node IDs.
