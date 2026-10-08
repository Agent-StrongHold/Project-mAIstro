---
inventory-delta:
  packages/maistro-core/tests: 0
  packages/maistro-server/tests: 0
  formal/: 0
---

# auto-966 — resolve the preserved develop-sync conflict, then revalidate #966

Repair round for issue #966 at exact starting head
`021849a407203676730cf060ecaaf2d55f637bc4`. The worktree carried an
interrupted merge of develop commit `34795962548a` with two unmerged paths;
no source work was discarded (salvage-preserved).

## Conflict resolution

Both conflicts were additive import blocks; each resolution keeps BOTH sides.

- `packages/maistro-core/src/_vulture_whitelist.py` — branch side imports
  `InstallablePackRegistry` (the #966 pack contracts); develop side imports
  `ExtensionMeter` / `ExtensionQuotaLedger` / `ExtensionUsageEvent`
  (#2018 metering). Both import statements retained.
- `packages/maistro-core/src/maistro/extensions/__init__.py` — branch side
  re-exports the pack contract surface (`packs.py`); develop side re-exports
  the metering surface (`metering.py`). Both re-export blocks retained.

After committing that merge as `994fb9756`, `origin/develop` had advanced 10
commits past the merged sha; the branch was completed to the round's stated
develop base `2b23303f72f0` with a second, conflict-free merge `c1492fff1`.
Quality ledgers were diffed against `origin/develop` after both merges
(`git diff --numstat origin/develop -- quality/`): identical except the
branch's own new `quality/ac-state-notes/auto-966.json` — no rows lost.

## Validation (all run on merged head `c1492fff1`)

- `uv run ruff check .` — All checks passed.
- `uv run ruff format --check .` — 3184 files already formatted.
- `uv run pytest packages/maistro-core/tests -q` — **14779 passed**, 1001
  skipped, 1 xfailed, 0 failed (a first pass showed 2 failed / 202 errors in
  workspaces store-conformance fixtures that did not reproduce on rerun and
  left no FAILED lines; treated as environmental fixture flakiness).
- `uv run pytest packages/maistro-rsi/tests -q` — 1323 passed, 4 skipped
  (develop's new research harnesses).
- `uv run pytest packages/maistro-core/tests/extensions -q` — 968 passed
  (the conflicted package's own suite).
- `uv run pytest packages/maistro-core/tests/extensions/test_pack_contracts.py -q`
  — 123 passed (issue #966 acceptance suite, unchanged by the sync).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — 1326 reviewed identities
  matched, exit 0 (CI-exact arguments; no ledger amendment needed).
- `uv run mypy packages/maistro-core/src packages/maistro-server/src
  packages/maistro-turing/src packages/maistro-canvas/src
  packages/maistro-bootstrap/src packages/maistro-registry/src
  packages/maistro-ext-sdk/src` — Success: no issues in 874 files.
- Script gates: check-merge-markers, verify-monorepo-layout,
  check-radon-baseline, check_enumerations, check-workspace-retirement,
  check-route-permissions, check-principal-identity,
  check-frontend-typed-client, check-reachability, check-doc-links,
  bump_version --check, check-release-consistency,
  check-backlog-consistency, check-suite-inventory — all exit 0.

## Acceptance standing of #966 after the sync

The pack-contract suite still proves every acceptance criterion:

- side-by-side install + canonical instantiation:
  `test_two_publishers_install_into_one_registry`,
  `test_both_packs_instantiate_canonical_objects_into_one_workspace`,
  `test_pack_graph_assets_execute_the_canonical_spine`;
- version-addressable assets with publisher/version provenance:
  `test_assets_resolve_at_exact_declared_versions`,
  `test_instantiated_objects_carry_publisher_and_version_provenance`;
- pack-local IDs never become canonical IDs:
  `test_pack_local_ids_never_become_canonical_object_ids`;
- disable stops new use, deletes nothing:
  `test_disable_refuses_every_instantiation_of_that_pack`,
  `test_disable_deletes_nothing`,
  `test_objects_instantiated_before_disable_survive_untouched`;
- dependencies via the M9 evaluator:
  `test_resolution_is_literally_the_m9_evaluator`,
  `test_a_disabled_pack_does_not_satisfy_dependencies`;
- no private authority smuggled in:
  `test_the_manifest_schema_has_no_authority_field`,
  `test_execution_state_cannot_smuggle_into_a_graph_asset`,
  `test_instantiation_is_pure_and_persistence_stays_canonical`.

No test was added or removed in this round (delta 0).
