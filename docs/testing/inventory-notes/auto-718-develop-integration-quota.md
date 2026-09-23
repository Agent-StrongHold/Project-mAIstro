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

Also re-ids the lane's quota evidence migration `035 -> 039` (chained after develop's `038`) because the merge left two revisions named `035` and two alembic heads, and adds `quota_invocation_evidence` to the migration-chain catalog test.
