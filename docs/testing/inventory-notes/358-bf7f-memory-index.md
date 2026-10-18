---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---

# #358: mutation-safe legacy memory pagination

Six collected cases added to `test_audit_pagination.py`: two corpus sizes reject
per-page enumeration, replacement/removal/clear update filter indexes, caller
aliases cannot mutate indexed fields or nested detail, initialization/refresh/
insert-once adopt persisted winners, and threaded inserts preserve a cursor walk.
These exercise the actual store type bound in `stores.audit_log`, not a separate
adapter selected only by tests. Existing durable million-row, scope, export and
route tests remain unchanged. Validation and fail-first evidence are recorded in
`docs/testing/358-bf7f-repair.md`.
