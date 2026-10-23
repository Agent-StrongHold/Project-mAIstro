---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# Issue #65 — exact revision facts

Two regressions exercise the real scoped Goal/Run readers and Conductor's
production inspection seam:

- A sparse newest legacy Goal revision cannot inherit desired/success/stop
  conditions from an older revision. The older facts remain visible only in
  their historical Run provenance.
- Canonical empty condition lists override stale legacy provenance; the scalar
  compatibility fields cannot reintroduce conditions absent from the owner.

Both tests must fail before the projection fix and pass afterward. These are
projection boundary tests, not proof of Goal-producing admission, reconciliation,
or complete Goal discovery. See `docs/testing/auto-65-repair-validation.md` for
validation results and outstanding issue criteria.
