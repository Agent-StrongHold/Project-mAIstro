---
inventory-delta:
  packages/maistro-core/tests: +99
---

# 966 — Installable domain-pack contracts over canonical objects (M9-F1)

Adds `packages/maistro-core/src/maistro/extensions/packs.py` (the pack
manifest subtype, version-addressable asset inventory, instantiation rules,
and the `InstallablePackRegistry` side-by-side install/disable surface) and
`packages/maistro-core/tests/extensions/test_pack_contracts.py` (+54 collected
node IDs; the extensions suite goes 153 → 207), plus the four registry verbs
whose only in-tree consumers are this suite whitelisted in
`packages/maistro-core/src/_vulture_whitelist.py` with the
contract-ships-first rationale (the production driver is M9-F3, #968). No
canonical model, store, or gate changes; `quality/*.json` is untouched.

## What the tests actually assert (issue acceptance mapping)

- **AC-1 two out-of-tree packs, side-by-side, canonical objects** —
  `TestSideBySideInstall`: two publisher-namespaced packs install into one
  registry and each instantiates Graph/Persona/Rubric into the same
  Workspace as canonical models with distinct canonical identities; both
  packs' graph assets execute through the real `run_durable_graph` executor
  + `InMemoryDurableRunStore` (the established durable-runs pattern) and
  terminate `COMPLETED` with Run/NodeRun/Attempt lineage intact.
- **AC-2 version-addressable assets with provenance** —
  `TestVersionAddressableProvenance`: assets resolve at exact
  `(asset_id, version)`; multiple versions of one asset stay addressable
  with deterministic highest-version default; instantiated GraphTemplate
  metadata / Persona `source_template_*` + `extension_metadata` / Rubric
  `ProvenanceOrigin.PACK` + `pack_id` all carry publisher, version and the
  manifest digest; same-version reinstalls are idempotent.
- **AC-3 pack-local ids never become canonical ids** —
  `TestCanonicalIdentityWins`: minted `template_id`/`Persona.id`/
  `rubric_id` differ from the pack-local asset ids (which ride only in
  provenance), every instantiation mints a fresh identity, and
  caller-pinned canonical ids are honored.
- **AC-4 disable stops new use, deletes nothing** —
  `TestDisableStopsNewUseOnly`: disable refuses all three instantiation
  paths with the operator note surfaced; the record and its immutable
  manifest snapshot remain queryable unchanged; objects and Runs created
  before the disable still execute and complete afterward; `activate`
  restores new use; disable can pin one version while a sibling version
  stays active.
- **AC-5 dependencies through the M9 machinery** —
  `TestCompatibilityThroughM9Machinery`: `evaluate_pack_compatibility` is
  asserted equal to `evaluate_compatibility(pack_extension_view(m), policy)`
  (the M9 evaluator, not a second resolver); missing dependency, api-major
  mismatch, and unknown range grammar refuse the install with nothing
  recorded; dependencies on another installed pack and on a plain
  extension (capability provider) are satisfied.
- **AC-6 no private executor/store/authority** — `TestNoPrivateAuthority`:
  `executor`/`*_store`/`*_authority`/`permissions` keys are unknown-key
  rejections; an execution-state key (`run_id`) smuggled into a graph
  asset fails inspection through the canonical probe (the R12 runtime-state
  scan runs via a discarded scratch `GraphTemplate`); the registry holds
  only manifest records; rubric provenance names the pack as supplier
  (`authored_by` stays the caller's principal); a pack id outside its own
  publisher namespace is rejected.
- **Fail-closed parse matrix** — `TestManifestInspection`: envelope
  version/kind, unknown/missing keys, publisher-namespaced pack ids, strict
  semver, duplicate capabilities/dependencies/assets, kind-payload
  exclusivity, graph node/edge/entry structural rules, persona/rubric
  payload strictness, and canonical-model refusals (inverted numeric scale,
  veto naming a non-dimension) surfaced as typed
  `PackManifestRejected`.

## Develop-base repair round (+45)

The contracts landed here as a cherry-pick of the #966 branch head onto the
develop line, whose diff-coverage gate (per file: 90% lines / 80% branch
arcs) measured the module's *refusal* branches at 75.8% — the source
branch's suite pinned the happy paths and the headline rejections but not
the rest of the fail-closed surface. The repair round adds exactly those
degenerate paths, each asserted against its own detail fragment:

- `TestInspectionRefusalMatrix` (36 parametrized cases): every remaining
  parse refusal — envelope/identity (empty name, empty assets, malformed
  publisher, malformed dependency shape/id/range, non-list capabilities),
  asset envelope (non-object asset, unknown/missing keys, malformed
  asset_id, kind-payload exclusivity), graph payload (non-object payload,
  unknown keys, non-string description, bad entry_node type, malformed
  node_id, non-string node name, non-list edges, malformed edge pair),
  persona payload (non-object, unknown keys, non-list surfaces, non-object
  defaults), rubric payload (non-object, unknown keys, non-list veto ids,
  non-object dimension, unknown/missing dimension keys, unknown scoring
  method, empty scale, unknown scale keys, extra numeric/pass_fail keys).
  Unknown-key refusals are asserted per section, so a parser that started
  ignoring one section's unknown keys fails that section's case by name.
- `TestInstantiationRefusals` (9 cases): the registry's unknown-pack
  error names the pinned version; blank explicit canonical id, blank
  workspace, and blank rubric scope fields are ValueErrors; wrong-kind
  assets refuse each instantiation path; `PackInstallRecord.provenance`
  is the manifest snapshot's provenance; activating an already-active
  pack is the same record (no spurious transition).

Two mutation spot-checks pin the matrix to reachable behavior (run and
reverted): neutralizing the graph unknown-keys raise fails
`test_each_refusal_names_its_own_reason[<lambda>-unknown graph payload
keys]`, and neutralizing the graph kind-gate fails
`test_wrong_kind_asset_is_refused_for_graph_instantiation`.

## Naming notes future lanes should not undo

- `PackAssetKind.GRAPH_TEMPLATE` (not `GRAPH`) and the string-keyed persona
  payload are deliberate: vulture's name-level matching would otherwise
  mark the banked `graph/types.py::GRAPH` and `personas/model.py::purpose`
  /`style_guidance` findings used and stale three ledger rows this lane
  may not prune (ledger edits are CI-repair-only). Same reason the registry
  reversal verb is `activate`, not `enable` (three banked security-store
  `enable` rows).
- `InstallablePackRegistry` is the in-memory reference authority for the
  contract rules; the Workspace-scoped activation/config/upgrade/disable
  lifecycle over durable storage is #968 and must not grow here.
