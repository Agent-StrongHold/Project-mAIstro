---
inventory-delta:
  packages/maistro-core/tests: +1
---

# M0 admin-key comparison coverage

Adds one behavioral test that inventories every live `PrivilegeGuard` admin-key authorization decision and proves each decision reaches `secret_equal`.
