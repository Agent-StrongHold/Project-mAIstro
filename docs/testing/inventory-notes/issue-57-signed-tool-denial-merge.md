---
inventory-delta:
  packages/maistro-core/tests: +1
---
# Issue #57: preserve signed pre-Sentinel denial evidence

The merge combines the #847 scoped declaration-denial helper with audit signing.
A regression test calls the real helper and in-memory audit sink, requiring one
signed deny record in the caller's organization with tool, principal, and denial
reason intact. It also verifies that the default system-scope read cannot see
that record. This catches a lost helper/runtime AuditEntry import (the guarded
write would otherwise silently retain nothing), and lost signing integration.
