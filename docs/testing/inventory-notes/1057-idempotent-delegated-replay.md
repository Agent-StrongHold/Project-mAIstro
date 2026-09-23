---
inventory-delta:
  packages/maistro-core/tests: +2
---

Issue #1057 repair (merge-forward of develop's task idempotency #1176): two
tests in `packages/maistro-core/tests/tasks/test_idempotency.py` hold the
interaction the merge created between delegated admission identity and the
idempotent replay path.

- `test_a_delegated_retry_replays_the_originating_principal_evidence` — a
  retry under the same explicit key through the claim store hands back the
  receipt that still names the originating user principal plus the service
  principal, delegation id and actor kind, instead of flattening the work
  onto the service credential.
- `test_a_replayed_admission_after_restart_answers_from_the_durable_delegated_receipt`
  — after the in-memory receipt is dropped (restart) while the claim and the
  durable `TaskRecord` row survive, the replayed admission is answered from
  the durable row with full delegation provenance. Uses a session double that
  keeps the merged rows and answers `get`, so the queue's real
  `_persisted_receipt` → `_task_from_record` path runs rather than a stub of
  it.

Also updated in this repair (no test count change): the branch's two Alembic
migrations were renumbered onto develop's chain (`035_task_identity_provenance`
→ `039_task_identity_provenance`, `036_task_receipt_dispatch_inputs` →
`040_task_receipt_dispatch_inputs`) because develop independently minted
revision `035`; `tests/migrations/test_migration_chain.py` now upgrades to the
renumbered revision and the live-PostgreSQL suite (94 tests) was executed
against a real `pgvector/pgvector:pg18` server, including the
pre-provenance-receipts-become-system-work check.

Follow-up merge-forward (develop minted `039_canvas_job_admission_key` after
the first renumbering): the two #1057 revisions were renumbered again onto
the tail of develop's chain — `041_task_identity_provenance` (Revises: 039)
and `042_task_receipt_dispatch_inputs` (Revises: 041) — so the migration
graph keeps a single head. `test_migration_chain.py` upgrades to
`041_task_identity_provenance` for the legacy-receipt system-actor check.
