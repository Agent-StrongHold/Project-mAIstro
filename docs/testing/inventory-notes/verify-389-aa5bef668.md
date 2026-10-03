# verify-389-aa5bef668

CI-repair verification + salvage resolution for lane L389 (#389 — inventory and
eliminate success-shaped no-op API routes) at branch head
`aa5bef668a1a987cbbdd0fbf5ddbd94d54719798` (develop base `5765efce8c1f`).
Adds no tests; moves no test counts.

## Triage of the prior CI failures (all at `951864f7a`, the pre-repair, pre-merge head)

Fetched the runner logs for the three failed jobs:

- **exact-debt-ledger** (job 110221589404): `FAIL: ratchet provenance inventory
  is incomplete — check-api-route-contracts.py reads
  quality/api-route-contracts.json from the candidate tree without trusted-base
  resolution or a documented exception`.
- **test** (job 110221589864): two repo-consistency tests —
  `tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
  (`['unclassified...api-route-contracts.json'] == []`) and
  `tests/test_ratchet_provenance_repository.py::test_every_live_ratchet_has_explicit_provenance`
  (`['check-api-r...ed exception'] == []`).
- **Coverage gate** (job 110223363836): the *same two tests* failing inside the
  `pytest tests/` coverage producer step (exit 1), not a coverage shortfall.

All three therefore trace to one root cause fixed by the repair commits
`3a2571c15` + `254b84c95` (registering the new consumer in
`scripts/check-ratchet-provenance.py` (+6) and classifying the new registry in
`quality/branch-independence.json` (+8)), reconciled with origin/develop at the
merge `aa5bef668`.

## Executed at the branch head (this round's own runs)

- `uv sync --locked --all-extras`, then the three `exact-debt-ledger` legs
  (`.github/workflows/vulture-ratchet.yml`) with CI's exact arguments —
  `check-ratchet-provenance.py` **exit 0** (`OK: 46 quality JSON consumer(s)`),
  `check-shipped-surface-truth.py` **exit 0**, `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` **exit 0**
  (base `5765efce8c1f`, candidate `aa5bef668a1a`, `1359 reviewed identities ->
  1359 findings`, `unclassified: 0`, `never_allowlist: 0`). No ledger amendment
  is needed: the candidate ledger equals the scan exactly.
- `scripts/check-api-route-contracts.py` — **exit 0** (`279 handlers scanned,
  15 audited routes registered, 0 canned`); wired at `.github/workflows/
  ci.yml:150`.
- CI-shaped coverage producers, then the diff-coverage gate: backend suite
  `coverage run --branch --source=packages/hive-conductor/backend -m pytest
  packages/hive-conductor/backend/tests` — **3278 passed, 6 skipped**;
  `coverage run --append --branch --source=scripts -m pytest tests/` —
  **4324 passed, 126 skipped** (the two previously failing repo tests pass
  inside this run); `coverage xml`; `check-diff-coverage.py coverage.xml
  --base 5765efce8` — **exit 0**: 14 changed files measured, 8 test-exempt,
  every measured file ≥ 90% lines / ≥ 80% branch arcs. The branch changes no
  publish-set source, so the 87% publish-set floor inherits develop's green
  state.
- `pytest test_noop_route_contracts.py test_memory_routes.py -q` — **45
  passed** (state-change, seeded non-empty, distinct-status, OpenAPI
  preview/unsupported and placeholder-gate proofs for this issue).
- `pytest tests/test_branch_independence_repository.py
  tests/test_ratchet_provenance_repository.py
  tests/test_check_api_route_contracts.py -q` — **33 passed**.
- Driver battery: `ruff check .` / `ruff format --check .` pass; the seven
  backend contract files (223 tests) pass; `check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests` — ok (3284 recorded == actual).

## Why local runs equal what the merge queue evaluates

`origin/develop` is `5765efce8c1f` and is an ancestor of HEAD, so the
merge-queue's synthetic base+candidate merge is exactly `aa5bef668`; every gate
result above applies verbatim to the queued evaluation.

## Acceptance criteria — evidence (re-verified this round)

- Inventory with intended contracts: `docs/api/route-contract-inventory.md`
  + `quality/api-route-contracts.json`, CI-checked by
  `scripts/check-api-route-contracts.py` (placeholder AST gate included),
  exit 0 above.
- Canonical-owner implementations or explicit unsupported: settings reload
  re-reads `services.settings_store` (`503` on failure), settings audit /
  schedule history read the durable audit log via the shared
  `routes.audit.audit_entries_view`, `/settings/quotas` delegates to
  `services.provider_usage.provider_panel`, memory namespaces are derived from
  owned entries and contradict durably increments
  (`test_contradict_entry_changes_durable_state`), quota panels distinguish
  `ok`/`no_data`/`unavailable`/`error`; `containers`/`mcp scan`/`mcp
  discover`/`rsi models` refuse `501` with named alternatives.
- Distinct states and schema/docs marking: pinned by
  `test_openapi_marks_preview_and_unsupported_operations`,
  `test_settings_reload_with_unavailable_store_is_503`,
  `test_settings_quotas_unavailable_is_distinct`,
  `test_unsupported_operations_are_501`,
  `test_mcp_scan_refuses_real_servers_with_501_and_keeps_404`.
- State-change + seeded non-empty:
  `test_settings_reload_reflects_an_out_of_band_write`,
  `test_settings_audit_returns_seeded_non_empty_data`,
  `test_schedule_history_returns_seeded_non_empty_data`,
  `test_list_namespaces_derived_from_owned_entries`.

## Salvage resolution (the recurring "uncommitted work" block)

The three untracked root files `full_output.txt` / `output2.txt` /
`vulture_output.txt` are byte-identical prior-round vulture scan summaries
(single md5 `ee90b8f6b08ea6ca629776099bae5131`; the 1383-finding pre-merge
state, superseded by the current 1359). No source work was ever uncommitted.
Preserved this round at
`/home/dev/maistro/jobs/1dc6aa98d81147d289f60de54a39a42a/salvage/` and then
removed from the worktree so the tree ends clean; nothing else was removed.
