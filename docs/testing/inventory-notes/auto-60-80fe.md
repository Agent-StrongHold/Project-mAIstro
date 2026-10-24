---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
  packages/maistro-core/tests: +14
---
# auto-60-80fe

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Hive-conductor +5 and maistro-core +14 are the branch's delegation-authority suite
(#845) plus the fail-closed branch coverage added in this repair round: non-agent
principal, owner mismatch, expired grant, no owning principal, uncarryable
authorization envelope, blank identity fallback, audit grant provenance,
resolve_tier default, the broker host-authority path, and the host-role/host-mode
seams (`_host_principal_roles`, `_host_execution_authority`, `host_user_role`).
