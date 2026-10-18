---
inventory-delta:
  packages/maistro-core/tests: +1
---
# Develop-sync merge (origin/develop eec7a5870 into auto-971): Workspace policy name distinctness

The develop-sync merge for #971 resolved a genuine semantic clash: develop's
M9-G1 effective-authority lane (#969) and this branch's M9-G3 org/Workspace
policy lane (#971) both define a `WorkspaceExtensionPolicy` on different
modules (`maistro.extensions.effective_authority` vs
`maistro.extensions.policy`). Following the file's existing dual
`CompatibilityReport` precedent (M9-C1 negotiation vs M9-B2 activation), the
package root keeps the #969 input under the historical name and publishes the
#971 engine's Workspace layer as `WorkspaceExtensionEnablementPolicy`; the
#971 class stays importable as `maistro.extensions.policy.WorkspaceExtensionPolicy`
(the module path every #971 consumer and both server API modules use).

`test_workspace_policy_names_stay_distinct` (in the existing
`test_public_surface_union.py` structural suite) pins that both root exports
exist, resolve to their intended classes, and are not one class re-exported —
so a future sync cannot silently collapse either surface. One new test in the
core suite: **+1**.
