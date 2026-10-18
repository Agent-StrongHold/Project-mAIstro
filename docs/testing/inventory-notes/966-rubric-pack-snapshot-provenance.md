---
inventory-delta:
  packages/maistro-core/tests: +1
---

# auto-966 — exact pack-snapshot provenance on instantiated Rubrics (#966)

Salvage round for issue #966 at head `f710627537e5`. The worktree carried the
prior session's uncommitted work; nothing was discarded — it was validated and
committed as-is (one formatting nit the prior session's final write introduced
is fixed by this round's `ruff format` pass over `packs.py`).

## What moved

- `RubricProvenance` (maistro-core ontology) gains five optional snapshot
  fields — `publisher`, `pack_version`, `manifest_sha256`, `asset_id`,
  `asset_version` — so rubrics instantiated from different versions of one
  pack are provenance-distinguishable, matching what GraphTemplate metadata
  and Persona extension metadata already carry. `instantiate_rubric_asset`
  populates all five from the installed manifest snapshot; catalog adoption
  (`RubricStore.adopt`) keeps recording `pack_id` only, because it carries no
  manifest snapshot. No store, gate, or ledger changes.
- Pack-id grammar widened to the publisher alphabet the extension manifest
  already accepts: `_PACK_SEGMENT_RE` now allows hyphens, and `_parse_pack_identity`
  matches `pack_id` as `publisher.` + one slug segment instead of splitting on
  dots — so hyphenated (`pub-1.my_pack`) and dotted (`a.b.my_pack`) publishers
  can name packs under themselves. Three-segment names and ids outside the
  declaring publisher's namespace are still rejected.

## Test delta (+1)

- `TestManifestInspection.test_publisher_slugs_allowed_by_manifests_can_publish`
  (new, +1 node ID): hyphenated and dotted publishers parse their namespaced
  pack ids. Fails at the parent commit — the old grammar rejected
  `pub-1.my_pack` on the segment regex and `a.b.my_pack` on the two-segment
  length check (both proven mechanically against HEAD's exact patterns).
- `TestVersionAddressableProvenance.test_instantiated_objects_carry_publisher_and_version_provenance`
  (extended, no count change): asserts all five snapshot fields on the
  instantiated rubric. Also proven failing at the parent — HEAD's
  `RubricProvenance` is `extra="forbid"` with no snapshot fields, so the
  assertions cannot hold there.

No suite stopped collecting; the drift alarm fired exactly on the +1 above.
