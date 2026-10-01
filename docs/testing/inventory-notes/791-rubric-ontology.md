---
inventory-delta:
  packages/maistro-core/tests: +44
---
# M7-A2 Rubric ontology (#791) inventory

Issue #791 registers `Rubric` as a first-class ontology kind bound to a Goal
and adds the Project-scoped, ontology-backed Rubric store.

Provenance note: the 18 vulture identities these tests/modules introduce are
banked in `quality/vulture-baseline.json` (multiplicity-preserving, per the
Counter comparison in `scripts/check-vulture-baseline.py`) and granted in
`quality/ratchet-authorizations.json` (18 vulture + 2 reachability entries,
keyed to the `ontology` CONNECT group and the `projects-rubric-store` LIBRARY
group in `quality/reachability-dispositions.json`), following the repo's
two-merge grant doctrine: grants are read from the base revision, so they
take effect once this branch lands.

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
- `projects/test_rubric_store.py` (+19): store invariants — creation without a
  live Goal revision fails; cross-Project and cross-Workspace binds are
  structurally rejected; dimension updates mint new revisions with prior
  revisions still readable; one revision binds exactly one Goal revision;
  Run bindings persist `goal_id` + Goal revision + `rubric_id` + Rubric
  revision and keep naming them after newer revisions exist; pack catalogs
  instantiate Rubrics (deep-copied, provenance `origin="pack"`) without
  owning them and without being persisted. The +4 over the first draft of
  this note: revision supersession/idempotency/conflict guard tests and a
  run-binding-restarts-over-the-same-ontology test.
