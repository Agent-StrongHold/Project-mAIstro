---
inventory-delta:
  packages/maistro-core/tests: +30
---

# PR #1276: accepted evidence for successful NodeRuns (#1153)

Adds 21 collected cases in `test_accepted_outcome_required.py`: seven logical
cases across memory, SQLite, and PostgreSQL. These cover missing evidence with
and without output, explicit no-output acceptance, real runtime no-output work,
and unchanged failed/cancelled/timed-out transitions.

Adds nine historical-backfill rejection cases in `test_spine_conformance.py`:
result, error, and logical-status changes are refused across all three backends.
The existing successful-backfill case also checks unchanged lifecycle timestamps.

Existing fixtures are migrated to real completed Attempts and accepted outcomes.
Only historical-row repair fixtures remove evidence directly from stored test
records. The historical traversal entry points now delegate to the canonical
Attempt executor; their parity/restart tests continue to run through that seam.
The step-budget behavior test executes three physical steps to exhaustion; its
separate default-contract test verifies that omitted configuration forwards 256,
without persisting 256 growing histories just to inspect a default value.
