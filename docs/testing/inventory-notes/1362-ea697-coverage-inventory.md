---
inventory-delta:
  packages/maistro-core/tests: +52
---
# PR 1362: record the incoming coverage repair's tests

Incoming commit `ea697ca4bd9c3cf7ca3b87b94036ee0f668e4bb1` added coverage
cases in six test files without an inventory note. A clean detached worktree
at that exact commit, with no later codec/conformance changes, collected
12,281 core node IDs against the unchanged recorded 12,229. The inventory
script generated the **+52** above in that isolated worktree.

The additions are in `capabilities/test_pg_approval_store.py`,
`capabilities/test_pg_invocation_store.py`, `capabilities/test_pm_polling_nodes.py`,
`capabilities/test_pm_polling_providers.py`,
`quota/test_pg_invocation_quota_boundary.py`, and
`test_effect_context_convergence.py`. Their implementation and behavioral
assertions are preserved. Follow-up commit
`03bbb4200cdcc47ccc9aab51c4c11f6d75924301` supplied the import, regex and
formatting corrections; those incoming fixes are retained unchanged.

This note records incoming work separately from the later real approval-store
and mixed-codec quota conformance additions. It changes no shared baseline,
quality floor, authorization, exemption, or source behavior.
