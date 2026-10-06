---
inventory-delta:
  packages/maistro-core/tests: +27
  packages/maistro-server/tests: +18
---

# 971-org-workspace-extension-policy

#971 (M9-G3): organization/Workspace extension policy, pinning, approval, and
cross-tenant noninterference.

`packages/maistro-core/tests/extensions/test_org_workspace_policy.py` (+27)
carries one cluster per acceptance criterion: deterministic, explainable
resolution (fixed rule order with the full per-rule trace on every decision,
`explain` proven side-effect-free against the audit log); organization deny
overriding a Workspace enable request at the engine and at every install
machine phase it can matter (inspection rejects at the door, authorization
denies terminally, activation raises `ExtensionPolicyViolation` with the
record unchanged); publisher/version pinning enforced server-side, including
eight racing full flows against a pre-existing pin and a linearization test
that pins a policy change never splitting an in-flight activation (the
per-org enforcement window); tenant-keyed config/cache/checkpoint state where
a foreign Workspace cannot bind a handle, cannot observe values, and
org-only scope is its own tenant rather than a wildcard; a Hypothesis
property test interleaving mixed config/cache operations across two
Workspaces with model-checked noninterference of both invocation and state;
and Container wiring (lazy, cached, default engine imposes nothing).

`packages/maistro-server/tests/api/test_extensions_policy_api.py` (+18)
drives the real router: org policy gating the lifecycle over HTTP (including
the acceptance ordering — inspect while allowed, org denies, the Workspace
enable request loses at authorization); pin enforcement and the pinned-ok
happy path; malformed policy bodies rejected 422; admin inspection of both
layers with the published inheritance semantics; the decision dry run with a
full trace writing no audit row; the audit trail recording policy changes
and every enforcement decision, filterable by Workspace; tenant-scoped
configuration with a foreign Workspace observing 404 (never the value); and
the authentication regressions: every new route rejects missing credentials
with 401, Workspace-scoped reads and writes require canonical Workspace
ownership (a non-member's config read is the scope-blind 404, never the
secret), and org-scoped reads stay behind authentication.

All counts collected with `uv run pytest --collect-only -q` per suite via
`scripts/check-suite-inventory.py --update --note 971-org-workspace-extension-policy`.
