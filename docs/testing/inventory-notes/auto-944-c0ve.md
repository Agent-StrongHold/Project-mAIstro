---
inventory-delta:
  packages/maistro-core/tests: +1
---

# auto-944-c0ve

CI-gate repair round. One test added to
`packages/maistro-core/tests/extensions/test_extension_policy_governance.py`:
`test_org_absent_from_a_workspace_scoped_table_denies`.

It closes a hole found by mutation testing during this round, not by a scan.
Deleting the `org {org_id!r} is not registered with extension policy` reason in
`resolve_extension_policy` (policy.py:311) left every other test green: the
existing `test_unregistered_org_denies_everything` resolves against an empty
ledger, where the *Workspace* "not registered" reason already denies, so the two
reasons mask each other. The one table shape where they do not overlap — a
Workspace override recorded with no org policy — cannot be built through
`ExtensionPolicyLedger` (`set_workspace_override` raises "not registered; set
its policy first"), so it is only reachable through the exported pure
`resolve_extension_policy`, which takes whatever table it is handed.

With the reason removed that shape resolves to `enabled=True` with no permission
ceiling and no version pin, i.e. org policy stops being canonical. Verified
directly: restoring the line makes the test pass, deleting it fails this test
and only this test.

No test files were added or removed elsewhere.
