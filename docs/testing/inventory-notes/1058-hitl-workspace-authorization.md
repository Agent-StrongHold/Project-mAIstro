---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-core/tests: +2
---
# Issue 1058 - HITL Workspace authorization

Adds end-to-end and core regression cases proving a principal with
`dags.write` can settle an expired pause only in a canonical Workspace where
the principal is a member; a foreign Workspace remains paused. The tests also
pin the membership predicate, effective-principal evidence, and late answer /
cancel behavior after a competing timeout settlement.
