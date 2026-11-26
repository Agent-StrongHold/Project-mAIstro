---
inventory-delta:
  packages/maistro-core/tests: +37
---
# 971-extension-policy-governance

> **Superseded by the develop-sync merge**: develop landed this feature as
> PR #2211 (`1bdc32dc1`), so the branch's `policy.py` and the
> `test_extension_policy_governance.py` module described below were replaced
> by develop's engine and its own suites during the develop sync. The
> removal is recorded in `944-develop-sync-merge-resolution.md`.

Lands the M9-G3 organization/Workspace extension-policy governance layer
(`packages/maistro-core/src/maistro/extensions/policy.py`): org allow/deny
and publisher approval resolved over Workspace enablement in a fixed,
documented order; server-side exact-version pinning; deterministic,
explainable resolution projected onto the #969 effective-authority
intersection; tenant-keyed extension state with structurally isolated
views; and an append-only policy audit trail. Thirty-seven node IDs in
`packages/maistro-core/tests/extensions/test_extension_policy_governance.py`.

Per-criterion mapping (issue #971 acceptance):

- **organization deny overrides Workspace enable request** —
  `test_org_deny_overrides_workspace_enablement` (the denial reason names
  the override), and end-to-end through #969:
  `test_org_deny_becomes_an_effective_authority_blocker` proves the
  resolution turns into the intersection's package blocker, so a denied
  extension cannot be granted even by an approving caller.
- **version/publisher pinning enforced server-side under concurrent
  callers** — `test_pinning_enforced_under_concurrent_callers` interleaves
  `pin_version` with concurrent resolvers under `asyncio.gather` and asserts
  the invariant *enabled ⇒ the result's own pin admits the version* for
  every observation (structure, not timing), plus `test_version_pin_denies_other_versions`
  / `test_pinned_version_admitted` / `test_no_pin_admits_any_version`, and
  the whole-table-swap invariant in
  `test_concurrent_publisher_pinning_and_policy_swap_stay_consistent`.
  Publisher approval: `test_unapproved_publisher_denied`,
  `test_approved_publisher_admitted`.
- **two Workspaces can enable the same extension with different permissions
  without state leakage** — `test_two_workspaces_resolve_the_same_extension_independently`
  for policy, `test_tenant_views_are_structurally_isolated` /
  `test_org_scopes_are_isolated_too` for tenant-keyed state, and the
  hypothesis property `test_tenant_state_never_leaks_under_mixed_operations`
  which mirrors arbitrary interleaved put/get/pop sequences across two
  Workspaces against per-view models and asserts the other tenant never
  observes a write.
- **policy inheritance/override result is deterministic and explainable** —
  `test_resolution_is_a_pure_function_of_the_table`,
  `test_reasons_follow_the_fixed_layer_order` (allowlist → deny → publisher
  → pin → workspace enablement), ceiling composition
  (`test_workspace_ceiling_intersects_org_ceiling` via
  `test_workspace_ceiling_narrows_org_ceiling`,
  `test_absent_ceilings_leave_the_layer_unstated`,
  `test_workspace_layer_with_no_ceiling_yields_the_request`), and the
  pin-exactness property `test_pin_is_exact_under_arbitrary_versions`.
- **admin inspection and policy audit trail** —
  `test_every_mutation_is_audited_with_actor_scope_and_reason` (monotonic
  seq, actor/scope/reason, per-row table digest),
  `test_audit_trail_is_append_only_and_org_narrowable`,
  `test_mutations_require_actor_and_reason`,
  `test_workspace_override_requires_registered_org`,
  `test_pin_requires_registered_org`,
  `test_table_digest_is_stable_and_content_sensitive`.
- **fail-closed defaults and degenerate paths** — unregistered org deny
  (`test_unregistered_org_denies_everything`), unregistered Workspace
  (`test_unregistered_workspace_denies`), org allowlist exclusion
  (`test_org_allowlist_excludes_despite_workspace_enablement`,
  `test_org_allowlist_admits_listed_extension`), blank org for tenant keys
  (`test_tenant_scope_key_requires_an_org`, `test_view_requires_real_ids`,
  `test_tenant_scope_key_rejects_non_string_workspace`), and the degenerate
  empty-ledger surface (`test_ledger_exposes_its_table_and_views_expose_scope`).
- **composition with the canonical install service** —
  `test_policy_resolution_feeds_install_authority_inputs` drives the real
  `ExtensionInstallService` with the resolution as
  `ExtensionAuthorityInputs.workspace` and proves the org ceiling narrows
  the frozen grant (`network.http` only).
