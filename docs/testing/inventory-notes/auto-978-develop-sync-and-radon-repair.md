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
