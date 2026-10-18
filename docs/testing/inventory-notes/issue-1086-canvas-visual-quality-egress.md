---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
  packages/maistro-core/tests: +2
---
# Issue 1086 Canvas visual-quality egress

The shipped `/v1/canvas/eval` route now has product-composition coverage for a
successful governed quality evaluation and for missing, fabricated, or
unauthorized execution context. The success test builds the egress from the
application engine composition and asserts one completed Invocation carries
the canonical Workspace/Project/Run/NodeRun/Attempt correlation while
preserving JSON score parsing. Refusal tests prove unavailable evaluations do
not return a fake score.

## Salvage repair (post-verify findings)

Two verifier findings were repaired on top of the develop `ba2f1f077` merge:

- **Legacy JSON-mode parity**: `services/canvas_dag.visual_quality_eval` again
  sends `response_format={"type": "json_object"}`. The governed
  `ModelChatRequest` -> gateway payload path carries it through, and
  `test_canvas_route_sends_legacy_json_response_format` captures the provider
  payload through the shipped `/v1/canvas/eval` route to prove the constraint
  survives the governed seam (model, temperature 0.0, stream false included).
- **Disabled Binding**: `Binding.disabled` (and `ModelBindingConfig.disabled`)
  is now a first-class operator kill-switch. `InMemoryBindingStore.resolve`
  raises `BindingDisabled` (a `BindingResolutionError`) before any scope or
  provider work, so the Canvas route answers 503 and the owning Attempt settles
  FAILED — proven by `test_canvas_route_refuses_disabled_binding`. Core
  refusal and bootstrap carry-through are covered in
  `maistro-core/tests/capabilities/test_binding_invocation.py`
  (`test_resolve_of_a_disabled_binding_refuses_instead_of_authorizing`) and
  `maistro-core/tests/test_model_egress_container_composition.py`
  (`test_declared_disabled_model_binding_bootstraps_but_refuses_resolution`).
