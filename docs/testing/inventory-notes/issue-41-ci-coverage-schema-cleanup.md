---
inventory-delta:
  tests/: +0
---

# Issue #41 coverage schema cleanup

`tests/migrations` intentionally leaves its configured PostgreSQL database at
base while exercising the migration chain. The PostgreSQL coverage producer
runs durable suites against the same service immediately afterward, so its
migration conftest now removes chain and runtime-provisioned tables and restores
Alembic head at session finish. This adds no collected test identities.

Validated against an isolated PostgreSQL database: the hook ran after
`tests/migrations/test_revision_metadata.py` (2 passed), restored revision
`053`, and recreated `quota_invocation_evidence`; downstream durable admission
and persistence tests passed (96 passed).
