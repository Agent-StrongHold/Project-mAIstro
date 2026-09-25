---
inventory-delta:
  packages/maistro-core/tests: +5
---

Develop-integration repair for #718 (canonical Invocation quota ledger). The merge brought the Invocation lifecycle CAS/reconciliation layer onto the lane's canonical recording hook; these tests pin the at-most-once quota property across both terminal paths and the paths that must record nothing:

- an `UNKNOWN` physical outcome records nothing (no silent zero) until evidence settles it;
- an `APPLIED` reconciliation records the recovered usage exactly once, and re-invoking the settled effect dispatches nothing and adds no second row;
- an `APPLIED` settlement without usage evidence records an explicit unreported marker (`unreported_count`, `usage_complete=False`), never a measured zero;
- `NOT_APPLIED` and `INDETERMINATE` settlements leave the ledger untouched;
- a physically `COMPLETED` call is recorded once and a late duplicate reconciliation report cannot add a second row.

Also re-ids the lane's quota evidence migration twice during the integration — `035 -> 039 -> 041_quota_invocation_evidence` — because both numeric slots collided with migrations develop landed in the same window (its capability-invocation migration, then `039_canvas_job_admission_key`), and adds `quota_invocation_evidence` to the migration-chain catalog test.
