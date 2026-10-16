
# 966 repair round — publisher-slug grammar and non-finite rubric numbers

> **Develop-line round, folded into `966-installable-pack-contracts.md` by the
> 2026-10 develop sync.** In the merged tree the surviving coverage is counted
> in the main note's `inventory-delta` (+125 → +133), so this note carries **no
> delta block**:
> - `test_hyphenated_publisher_slug_is_accepted` — subsumed by the main
>   branch's grammar, where the publisher half reuses `_PUBLISHER_RE`
>   (`^[a-z0-9][a-z0-9._-]*$`) and the name segment allows hyphens too
>   (`test_publisher_slugs_allowed_by_manifests_can_publish` pins
>   `pub-1.my_pack` and the dotted `a.b.my_pack`; the two-segment split and
>   this round's `pack_id name segment must be a slug` refusal were not
>   kept).
> - `test_non_finite_rubric_numbers_are_rejected` — subsumed: the main
>   branch's `test_rubric_payload_is_rejected_fail_closed` covers the same
>   `_require_finite_number` guard including the bool arm and the
>   weight/pass_value/gate numbers.
> - The graph-node missing-keys, literal-integer manifest version, rubric
>   revalidation, and install-order resolution repairs from the later
>   rounds below survive as behavior; the main branch pins them with its own
>   message text (`graph node missing required keys: …`,
>   `unsupported manifest_version:`, pydantic `ValidationError`), and the
>   install-order regression is ported verbatim.

Follow-up to `966-installable-pack-contracts.md` (same module,
`packages/maistro-core/src/maistro/extensions/packs.py`): two P1 review
findings against the pack-manifest parser, each closed with the test that
fails against the regression it names.

- `test_hyphenated_publisher_slug_is_accepted` — pack ids are
  `publisher.name`, and the publisher half now inherits the extension
  manifest's `_PUBLISHER_RE` grammar (`^[a-z0-9][a-z0-9._-]*$`) instead of the
  underscore-only pack-name slug: the established publisher id `pub-1`
  (used across `test_install_store_conformance.py` and
  `test_lock_reinstall.py`) was unable to namespace any pack because
  `pub-1.film_critique` split into segments that `_PACK_SEGMENT_RE`
  refused. The name segment is still slug-validated separately, and the
  two-segment shape and publisher-namespace rules are unchanged. Pinned the
  other way by the pre-existing `acme.film.critique` three-segment refusal.
- `test_non_finite_rubric_numbers_are_rejected` — `json.loads` turns
  `1e400` into `inf`, which the previous `isinstance(value, (int, float))`
  gate passed straight through to Pydantic models constrained only by
  `gt=0`: a parsed rubric dimension carried `weight=inf` into weighted
  scoring. Every pack-supplied scoring number (dimension weight, numeric
  `min_value`/`max_value`, pass-fail `pass_value`/`fail_value`,
  `gate_pass_threshold`) now goes through `_require_finite`
  (`math.isfinite`), and the number-shaped refusals share one message
  family (`... must be a finite number`). The `gate_pass_threshold` string
  case asserts the message change explicitly.

Mutation evidence (run and reverted): against the pre-fix module,
`inspect_pack_manifest` accepted `weight=1e400` with the parsed dimension
weight equal to `inf`, and rejected `pub-1.film_critique` as `pack_id must
be publisher.name (two slug segments)` — both new tests fail there and pass
here.

## Same-round parser-boundary repairs (+3)

Three more review findings against the same fail-closed boundary, each a
typed-refusal leak or silent coercion reachable from manifest bytes alone:

- graph node missing required keys (asserted inside
  `test_graph_payload_structure_is_rejected_fail_closed`, so no new node
  ID) — the graph
  node shape check refused only *unknown* keys, so a node missing
  `node_id`/`node_type` reached `_require_str`'s direct index and a raw
  `KeyError` escaped the documented `PackManifestRejected` boundary
  (untyped server error instead of install refusal). Both required keys are
  now checked explicitly, in the rubric-dimension `missing ... keys` style.
- `test_evidence_required_must_be_a_json_boolean` — `bool()` coerced any
  truthy junk (`"false"` -> `True`), silently inverting a pack-declared
  scoring requirement. A non-boolean `evidence_required` is now refused.
- `test_manifest_version_must_be_a_literal_integer` — `True == 1` and
  `1.0 == 1` let JSON `true`/`1.0` pass the envelope equality check, after
  which the returned snapshot silently normalized the value to the integer
  constant, hiding malformed source data. A non-boolean integer is now
  required before the version comparison.

Probed on the pre-fix module: the node case raised `KeyError: 'node_id'`,
`evidence_required="false"` parsed as `True`, and `manifest_version=true`/
`1.0` were accepted into a snapshot claiming `1`.

## Same-round instantiation/registry repairs (+2)

- `test_instantiated_rubric_revalidates_caller_supplied_counts` —
  `BaseModel.model_copy(update=...)` skips validation, so
  `instantiate_rubric_asset` returned `RubricSemantic` objects violating the
  canonical `ge=1` constraints when a caller passed `revision=0` or
  `goal_revision=0` (probed: both were accepted). The final object is now
  re-validated through `RubricSemantic.model_validate`, and a violation
  surfaces as the path's own `ValueError` boundary, not a raw pydantic
  error. Graph/persona instantiation only update blank-guarded string
  identity fields, so they keep the copy form.
- `test_dependency_resolution_is_independent_of_install_order` —
  `_active_versions` answered dependency resolution with whichever version
  of a pack was inserted last, not the highest active one: installing v1
  after v2 made a `^2.0.0` dependent fail although an active compatible
  version was installed (probed against the old method:
  `dependency conflict: ... active at 1.0.0`). The dependency view now
  selects the highest active version per pack id — the same default
  `_require_record` and the asset lookup already use — and the test pins
  both side-by-side install orders.

## Recorded as deferred at the time — repaired in the CI-repair round

Two review findings were recorded as deferred when this note was written;
both are **repaired in this branch** as of the CI-repair round — see
`966-pack-provenance-snapshot-immutability.md` for the implementation,
the tests, and the mutation evidence:

- Rubric provenance now carries the exact source-snapshot identity
  (publisher, pack version, asset id/version, manifest digest) through
  five optional all-or-nothing `RubricProvenance` fields — a canonical
  model change, but an additive one that leaves every existing
  construction valid, and it is #966's own acceptance ("retain
  publisher/version provenance"), not #968's.
- Manifest snapshots are now anchored to their bytes: persona payload
  trees are frozen recursively, and `PackManifest.asset` resolves every
  use against a pristine re-parse of `raw`, closing the
  `RubricDimension` mutability that cannot be frozen here (canonical
  model) by construction rather than by a #968 store-boundary decision.

The original deferral rationale, kept for the record:

- Rubric provenance carried only `pack_id` (publisher/version/asset/
  digest ride on the GraphTemplate metadata and Persona fields, because
  those canonical models have extension metadata slots). Enriching it means
  extending the canonical `RubricProvenance` model — this slice shipped
  with "no canonical model changes" and the durable per-Workspace pack
  lifecycle that owns version lineage is #968.
- Manifest snapshots freeze the outer dataclasses and tuple, but persona
  payload dicts and rubric `RubricDimension` objects inside them are
  mutable by a caller holding the snapshot. The parse tree is private to
  `inspect_pack_manifest` (never aliased to caller bytes), so this is
  in-process defense-in-depth on the snapshot accessor shape, not an
  external-input path; the right shape (defensive copies vs deep freeze)
  should be settled once, at the #968 store boundary, not patched here.
