---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
  packages/maistro-core/tests: +1
---
# Issue 1201 — Schedule principal and Workspace scope

Adds conformance cases covering owner-stamped schedule creation and CRUD/manual-fire
enumeration resistance across two principals and Workspaces, revoked automatic-fire
eligibility (both the standalone fallback tick and the production canonical
admission boundary), and separate manual requester versus scheduled actor provenance.

Repair round: added the live two-principal manual-fire HTTP case (an authorized
foreign principal's fire is the route's own enumeration-resistant 404; the owner's
fire stamps actor, requester, and scheduler service identity onto the Run), the
canonical-path Workspace-membership revocation case (`_canonical_scope` refuses an
actor whose membership is gone), and a PostgreSQL `PgScheduleStore` round-trip case
proving `workspace_id`, `project_id`, and `actor_principal_id` survive `put`/`get`,
the project-scoped listing, and a `record_fire` cursor advance. The PG case requires
`MAISTRO_TEST_PG_DSN` and skips like the existing `test_pg_admission.py` live suite.
