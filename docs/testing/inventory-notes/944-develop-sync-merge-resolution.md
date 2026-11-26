---
inventory-delta:
  packages/maistro-core/tests: -38
---
# 944-develop-sync-merge-resolution

Develop-sync merge of `origin/develop` (`2dfd3b97a7b815373b401b564d004d519f36dc28`)
into `auto-944`. Develop landed the same M9-G3 feature as PR #2211
("[M9-G3] Add organization/Workspace extension policy, pinning, approval, and
cross-tenant noninterference", `1bdc32dc1`), so the branch's independent
M9-G3 implementation is superseded.

`-38` in `packages/maistro-core/tests`: the branch's superseded M9-G3 module
`packages/maistro-core/tests/extensions/test_extension_policy_governance.py`
(38 collected node IDs at the branch head, verified by
`pytest --collect-only`) is deleted because develop's landed
`packages/maistro-core/tests/extensions/test_org_workspace_policy.py` (+29,
`971-org-workspace-extension-policy`) and
`packages/maistro-server/tests/api/test_extensions_policy_api.py` (+20)
carry the same acceptance criteria against the develop policy engine
(`ExtensionPolicyEngine`, `PolicyDecision`, `TenantScopedExtensionState`).
The branch's `971-extension-policy-governance` note had recorded `+37` for
that module; the 1-node gap is absorbed by compensating deltas elsewhere in
the ledger. No test was weakened: the develop-side module, its server API
suite, and the structural `test_public_surface_union.py` suite remain.
