---
inventory-delta:
  packages/maistro-core/tests: +5
---

# 966 CI-repair round — exact rubric provenance and byte-anchored snapshots

Closes the two review findings the salvage round had recorded as deferred
(`966-pack-contract-refusal-repairs.md`, "Reviewed and deliberately
deferred"), which were the reason that round stopped at NEEDS-DEEP-REVIEW.
Both are now repaired in this branch, each with a test proven failing
against the pre-fix module.

## P1 — exact rubric pack provenance (+3 in test_pack_contracts.py, +1 in
test_rubric_model.py)

The canonical `RubricProvenance` grew five optional all-or-nothing detail
fields (`publisher`, `pack_version`, `asset_id`, `asset_version`,
`manifest_sha256`) — additive and defaulting to `None`, so authored
revisions and the in-repo `PackRubricCatalog` adoption path
(`rubric_store.adopt_pack_catalog`, pack_id only) validate unchanged. A
half-stamped provenance is refused (all five come from one immutable
manifest snapshot together, and detail fields require `origin="pack"`).
`instantiate_rubric_asset` now stamps the full snapshot identity, matching
what `GraphTemplate.metadata["pack"]` and `Persona.extension_metadata`
already carried.

- `test_instantiated_objects_carry_publisher_and_version_provenance`
  (extended, not new) asserts the rubric provenance equals the
  graph/persona metadata identity.
- `test_rubric_provenance_distinguishes_pack_versions` — two installed
  versions of one pack stamp different `pack_version`/`asset_version`/
  `manifest_sha256` onto otherwise identical instantiations.
- `test_pack_provenance_details_are_all_or_nothing` (canonical model,
  `tests/ontology/test_rubric_model.py`) pins the shape rule.

Mutation evidence (run and reverted): with the detail kwargs removed from
`instantiate_rubric_asset`, both pack-contract provenance tests fail
(publisher/asset fields are `None` where "acme"/"scene" is asserted).

## P2 — manifest snapshots cannot be mutated into lying about raw
(+2 in test_pack_contracts.py)

- Persona payload trees are frozen recursively at parse time
  (`MappingProxyType` over tuples); `_persona_constructor_fields` thaws
  into fresh plain containers for the canonical `Persona` constructor, so
  instantiation neither reads nor aliases a mutable tree.
- `PackManifest.asset` now resolves against a pristine re-parse of `raw`
  instead of the stored tree. The one canonical-model object inside the
  tree (`RubricDimension`) cannot be frozen by this contract, so every
  *use* is anchored to the immutable bytes `source_sha256` names.

- `test_persona_payload_trees_are_frozen` — in-place assignment raises
  `TypeError`/`AttributeError` at every container level, and a frozen tree
  still instantiates correctly.
- `test_mutating_a_stored_dimension_cannot_serve_wrong_bytes` — mutating a
  stored `RubricDimension.weight` really mutates the snapshot tree, yet
  `asset()` and instantiation answer from the pristine bytes, and the
  stamped digest equals `sha256(raw)`.
- `test_instantiated_objects_never_alias_the_snapshot_tree` — mutating the
  returned canonical objects cannot reach the snapshot (thaw/re-parse make
  every handout a private copy).

Mutation evidence (run and reverted): with `asset()` back on
`self.assets`, `test_mutating_a_stored_dimension_cannot_serve_wrong_bytes`
fails at the `manifest.asset("scene").rubric.dimensions[0].weight == 0.6`
assertion. The frozen-payload test is structural: without `_freeze` the
`pytest.raises(TypeError)` blocks cannot pass.

Net suite delta: `packages/maistro-core/tests` +5 (105→109 in
`test_pack_contracts.py`, +1 in `test_rubric_model.py`).
