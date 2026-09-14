---
inventory-delta:
  packages/maistro-core/tests/events/test_durable_log.py: +2
  packages/maistro-core/tests/persistence/test_sqlite_audit.py: +1
  packages/maistro-core/tests/quota/test_sqlite_usage_log.py: +2
  tests/test_check_retention_inventory.py: +3
---
# Issue 325 retention inventory and raw usage purge

The two quota tests exercise the durable raw-to-aggregate boundary, the exact
expiry boundary, bounded progress, and scope-isolated legal holds. The three
inventory tests cover the real migration inventory plus missing-field and
duplicate-entry failures in the CI checker. Existing Run retention evidence is
recorded in `m2-1175.md`; this note does not re-count those tests.
