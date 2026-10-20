---
inventory-delta:
  packages/maistro-server/tests: +2
---

# auto-1095-admin-rate-limit

Two rate-limit integration tests for admin-only deployments (API_KEYS empty,
ADMIN_API_KEYS set): a valid admin bearer keys the principal bucket, and an
invalid bearer falls back to the client IP. Closes the test-coverage gap
called out for #1095's admin-only rate-limit path.
