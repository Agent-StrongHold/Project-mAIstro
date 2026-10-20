---
inventory-delta:
  packages/hive-conductor/backend/tests: -2
  packages/maistro-design/tests: -7
---
# 777-remove-dead-design-seams

Removes the #777 DesignEngine injection-seam scaffolding
(`workspace_agent_resolver` / `reconciler_factory` constructor params, the
`WorkspaceAgentResolver` / `ReconcilerFactory` protocols, and the
`get_workspace_agent` / `get_reconciler` accessors) together with the tests
that exercised only those accessors.

Why: the accessors were production-dead — every call site was a test written
to exercise them, and the Conductor injected the resolver without any route or
service consuming it through the engine. Vulture therefore reported both
methods as new `protocol-and-adapter-port` debt (60% confidence), and the
vulture per-identity gate went red. Keeping them is not possible in-branch:
`ratchet_provenance.load_authorizations` reads grants from the merge base, and
no grant for these identities exists on `origin/develop` (the two-merge rule),
so the only green path was eliminating the dead surface. The seam is trivial
to reintroduce alongside its real consumer when the #804/#805/#806 Goal
reconciliation APIs land; until then the stop condition's "no
Design-Studio-private substitutes" is served by not carrying speculative
surface at all.

What moved:

- `packages/maistro-design/tests` −7: the whole of
  `test_engine_workspace_seam.py` (unconfigured-seam failures, resolver
  pass-through, protocol shapes, reconciler factory forwarding) — it tested
  nothing but the removed accessors.
- `packages/hive-conductor/backend/tests` −2:
  `TestTheWorkspaceAgentSeamIsTheRealFrontDoor` in
  `test_design_service_startup.py` (canonical roster row through the seam,
  front-door error propagation) — same subject. The other 26 cases in that
  file (bundled-system registry, importability, prompt stack) are untouched.
