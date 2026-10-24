---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-core/tests: +9
---
# #845 repair: host-resolved principal roles and denied degenerate delegation paths

Nine core tests close the remaining audit gaps on the delegation/elevation
authority boundary:

- Degenerate delegation paths fail closed: a delegated call without a grant id
  is denied, a naive `delegation_expires_at` still expires (read as UTC), a
  grant without `granted_by` provenance cannot authorize, a human principal
  cannot delegate, a principal owned elsewhere cannot spend another owner's
  grant, and an expired grant is skipped.
- A Sentinel composed without a delegation authority denies the handoff
  instead of silently allowing it.
- Execution-mode resolution maps a host BLOCKED tier record to the adapter's
  blocked floor, and any tier that is neither OPEN/ROLE_AUTO nor BLOCKED
  (e.g. SELF_ELEVATION) falls through to the sandbox floor — never to inline
  execution.

These pair with the Hive-side repair that resolves a node principal's roles
from the server-side user store (`_host_principal_roles` in
`canonical_dag_runner`) rather than the request, so the Sentinel tier
intersection sees the roles the host actually assigned.
