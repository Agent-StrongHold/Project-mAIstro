---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
---

# Issue #7: prove disabled JIT at the OAuth callback

Strengthens the existing disabled-JIT test without adding node IDs. Previously
it asserted only `service._jit is None`; it never exercised the refusal named
by the test. The replacement uses a signed, nonce-bound Entra ID token, valid
eligible-group configuration, the real settings/builder/login path, and the
shipped disabled default. It asserts HTTP 401, no Graph membership request,
no new account, identity link, or session, and no JIT decision. The mock IdP
would return an eligible membership if contacted, so activation would admit
rather than accidentally pass on ineligible evidence.

Validation: 39 JIT tests passed; the full backend suite passed (4571 passed,
113 skipped). The scoped inventory gate collected the unchanged 4684 node IDs.
A validation-only external plugin simulated activation bypass inside
`authenticate` while leaving the builder disabled: this test failed at HTTP
303 != 401, proving the new callback assertion detects behavior the previous
configuration-only assertion could not exercise. Root ruff check/format passed.

This is deterministic first-login evidence only, not proof of subsequent-login
entitlement reconciliation or milestone completion. See
`docs/implementation/issue-7-handoff.md`, Round 5, for fresh commands/results.
