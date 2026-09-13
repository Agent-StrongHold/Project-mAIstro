---
inventory-delta:
  packages/maistro-core/tests/quota: +1
---
# auto-55-pg-quota

- **+1** — `test_pg_invocation_quota_boundary.py` exercises PostgreSQL Invocation quota settlement for known non-dispatch failure, missing usage holds, and trusted provider reconciliation.
