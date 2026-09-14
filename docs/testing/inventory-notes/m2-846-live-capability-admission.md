---
inventory-delta:
  packages/maistro-core/tests: +3
  packages/hive-conductor/backend/tests: +4
---

# M2 #846 — live capability admission

Adds coverage for the two reachable live-effect bypasses fixed by #846:

- `test_harness_manager.py` proves a harness session re-resolves its provider
  after initialization and that a policy dependency failure denies reported
  actions rather than falling back to allow-all.
- `test_harness_routes.py` drives the real route after disabling the active
  harness capability and proves the later request is unavailable with no fake
  provider call.
- `test_self_repair_routes.py` drives the real self-repair route after
  disabling or revoking `infra_action` and proves no host action request is issued.
- `test_capabilities_wiring.py` proves the production self-repair wiring
  records its host action through the canonical Binding/Invocation context.
- `test_binding_invocation.py` proves an omitted effect policy is an audited
  denial and cannot reach the provider.
