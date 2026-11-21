---
inventory-delta:
  packages/maistro-core/tests: +13
---
# Canonical Event preflight review corrections (#1135, partial)

Five unit cases reject incompatible consumed column types (four) and a missing
INSERT privilege. Eight real-PostgreSQL cases cover drifted types (four),
SELECT-only and partial-column-INSERT rejection, and success with INSERT granted
only on the 19 consumed columns despite an additive column with no INSERT grant.
The eighth rejects column-level SELECT on only the 19 original columns when an
additive column is not readable, matching runtime SELECT * lookups.

All PostgreSQL cases use the official revision-030 fixture. The existing
positive DML-role/restart/replica case now grants only SELECT and INSERT,
proving unused UPDATE/DELETE privileges are not required. No test is removed or
skipped beyond the existing missing-real-PostgreSQL behavior; CI still requires
the real legs. Application startup performs only SELECT/catalog/privilege
checks and never changes grants, credentials or schema.
