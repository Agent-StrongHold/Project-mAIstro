---
inventory-delta:
  tests/: +1
---
# Issue #890 CI repair — dependency-namespace prune-target pins (+1)

Repairs the two red CI gates at 567a43afe (`test` and `Coverage gate`), which
failed the same four nodes in `tests/test_dependency_namespaces.py`: the branch
had added the second production prune target
(`"doc": "crosshair-tool"` in `PRUNED_IN_PRODUCTION`, with its
`REVIEWED_NAMESPACES` entry) but left the root suite's pins on the
single-target reality stale. Fixed in place, no removals:

- `TestFirstPartyMap::test_prune_targets_are_gate_targets` now pins both
  targets and requires both namespaces reviewed;
- the two `prune_site_packages` result pins (`test_finder_returns_none_when_no_candidate_matches`,
  `test_finder_stem_fallback_without_name_header`) expect one row per target in
  sorted order, with the absent `doc` target as the 0-rows no-op;
- `test_prune_reports_verified_when_the_import_check_holds` asserts the
  absent-target note AND `verified: 2 pruned namespace(s)`.

Net delta: `tests/` **+1 node** (5010 → 5011). The added node,
`TestPruneScript::test_prune_removes_the_crosshair_doc_payload`, is not a
count-balancer: it installs a fabricated crosshair-tool 0.0.111 dist (exact
wheel shape: one `doc/source/conf.py` row plus the `crosshair` import package)
and proves the prune deletes exactly the `doc/` rows, rewrites the RECORD, and
leaves the distribution named for the SBOM. It bites: with the `doc` target
removed from `PRUNED_IN_PRODUCTION`, the payload survives and the test fails.

No other suite count moved. Production code is untouched by this repair; the
only source change is the test file.
