---
inventory-delta:
  packages/maistro-core/tests: +40
---
# M7-A2 Rubric ontology (#791) inventory

Issue #791 registers `Rubric` as a first-class ontology kind bound to a Goal
and adds the Project-scoped, ontology-backed Rubric store.

New tests under `packages/maistro-core/tests`:

- `ontology/test_rubric_model.py` (+16): the `rubric` kind's SEMANTIC model —
  registration + upsert through `InMemoryOntology`, deterministic
  `(rubric_id, revision)` entity ids, scale/weight/method/gate/veto/provenance
  validation, required Goal-binding + scope fields, forbidden extra fields
  (a Rubric is never a score), and the pack catalog's supply-side-only shape.
- `ontology/test_rubric_contracts.py` (+8): contract separation — the persona
  `RubricEval` scorer cannot take over the `rubric` kind and its payload never
  validates as the kind model (and vice versa); CreativeBrief-shaped prose is
  rejected as a Rubric payload, cannot satisfy the kind model, and no
  Design-Studio DTO can swap the registered kind model. The #774
  `CreativeBrief` class itself is not present at this head, so the contract is
  proven against its documented payload shape (`docs/product/DESIGN-STUDIO.md`)
  rather than a class import.
- `projects/test_rubric_store.py` (+15): store invariants — creation without a
  live Goal revision fails; cross-Project and cross-Workspace binds are
  structurally rejected; dimension updates mint new revisions with prior
  revisions still readable; one revision binds exactly one Goal revision;
  Run bindings persist `goal_id` + Goal revision + `rubric_id` + Rubric
  revision and keep naming them after newer revisions exist; pack catalogs
  instantiate Rubrics (deep-copied, provenance `origin="pack"`) without
  owning them and without being persisted.
