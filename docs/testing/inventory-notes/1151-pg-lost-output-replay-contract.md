---
inventory-delta:
  packages/maistro-core/tests: +1
---
# #1151: lost Graph output still obeys replay semantics

Extend `test_pg_spine_crash_windows.py::test_lost_success_write_preserves_live_ownership_then_parks`
from one case to PURE and NON_RETRYABLE cases. Both use actual PgRunStore and
PgGraphContinuationStore, an independent recovery pool, and a third fresh pool
for explicit resume after canonical lease reclaim/parking. The injected
pre-commit completion failure occurs after exactly one successful node body.

The original live-owner refusal and parked-history assertions remain. Resume
must retain the cancelled Attempt unchanged, rotate ordinal/identity/fence,
and accept only the new Attempt's committed result. PURE may execute again;
NON_RETRYABLE must record ReplayRefused without invoking the body again, even
though the previous uncommitted runtime result was successful. Canonical Run,
NodeRun and continuation must agree and a repeated recovery tick is a no-op.

This is real PostgreSQL proof at an injected API boundary, not OS-process death
or preservation of the lost output. It adds no recovery authority or disposition
and does not satisfy the parent issue's parked-conflict or total-work-bound
holds. Execution and regression-sensitivity results are recorded in this
round's repair report.
