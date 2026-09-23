---
inventory-delta:
  packages/maistro-core/tests: +8
  packages/hive-conductor/backend/tests: +6
---

# M2 #846 — live capability admission

Adds coverage for the two reachable live-effect bypasses fixed by #846:

- `test_harness_manager.py` proves a harness session re-resolves its provider
  after initialization and that a policy dependency failure denies reported
  actions rather than falling back to allow-all.
- `test_harness_routes.py` drives the real route with an explicit policy context,
  proves missing policy fails closed, and proves later send/stream requests are
  unavailable after disabling or revoking the active capability with no fake
  provider call.
- `test_self_repair_routes.py` drives the real self-repair route after
  disabling or revoking `infra_action` and proves no host action request is issued.
- `test_capabilities_wiring.py` proves the production self-repair wiring
  records its host action through the canonical Binding/Invocation context.
- `test_binding_invocation.py` proves an omitted effect policy is an audited
  denial and cannot reach the provider.

Repair pass (auto-846): the fail-closed composition default denied several
pre-existing behavior fixtures that constructed effect contexts without an
evaluator (`test_model_chat_egress.py` setup-hook/structured-output,
`test_governed_model_consumers.py`, `test_providers_routes.py`). Those fixtures
now opt into the explicit `binding_scope_policy` M1 baseline; no test was added
or removed by the repair, so the delta above stays the original #846 split with
`846-live-capability-admission.md` (+2/+2 there, +7/+6 here).

Merge-reconciliation pass (auto-846, develop ffd6fdb16): the incoming Canvas
visual-quality fixtures re-introduced the same pattern —
`test_canvas_model_egress.py` built its effect context without an evaluator and
the shipped fail-closed composition denied the shipped route (proving the
control works). That fixture now also opts into `binding_scope_policy`, matching
the container's composition. One test was added to `test_governed_invocation.py`
(`test_policy_dependency_outage_fails_closed_and_is_audited`): a policy
evaluator that raises produces an audited `invocation.fail-closed` denial with
no provider selection or call — the explicit no-AllowAllGate-fallback proof at
the governed seam. Delta becomes maistro-core +8 / hive-conductor +6.

Merge-reconciliation pass 2 (auto-846, develop 8bb344e32): the develop base
durable-ized Binding persistence (`SqliteBindingStore`/`PgBindingStore`) and
refactored scope checks into the shared `_resolve` helper. Reconciled three
ways without weakening #846:

- `BindingStore` returns to develop's durably-implementable put/get/resolve
  contract; the #846 `register`/`revoke` revocation contract moves to a new
  `RevocableBindingStore` protocol that `InMemoryBindingStore` satisfies and
  durable backends must not silently satisfy until #1133. The effect-context
  seam (`CapabilityEffectContext.bindings`) is typed `RevocableBindingStore`,
  matching the always-in-memory composition and the wiring's `.register` use.
- `InMemoryBindingStore.resolve` re-asserts the revoked pre-check before
  delegating to `_resolve`: a revoked identity is a distinct
  "has been revoked" denial, never merely "is not registered"
  (`test_revoked_binding_cannot_be_recreated_or_resolved` pins this).
- `test_model_chat_egress.py` merges develop's #1091 gateway-credential
  `_effects()` helper with the #846 explicit `binding_scope_policy`
  opt-in; every governed call in that file now runs under both.

No tests were added or removed by this pass, so the delta above is unchanged.
All acceptance-critical tests re-executed after reconciliation: harness
manager deny/disable/revoke/outage set, route-level
`test_shipped_route_without_effect_policy_fails_closed`,
`test_disable_after_route_session_start_makes_send_unavailable`,
`test_shipped_route_factory_rechecks_revoked_binding`,
`test_revoke_infra_action_after_repair_initialization_blocks_effect`, and the
no-AllowAllGate sweep over `packages/*/src` all pass at merge head 4059d1e70.
