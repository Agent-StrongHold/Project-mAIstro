---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/hive-conductor/backend/tests: +0
---
# Issue #844 Outcome scope parity

The conformance suite now exercises the project axis on every durable Outcome
read family, including feedback listing and aggregates, for both SQLite and
PostgreSQL fixture variants.
