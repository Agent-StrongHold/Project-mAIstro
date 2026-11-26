---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +2
---
# Issue 1058 repair follow-up

Adds regression coverage for SQLite membership revalidation immediately before
serialized HITL settlement, rejection of direct unverified authorization
construction, and refusal to answer a canonical non-HITL pause.
