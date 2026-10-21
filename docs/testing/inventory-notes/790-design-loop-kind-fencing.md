---
inventory-delta:
  packages/maistro-core/tests: +12
---
# #790 M7-A1 design-loop kind-fencing contract tests

Branch: `auto-790` (to be delivered as `feat/m7-a1-design-loop-adr` off `develop`).
Base: `develop@0fb3dc69ed95d6eec93bbe34f82ebf3c1996b29c`.

## What moved

Added `packages/maistro-core/tests/ontology/test_design_loop_kind_fencing.py` with 12 tests:
3 parametrized fenced-kind cases (`Goal`/`Rubric`/`EvalRun` competing registration →
`KindAlreadyRegisteredError`), 3 parametrized canonical-owner idempotency cases, and 6
single-assertion contract cases covering the single Goal identity (`maistro.goals`,
`goal_id` + `goal_revision`), Goal projection revision recoverability, persona
`RubricEval` ≠ Goal Rubric (ontology ownership + class-level registration fence), and the
no-sidecar-eval-kind invariant. Contract for ADR-092926-7a01 / SPEC-092926-7a01 (#790, M7-A1).

No production module changed; the delta is tests only.

## Fenced kinds are the acceptance surface

The issue's acceptance criterion — "a contract test fails if a product module registers a
competing `Goal`, `Rubric`, or `EvalRun` kind outside the ontology registry" — is
`test_fenced_kind_rejects_product_module_registration` plus the ontology-level guards
(`test_goal_has_exactly_one_canonical_identity`,
`test_persona_module_owns_no_scoring_kind`, `test_no_sidecar_eval_kind_in_shared_ontology`).
The M7-A2 lane replaces the stand-in semantic models with the real registered Rubric
semantics; the guard shape stays.
