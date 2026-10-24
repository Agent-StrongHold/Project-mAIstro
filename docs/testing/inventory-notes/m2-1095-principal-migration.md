---
inventory-delta:
  packages/maistro-server/tests: +4
  tests/: +6
---

# m2-1095 principal parsing and ownership migration

The API auth suites now cover the canonical first-colon contract: `ops:admin:token`
remains a user credential with secret `admin:token`, `alice:admin:` is rejected at
startup, and administrator authority is granted only by `ADMIN_API_KEYS`. The
root mirror keeps the shipped-image contract aligned.

The migration contract suite checks the Alembic head merge, durable identity
mapping, conflict-safe Workspace/Project and strike merges, principal-labelled
rate-limit state, and Run/event ownership references. The SQL migration is
transactional under the existing entrypoint advisory lock; database integration
coverage still requires a PostgreSQL service.
