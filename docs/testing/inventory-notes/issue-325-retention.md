---
inventory-delta:
  packages/maistro-core/tests: +6
  tests/: +3
---
# Issue 325 retention inventory and raw usage purge

The two quota tests exercise the durable raw-to-aggregate boundary, the exact
expiry boundary, bounded progress, and scope-isolated legal holds. The third
proves that repeated bounded purges aggregate exactly the deleted batch, so
survivors of a bounded sweep are never re-aggregated and double-counted. The
three inventory tests cover the real migration inventory plus missing-field and
duplicate-entry failures in the CI checker. Existing Run retention evidence is
recorded in `m2-1175.md`; this note does not re-count those tests.
