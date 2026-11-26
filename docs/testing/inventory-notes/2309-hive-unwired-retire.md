---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# #2309 — RETIRE hive CONNECT leftovers

One pin: `hive-unwired-services`, `hive-pg-persistence`, and
`hive-dag-and-artifact-optimisation` are RETIRE with `replaced_by` (not CONNECT).
Projects onboarding (`routes.projects`) was already mounted elsewhere and is
out of these groups.
