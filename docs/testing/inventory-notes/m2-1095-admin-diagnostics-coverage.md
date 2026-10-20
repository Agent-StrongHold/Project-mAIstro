---
inventory-delta:
  packages/maistro-server/tests: +3
---

# m2-1095 — admin-only diagnostics coverage

Adds 3 unit tests in `packages/maistro-server/tests/api/test_health.py`
for `_admin_diagnostics_authorized` covering the admin-only deployment
configuration (API_KEYS empty, ADMIN_API_KEYS non-empty), an invalid token,
and the auth-disabled case.
