---
inventory-delta:
  packages/maistro-core/tests: +0
---
# auto-978: develop-sync conflict resolution + radon debt elimination (+0)

Repair round for #978 in `/home/dev/Git/wt/auto-978` (branch `auto-978`).
No test nodes were added or removed in this round — the recorded suite
inventory is unchanged and `scripts/check-suite-inventory.py` passes
unmodified. This note records what the round actually changed and why.

## 1. Develop-sync conflict resolution (the preserved merge)

The worktree carried an in-progress merge of `34795962548a` (a stale develop
head) with four unmerged paths, and `origin/develop` had since advanced to
`e46ad6708fda` (the lane's declared base). Both merges were completed in
place and committed:

- `fb31a9069` — resolution of the preserved `34795962` merge.
- `b20e136bd` — merge of `origin/develop` (`e46ad6708`).

All four conflicts were additive features from both sides; every resolution
keeps both feature sets:

- `packages/maistro-core/src/_vulture_whitelist.py` — branch's #978
  health-evidence identities (`ExtensionHealthService.record_observation`,
  the store twins' `append_error`) alongside develop's M9-C1/M9-E2/M9-E3
  compat/connector/tool-skill entries.
- `packages/maistro-core/src/maistro/container.py` — branch's
  `extension_health_store`/`extension_health_service` fields and
  `ensure_extension_health_service()` alongside develop's #979 catalog
  fields and `ensure_catalog_service()`.
- `packages/maistro-core/src/maistro/extensions/__init__.py` — health
  exports merged with develop's context/effective-authority/errors/host/
  identity/isolation/lifecycle exports and (second merge) the M9-H3
  certification exports; both the import block and `__all__` keep the
  grouped sort the package already used (constants, CamelCase, snake_case).
- `packages/maistro-core/tests/extensions/test_container_wiring.py` —
  branch's health-service wiring tests and container-level health-store
  backend-selection tests alongside develop's `TestCatalogContainerWiring`.

## 2. Radon ratchet repair (code, not ledger)

After the merge, `scripts/check-radon-baseline.py` (CI args) failed with 4
new C-grade blocks, all in
`packages/maistro-core/src/maistro/extensions/health.py`:
`ExtensionObservation` (C15), its `__post_init__` (C14),
`InMemoryExtensionHealthStore.errors` (C12), and
`ExtensionHealthService.statuses` (C12). None were ever banked — the
correct repair is to eliminate the debt, so the health module was
refactored without behavior change:

- The observation validation chain moved into three module-level helpers
  (`_require_finite_non_negative`, `_require_outcome_error_pairing`,
  `_require_embedded_error_provenance`); every refusal message keeps the
  substring the tests pin (`latency_ms`, `cost_units`, "must carry its
  classified", "cannot carry an error", "does not match the observation's
  identity").
- The in-memory reads share `_read_window` (the one read-limit contract)
  and `_error_in_scope`, so `observations`/`errors` cannot drift apart.
- `status()` uses `_newest_record`; `statuses()` delegates its
  telemetry-only ghost computation to `_telemetry_ghost_identities` +
  `_recorded_identity` (behavior identical, NOT_INSTALLED identities
  unchanged). `statuses()` keeps the inline `max(...)` for its
  provably-non-empty per-extension groups (mypy narrowing).

Gate evidence after the round (all run locally, CI arguments):

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — 1326 reviewed
  identities == 1326 findings, 0 unclassified.
- `uv run python scripts/check-radon-baseline.py` — 137 reviewed blocks ==
  137 findings, 0 new / 0 regressed / 0 stale.
- `uv run python scripts/check-suite-inventory.py` — 17 suites match the
  recorded inventory (this note's delta: +0 everywhere).
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
- `uv run mypy` (AGENTS.md command, 7 packages) — no issues in 875 files.
- `uv run pytest packages/maistro-core/tests/extensions -q` — 906 passed;
  the only 2 failures
  (`test_cli_compat.py::test_compat_preflight_rejects_unreadable_input`,
  `test_cli_certification.py::test_certify_refuses_a_malformed_signing_key`)
  reproduce byte-identically on pristine `origin/develop` (`e46ad6708`)
  in a throwaway worktree — pre-existing upstream rich-wrapping failures,
  not caused by this branch and outside #978's scope.
- `uv run pytest packages/maistro-server/tests -q` — 547 passed, 9 skipped.
- `uv run pytest packages/maistro-ext-harness/tests -q` — 138 passed.
- `uv run python scripts/check-ratchet-provenance.py`,
  `check-shipped-surface-truth.py`, `check-backlog-consistency.py` — all OK.

## 2. Second develop-sync round (current `origin/develop` `d99e598e1`) + #954 integration fix

Round 3 (2026-10-09): merged the advanced `origin/develop` (`d99e598e1`)
into `auto-978`. One conflict, resolved additively:

- `packages/maistro-core/src/_vulture_whitelist.py` — develop's
  `ExtensionInstallService` import alongside the branch's
  `SqliteExtensionHealthStore` import (both modules exist in the merged
  tree; both names stay banked). Merge commit `ae8588ef6`.

**Integration regression surfaced by the merge (fixed):** develop's #954
post-install lifecycle now marks the prior install record's lifecycle
state `SUPERSEDED` on upgrade (`extensions/service.py:_supersede_prior`),
while `extensions/health.py:_is_superseded` only recognized supersession
as "record still `ACTIVE` + active pointer moved". A superseded record
therefore fell through to `_uninstalled_summary` and projected
`NOT_INSTALLED` — falsifying the acceptance criterion that removed/
superseded versions remain identifiable in historical telemetry without
appearing active. Two tests failed post-merge
(`test_superseded_version_is_identifiable_and_never_active`,
`test_detail_can_project_a_historical_version`). Fix in
`extensions/health.py`: the registry's own lifecycle state is canonical
supersession evidence (`record.state is SUPERSEDED`), and
`_superseded_status` stays total when the successor is itself gone
(`active_record=None` → truthful reason string, verdict unchanged).

**Upstream flaky assertions hardened (test-only, count unchanged):** the
two rich-wrapping failures recorded in section 1
(`test_cli_compat.py::test_compat_preflight_rejects_unreadable_input`,
`test_cli_certification.py::test_certify_refuses_a_malformed_signing_key`)
wrap the asserted phrase at a console-width column that depends on the
machine-specific `tmp_path` prefix length. Both now flatten whitespace
before the substring assert — same node identities, same semantics.

### Round-3 validation

- `uv run pytest packages/maistro-core/tests/extensions -q` — 941 passed,
  0 failed (was 939 passed / 2 failed pre-fix).
- `uv run pytest packages/maistro-server/tests/api -q` — 526 passed, 7
  skipped; the four #978 health suites together: 73 passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — exit 0, 1323
  reviewed identities == 1323 findings.
- `uv run python scripts/check-suite-inventory.py` — 17 suites match.
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
- `uv run mypy packages/maistro-core/src packages/maistro-server/src` —
  only the pre-existing `maistro_canvas.py.typed`-absent import note
  (canvas ships no `py.typed`; unrelated to #978).

Inventory delta for this round: +0 everywhere (fix + assertion
hardening only; `check-suite-inventory.py` passes unmodified).

## 3. Third develop-sync round (current `origin/develop` `1f328be96`) — M9-I1 packs

Round 4 (2026-10-10): merged the advanced `origin/develop` (`1f328be96`,
the lane's declared base for this repair round) into `auto-978`. The merge
had been started by the previous attempt and preserved in the worktree with
one unmerged path; it was resolved in place and committed as `b228fbb1f`.

- `packages/maistro-core/src/maistro/extensions/__init__.py` — the only
  conflict: four `__all__` hunks where the branch's #978 health exports
  (`ObservationOutcome`, `OperatorDecision`, `evaluate_health`,
  `latest_decision`, `operator_state_for`) sit alphabetically beside
  develop's M9-I1 pack exports (`PackAsset`…`PackState`,
  `evaluate_pack_compatibility`, `instantiate_*_asset`,
  `pack_extension_view`). Every hunk resolved additively — both name sets
  kept, grouped sort preserved. The import block had merged cleanly (the
  branch's `health`/`sqlite_health_store` imports beside develop's
  `packs` import), and both `health.py` and `packs.py` exist in the merged
  tree. Post-resolution proof: all 317 exported names resolve
  (`hasattr` walk over `maistro.extensions`), zero conflict markers.

### Round-4 validation

- `uv run pytest packages/maistro-core/tests -q` — 15201 passed, 1034
  skipped, 3 xfailed (full core suite, not just extensions).
- `uv run pytest packages/maistro-server/tests -q` — 548 passed, 8 skipped
  (12 #978 health-API tests included).
- `uv run pytest tests/test_check_reachability.py -q` — 25 passed.
- Diff-coverage gate (CI per-file floors, lines 90 / branch arcs 80):
  produced coverage from CI's maistro-core and maistro-server producers
  (branch `--source` over each package's suite), then
  `uv run python scripts/check-diff-coverage.py coverage-gate.xml
  --base 1f328be96…` — ok, every measured file this change touches is at
  or above the floors. Whole-file coverage of the changed production
  files: `__init__.py` 100%, `health.py` 97%, `service.py` 98%,
  `sqlite_health_store.py` 99%, `store.py` 99%, `compatibility.py` 92%,
  `api/extensions.py` 99%.
- `uv run mypy --strict packages/maistro-core/src` — Success, no issues in
  782 files (after installing the `maistro-bootstrap` workspace member the
  worktree venv lacked; the earlier `import-not-found` errors were venv
  artifacts in files this branch does not touch).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — 1323 reviewed
  identities == 1323 findings, 0 unclassified (CI exact args).
- `uv run python scripts/check-radon-baseline.py` — 137 reviewed blocks ==
  137 findings.
- `uv run python scripts/check-reachability.py` — 1394 production modules,
  169 unreachable (unchanged verdict).
- `uv run python scripts/check-suite-inventory.py` — 17 suites match
  (this round adds no test nodes: delta +0 everywhere).
- `uv run python scripts/check-security-inventory.py`,
  `check-shipped-surface-truth.py`, `check-durable-table-inventory.py`,
  `check-workflow-inventory.py`, `check-backlog-consistency.py`,
  `check-extension-imports.py`, `check-api-route-contracts.py`,
  `check-public-routes.py`, `check-route-permissions.py` — all OK.
- `uv run ruff check .` / `uv run ruff format --check .` — clean.

Inventory delta for this round: +0 everywhere (merge-conflict resolution
only; no test nodes added or removed).
