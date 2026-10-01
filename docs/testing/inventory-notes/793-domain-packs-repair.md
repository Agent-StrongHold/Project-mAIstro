---
inventory-delta:
  packages/maistro-design/tests: +7
---

# #793 (M7-A4) repair round — pack-contract boundary tests

CI-repair for the M7-A4 domain-packs branch: the diff-coverage gate named
`packs/registry.py` (86% of changed lines) and `packs/types.py` (77.8% of
changed branch arcs) because the manifest loader's loud-failure paths and the
shape/pack validators' rejecting branches had no tests. This note records the
tests added to `packages/maistro-design/tests/test_packs.py` in the repair; the
original suite delta is recorded in `793-domain-packs.md`.

## What was added

- `TestOneRegistry.test_a_member_without_a_manifest_is_a_loud_error` — a
  `PackId` member whose manifest file is absent fails the whole builtin load
  with `PackManifestError` naming the member (the loader's FileNotFoundError
  branch).
- `TestOneRegistry.test_manifest_text_that_is_not_yaml_is_a_loud_error` —
  unparseable manifest text is the same loud `PackManifestError` through the
  single parse path (the yaml.YAMLError branch of `parse_manifest`).
- `TestOneRegistry.test_a_registry_missing_a_member_reports_it_as_unknown` —
  `get()` on a registry that lacks a member raises `UnknownPackError`
  ("no pack registered under …"), distinct from a name outside the closed
  enum (the KeyError branch).
- `TestContractEdges.test_duplicate_ids_within_a_pack_are_rejected` —
  duplicate `artifact_kinds` and duplicate rubric `dimension_id`s.
- `TestContractEdges.test_shape_with_duplicate_node_ids_is_rejected`.
- `TestContractEdges.test_shape_edge_to_a_node_outside_the_shape_is_rejected`.
- `TestContractEdges.test_shape_entry_outside_the_shape_is_rejected`.

Plus two assertions folded into existing tests: the `PackId` / `ExecuteBackend`
closed enums are disjoint at the member level (AC-5 is typed, not policed by a
validator branch — the never-firable collision branch was removed from
`DomainPack._validate_pack` in the same round), and `pack_graph_template`
metadata now carries `explore_focus` alongside the other pack fields.

## Deliberate scope boundaries recorded

- The removed `assert_no_pack_is_named_after_a_backend` helper had zero
  callers; its invariant is the enum disjointness pinned above.
- The 12 vulture identities this branch banks in
  `quality/vulture-baseline.json` (closed-enum members, the registry's
  route-facing loader/selector methods, the two pydantic model validators, the
  AC-2 `instantiate_rubric_catalog` contract API, and the canonical-node
  `binding_ids` write) are reviewed retained surfaces: their consumers are the
  HTTP route outside the scanned tree, pydantic's validator machinery, or
  dynamic value lookup. A reviewed grant for them must land on the base
  revision first — the exact-debt-ledger gate reports exactly that.
