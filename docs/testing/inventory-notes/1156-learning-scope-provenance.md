---
inventory-delta:
  packages/maistro-core/tests: +8
---
# #1156 Learning scope and provenance parity

The learning persistence conformance suite adds the cross-backend round-trip
node (one per backend parameter: memory, SQLite, PostgreSQL) plus two machine
checks requiring an explicit disposition for each dataclass field and matching
SQLite/PostgreSQL persistence contracts. The existing SQLite schema-upgrade
test was strengthened to prove legacy rows keep NULL `team_id`/`source_query`
storage — assertion changes only, no new node IDs.

Repair round additions: `test_sqlite_learnings_custom.py` finalizes the lane
reproduction (three nodes pinning `source_query`/`team_id` through the SQLite
store → `find_relevant` path, including the trigger-key matching semantics),
and the disposition machine-check in `test_learning_contract.py` was reworded
to derive the partition from the two contract frozensets directly — the derived
`LEARNING_FIELD_DISPOSITIONS` dict in src was removed because vulture's
src-only scan cannot see the test consumer and banked it as dead
(exact-debt-ledger); the partition assertion itself is unchanged in power.
