---
inventory-delta:
  packages/maistro-design/tests: +7
---

# #793 (M7-A4) repair round — pack-contract boundary tests

Round 2 (this round) added **no tests**; it recovered the uncommitted round-1
salvage (which CI had never seen), merged origin/develop (28 commits, quality
ledger + uv.lock overlaps resolved), and repaired the exact-debt-ledger and
reachability gates — see "Round 2" at the bottom. Test-suite count is
unchanged at 384 (checked by `scripts/check-suite-inventory.py`).

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

## Round 2 — salvage recovery, develop merge, ledger-gate repair

Round 1's edits (the tests above, the typed AC-5 invariant, the ledger
amendment) were left **uncommitted** on disk when its run died; the driver's
follow-up "orphan rebuild" then half-applied a corrupt `HEAD..origin/develop`
patch to the index. Round 2 salvaged the worktree (backed up under the job
directory), restored the index, committed the salvage, and merged
origin/develop (fa2deb0a4, 28 commits — overlap was exactly
quality/reachability-baseline.json, quality/vulture-baseline.json, uv.lock).

Ledger-gate repair, with the constraint that drove it:

- `check-vulture-baseline.py` judges new debt against the ledger **as of the
  merge base** (`scripts/ratchet_provenance.py`, two-merge rule), so the
  round-1 candidate-side amendment of `quality/vulture-baseline.json` could
  never authorize the 12 pack identities — develop has no packs. The
  references now live in `maistro_design.packs.__init__` (the reachable module
  the Design Studio route imports through), mirroring
  `packages/maistro-core/src/_vulture_whitelist.py`: closed-enum members, the
  route-consumed registry methods, pydantic model validators, the A2
  Goal-instantiation seam, and the canonical `Node.binding_ids` field. A
  standalone loose `_vulture_whitelist.py` was tried and reverted: a second
  top-level stem collides in `check-reachability.py`'s duplicate-module guard,
  and a new unreachable module needs a prior reachability authorization.
- Ledger pruning (count-free ratchet): the 12 pack rows, the 2
  `graph/definitions.py` `binding_ids` rows cleared by the reference, and the
  `agent.py` `phases` row (identity gone in the merged tree).
- `maistro.interop` / `maistro.interop.contract` became reachable in the
  merged tree (develop #997 wired the ontology), so the baseline entries were
  already pruned and the stale `interop-contract` disposition group left
  `quality/reachability-dispositions.json` (its own gate's instruction).

Gates proven this round (exit 0 unless noted):
`check-vulture-baseline.py` (exact-debt-ledger),
`check-reachability.py`, `check-reachability-dispositions.py`,
`check-reachability-dispositions-provenance.py`, `check-ratchet-provenance.py`,
`check-diff-coverage.py --base origin/develop` (design src + conductor backend
producers; test files exempt by declaration), `check-suite-inventory.py` for
both touched suites, `check-radon-baseline.py`, `bump_version.py --check`,
`check-release-consistency.py`, `check-doc-links.py`,
`check_enumerations.py`, `check-shipped-surface-truth.py`, ruff check/format.
Suites: maistro-design 384 passed; hive-conductor backend 3018 passed / 6
skipped; maistro-server 464 passed.
