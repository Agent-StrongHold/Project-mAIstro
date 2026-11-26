---
inventory-delta:
  packages/maistro-design/tests: +35
---

# #985 (M7-A9) — thick pack catalogs and artifact payload kinds

`packages/maistro-design/tests/test_packs.py` (+26 net) adds the M7-A9
classes over the #793 pack contract, and the same file's existing contract
fixtures gain the thick fields they now need:

- `TestThickCatalogContract` — the shipped default catalogs are the six
  dimensions #985 names, verbatim (ids, weights, low/high anchors), weights
  sum to exactly 1 per pack and per instantiated `GoalRubricCatalog`
  (`weight_sum`), a catalog whose weights do not sum to 1 is refused at
  manifest load, a dimension may be marked `human`/`deterministic` (the
  canonical `ScoringMethod` vocabulary, defaulting `model_judge`), and
  `artifact_payload_kind` must be one of the pack's own `artifact_kinds`.
- `TestThickCatalogsAsRubricRevisions` — each of the three catalogs
  instantiates onto a live Goal revision as a store-minted Rubric revision
  (provenance `origin="pack"`, pack_id as supplier only, the pack object
  carries no `rubric_id`), the thickness survives the projection into the
  canonical `RubricDimension` (weights, declared method, the fixed 1-5
  anchor scale), editing a catalog's dimensions mints revision 2 while
  revision 1 stays readable, and a retried identical adoption stays
  idempotent on revision 1.
- `TestArtifactPayloadSchemas` — every required field of `ProductSpec`,
  `GameLoop`, and `BookPages` fails closed when missing (and empty/extra
  fields are refused); `BookPages` enforces spreads numbered 1..N with the
  optional `turn` marker; a thesis slot's JSON body persists through its own
  pack into a `PackArtifactRecord` that reads back typed; a pack emitting a
  foreign artifact kind (another pack's payload kind, an undeclared kind, a
  declared-but-unstructured kind, or a payload kind with no registered
  schema) is rejected; and the `PackArtifactKind` vocabulary is closed and
  disjoint from `PackId`/`ExecuteBackend`.
- `TestSameGoalTakesBothCatalogs` — one Goal identity takes the product
  catalog then the book catalog on the same Project: distinct Rubric
  identities and dimension sets, distinct Graph content hashes, and each
  pack persisting its own payload (`ProductSpec` / `BookPages`) on the same
  Goal.
- `TestCanvasStaysABinding` — canvas is a backend binding on `product`,
  absent-but-addable on `book` (adding it changes no pack identity), it
  rides only execute-phase `binding_ids`/template metadata, and it never
  appears as a pack id, artifact kind, or payload kind.
- `TestPacksCannotRegisterCompetingKinds` — a pack-shaped model cannot
  overwrite the canonical `rubric` ontology kind (`KindAlreadyRegisteredError`),
  the pack surface exposes no register/declare-kind API, and no
  `DomainPack` field mints Goal/Rubric/Run identity.

`packages/maistro-design/tests/test_design_loop_proof.py` (+2, several
re-keyed) migrates the M7-A6 proof to the thick product catalog: the planted
failure moves from the retired `claim_evidence` dimension to `authority`
(Authority trail: Anonymous -> Auditable — a claim is auditable exactly when
it cites evidence), the seeded artifact carries the spec fields the five
presence dimensions read, raw scores sit on the declared 1-5 anchor scale,
and the ontology projection keeps the manifest's weights/anchors/method.
The two new tests pin the raw-score scale and the thickness of the
projection itself.

`packages/maistro-design/tests/test_pack_lifecycle.py` (+5) is re-keyed
to the thick catalog (configuration selects `job`/`metric`/`surface`, the
builtin release is 2.0.0 after the defaults change, and the narrowed-catalog
test now also proves the weight provenance rule: a narrowed override keeps
declared weights un-renormalized while the full defaults sum to 1), and
its `TestLegacyThinSnapshotsStillDeserialize` (review P1) pins the
pre-2.0.0 compatibility path: a thin snapshot (no `artifact_payload_kind`
key — impossible under the thick schema, the exact legacy marker)
deserializes with thickness derived deterministically from the thin body
(equal weights with the last dimension absorbing the float remainder,
anchors named on the fixed 1-5 scale, first declared artifact kind as the
payload kind) while identity and dimension ids ride unchanged; a migrated
thin pack fails closed at the judged-emission schema gate (no payload
schema shipped); tampered thin evidence is still refused before
migration; a disabled legacy activation re-enables from its snapshot; and
a seeded 1.0.0 record passes upgrade preflight and lands 2.0.0
end-to-end.

## Reconciliation notes

- The #793 manifests' thin catalogs are *replaced* (the issue's "current
  gap" table), not added to; because manifest defaults changed, every pack
  version moves 1.0.0 -> 2.0.0 (major, per the manifests' own release rule),
  and the lifecycle tests' synthetic releases move with it.
- `proof.py` is not in the issue's "files this lane may modify" list, but it
  reads the product manifest's dimension ids to build the proof Rubric;
  thickening the manifest forces the re-key. The scenario's shape (planted
  failure, redirect, refine, accept, lineage) is unchanged.
- Weights sum to 1 is enforced on the shipped defaults (`DomainPack`
  validator). A Workspace configuration that narrows the dimension set
  instantiates a partial judgment whose declared weights ride unchanged —
  no silent renormalization; `GoalRubricCatalog.weight_sum` makes that
  state visible and testable.
