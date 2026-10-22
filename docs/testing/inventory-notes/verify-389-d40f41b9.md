# verify-389-d40f41b9

Independent verification + CI-repair record for lane L389 (#389 — inventory and
eliminate success-shaped no-op API routes) at branch head
`d40f41b90cd29f3e5ca5a8f3435004be49550f16` (develop base `4df9dd9bde4c`,
merge base with origin/develop `e2b2dfa02822`). Moved no test counts.

Prior round's CI failures (at `951864f7a`, pre-merge): exact-debt-ledger,
test, and Coverage gate. This round proves all three gates green on the
current head AND on the synthetic merge the merge-queue will actually build.

## Why exact-debt-ledger failed and why no ledger amendment is needed

At `951864f7a` the branch sat on an older develop. The develop merge
(`d40d45d8f`) plus develop's subsequent pruning of fixed vulture identities
(e.g. `maistro_turing/bridge.py::acomplete`, `runs/model.py::popitem`,
`canvas/store.py::PgCanvasStore`, `reactor.py::is_running`,
`evolve/types.py::{cost_efficiency,diversity_bonus,latency_efficiency}`,
`repo_history.py::failing_tests`, `agents/base.py::_quota_tracker`,
`circuit_breaker.py::release_probe`, `workspaces/model.py::_require_non_blank`)
reconciled the ledger: the branch's `quality/vulture-baseline.json` is exactly
develop's ledger plus the branch's own banked identities, and the 12 rows
develop pruned are gone from the merge resolution. A ledger amendment is
therefore NOT required this round; the gate's candidate bookkeeping
(`candidate_removed`) stays clean on both trees, verified empirically below.

## Executed at the branch head (this round's own runs)

- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — **exit 0** (base `e2b2dfa02822`, candidate
  `d40f41b90cd2`, `1383 reviewed identities -> 1383 findings`,
  `unclassified: 0`, `never_allowlist: 0`).
- `scripts/check-ratchet-provenance.py` — **exit 0** (all ratchets compared,
  incl. the api-route-contract consumer registration).
- `scripts/check-shipped-surface-truth.py` — **exit 0**. Together these are
  the three steps of the `exact-debt-ledger` job (`.github/workflows/
  vulture-ratchet.yml`).
- `scripts/check-api-route-contracts.py` — **exit 0**: 277 handlers scanned,
  15 audited routes registered, 0 canned.
- `scripts/check-diff-coverage.py coverage.xml --base e2b2dfa02822` after the
  two CI-shaped coverage producers (backend suite over the six changed test
  files, 197 passed; `tests/` gate tests, 45 passed) — **exit 0**: 12 changed
  files measured, all ≥ 90% lines / ≥ 80% branch arcs. This is the
  diff-coverage leg of the Coverage gate that previously scored the new gate
  script 0% before `d40f41b90` added its in-process producer.
- `ruff check .` / `ruff format --check .` — pass.
- `pytest` backend: `test_noop_route_contracts.py test_memory_routes.py
  test_quotas.py test_containers_routes.py test_mcp_routes.py` — **145
  passed**; with `test_platform.py` — **197 passed**;
  `tests/test_check_api_route_contracts.py` — **31 passed**.
- `scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/
  tests` — ok (3103).

## Executed on the synthetic merge (what the merge-queue evaluates)

Throwaway worktree `~/Git/worktrees/val-389-merge`, merge of
`origin/develop` (`4df9dd9bd`) + `d40f41b90` → merge commit `802da6bf9d14`
(clean; develop's newer `routes/settings.py`/`routes/rsi.py` edits landed in
disjoint regions from the branch's). On that tree:

- vulture gate — **exit 0** (trusted base `4df9dd9bde4c`,
  `1371 reviewed identities -> 1371 findings`, `unclassified: 0`).
- `check-api-route-contracts.py` — **exit 0** (278 handlers, 15 audited,
  0 canned).
- backend route contracts + `test_settings_durability.py` — **238 passed**.
- `ruff check .` — pass; `tests/test_check_api_route_contracts.py` +
  `tests/test_check_ratchet_provenance.py` — **45 passed**.

The only leg not reproducible locally is the Coverage gate's publish-set
aggregate floor (full multi-package suite); the branch adds no publish-set
source (changed production files are hive-conductor backend + `scripts/`
only), so the floor inherits develop's measured state.

## Acceptance criteria — evidence

- Inventory with intended contracts: `docs/api/route-contract-inventory.md`
  (five-state distinctness table, per-route before/now/owner) +
  machine-checked `quality/api-route-contracts.json` (every entry must resolve
  to a live handler; gate wired at `.github/workflows/ci.yml:131`).
- Implemented against canonical owners or explicit unsupported: settings
  reload re-reads `services.settings_store` (`503` on store failure), audit
  reads `stores.audit_log`, `/settings/quotas` delegates to the one
  `provider_panel`, schedule history reads fire receipts from the audit log
  scoped to authorized Workspaces, memory namespaces/contradict are real
  operations on the owned entry store, quota panels read LiteLLM / the
  canonical outcome store; `containers/build`, `containers/suggest`,
  `mcp/servers/{id}/scan`, `mcp/discover`, `rsi/models` refuse `501`.
- Distinct states: quota envelope `ok`/`no_data`/`unavailable`/`error`,
  `503` unavailable vs `501` unimplemented vs `404` missing/foreign vs
  auth-layer 401/403 — pinned by the tests named above.
- Schema/docs identify preview/unsupported: `/v1/settings/volatile` marked
  "Preview (non-durable)" in OpenAPI summaries; 501 details name the wired
  alternative; `test_openapi_marks_preview_and_unsupported_operations` proves
  the schema contract.
- State-change and seeded non-empty proofs:
  `test_settings_reload_reflects_an_out_of_band_write`,
  `test_contradict_entry_changes_durable_state`,
  `test_settings_audit_returns_seeded_non_empty_data`,
  `test_schedule_history_returns_seeded_non_empty_data`,
  `test_outcomes_returns_seeded_non_empty_data`,
  `test_list_namespaces_derived_from_owned_entries`,
  `test_providers_counts_requests_when_reported`.
- Placeholder CI gate: `scripts/check-api-route-contracts.py` AST-refuses any
  handler whose every return is a pure constant with no call except
  HTTPException, and refuses inventory rot; self-tested in-process by
  `tests/test_check_api_route_contracts.py`.

Residual notes: the three untracked scratch files at the worktree root
(`vulture_output.txt`, `output2.txt`, `full_output.txt`) are identical prior-
round vulture scan summaries, left untouched (salvage, not disposable). The
validation worktree above was removed after the runs; its merge commit SHA is
recorded here for provenance.
