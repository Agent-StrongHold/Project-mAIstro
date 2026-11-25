# REPAIR-NOTES-2406 — develop sync resolution and post-merge gate revalidation

Round: cr-2406 verification/repair, 2026-11-21. Incoming head `74e7ea6374`
(branch `agent/m1-2311-assetinstance-cutover`), base `228dec753f` (origin/develop).

## Incoming state

The worktree held a **preserved, in-progress merge** of develop `a3efc93c` with
one unmerged path: `docs/architecture/CONVERGENCE-MATRIX.md` (everything else
already staged). Nothing was discarded; the conflict was resolved in place.

## Resolution

1. `f721ec08d6` — completed the `a3efc93c` merge with a **union** resolution:
   - *Agent Conductor services* row: develop's version (adds "never-registered /
     unfinished climb+PostgREST helpers RETIREd for Workspaces v1.0 (#2309)" and
     the `#2309` ref) — develop-side change, unrelated to this PR.
   - *Canvas ability* row: this branch's version (share `few` → `none`, the
     #2311 cutover reachability claim this PR owns).
   - `check-convergence-matrix.py` exit 0 post-resolution (52 subsystems, 1494
     modules, 82 unreachable attributed).
2. `dec3c68286` — merged `origin/develop` (`228dec753f`, fetched) cleanly; no
   conflicts. Per the quality-ledger merge hazard (AGENTS.md), verified the
   develop-side rows survived: the `#2378` sandbox-template digest row
   (`b178ca62ec…`) is present in `quality/image-pins.json`; `check-image-pins`
   exit 0.

## Post-merge validation (all executed this round, CI-exact arguments)

| Gate | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean / 3601 files formatted |
| `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | exit 0 — 1222 findings, 1229 reviewed identities, **0 unclassified**, 0 never-allowlist (no ledger amendment needed) |
| `check-radon-baseline.py` | exit 0 — 124 C-or-worse blocks vs 126 reviewed |
| xenon (CI-exact argv) | 124 block violations == `XENON_BASELINE: 124`; 0 module; 0 average |
| `check-reachability.py` / `check-reachability-dispositions.py` / `check-reachability-dispositions-provenance.py` | exit 0 / 27 groups / provenance OK |
| `check-convergence-matrix.py` | exit 0 |
| `check-ratchet-provenance.py` | exit 0 — no candidate-approved expansion |
| `check-shipped-surface-truth.py` / `check-backlog-consistency.py` / `check-durable-table-inventory.py` | exit 0 (124 tables; `character_references` pruned) |
| `check-image-pins.py` / `check-image-inventory.py` | exit 0 |
| `check-suite-inventory.py` (full) | exit 0 — 21 suites match recorded inventory |
| `uv run mypy <CI 8-package scope>` | Success: no issues in 1070 files |
| `maistro-registry lint . --strict` | exit 0 |
| interrogate (all 12 CI floors) | all pass |
| `pytest packages/maistro-canvas/tests -q` | **576 passed, 75 skipped** |
| `pytest packages/maistro-server/tests -q` | **681 passed, 10 skipped** |
| `pytest packages/maistro-core/tests/runs packages/maistro-rsi/tests/test_m8a16_lean_rust_kernel_research.py -q` | **1607 passed, 385 skipped** (covers the #2422 pg/sqlite/store merge delta) |
| `pytest tests/test_complexity_gate_scope.py -q` | 5 passed (pins `XENON_BASELINE` to ledger length) |
| `test_asset_instance_parity.py` + `test_canvas_runtime.py` | 27 passed; `TestLifespanCanvasRunnerStart` 4 passed |

## Acceptance evidence (issue #2406 / #2311 ACs)

- **tool.py retired, parity first**: `maistro_canvas/canvas/tool.py` absent;
  `test_asset_instance_parity.py` (10 tests) passes; transitional demotion
  markers with the no-authority-regain rule present in `canvas/{store,routes,
  executor,compositor,publishing}.py`.
- **CanvasJobRunner in default composition**: `_runtime_lifespan` starts it
  (`main.py:728-737`) via `_start_canvas_job_runner`, with the
  `CANVAS_SERVER_CONSUMER_ENABLED` opt-out pinned by tests; governed
  `ImageGenerationEgress`, fail-closed `MAISTRO_CANVAS_DEFAULT_DRAFT_MODEL`,
  stable `effect_key` in `maistro_server/canvas_runtime.py`; binding restart
  read-first registration pinned by `test_restart_against_a_persisted_binding_
  reuses_the_record` / `test_a_conflicting_persisted_binding_refuses_to_start`.
- **/v2/canvas operable on default compose**: `docker-compose.yml` threads
  `CANVAS_API_TOKEN=${CANVAS_API_TOKEN:-}` (fail-closed default, June audit
  3.2); `TestDefaultComposeCanSupplyTheToken` structural tests pin the wiring;
  the `/v2/canvas` router mounts unconditionally (`main.py:203`), legacy
  `/api/canvas` retained transitional (`main.py:974`). **Live bring-up was
  executed at `74e7ea6`** (commit message documents the engine crash-loop
  restart fix verified over three restarts against a persisted database); this
  round's merges (`74e7ea6..dec3c68286`) touch **no** files under
  `docker-compose.yml`, `packages/maistro-server/src`, or
  `packages/maistro-canvas/src` (diff verified), so that live evidence remains
  valid for the compose/canvas/server surfaces; the merged core runtime delta
  is covered by the 1607-test runs battery above.
- **Disposition/ledger pruning**: `canvas-legacy-layerrecord` absent from
  `quality/`; vulture ledger matches the CI-exact scan exactly with no stale
  rows for the eliminated identities (`delete_layer`, `perspective`,
  `canvas/tool.py` — grep-verified absent from `quality/vulture-baseline.json`);
  durable-table retention green with `character_references` pruned (orphan
  documented in `KNOWN-GAPS.md`).

## Residual (not tree defects)

1. **Stale inert grant rows**: `quality/ratchet-authorizations.json` still
   carries authorizations for `routes.py::unused function 'delete_layer'` and
   `layers.py::unused variable 'perspective'` (lines ~588/593). The debt they
   covered was eliminated at source (`25e1206d87`), so the rows are inert;
   `check-ratchet-provenance` reads authorizations from the merge base and
   exits 0. Pruning them is a cosmetic follow-up, not required by any gate.
2. **GitHub PR-body prose is stale** (says "17 new server tests", "1248 passed,
   86 skipped", and credits PR #2397 for rows now eliminated at source).
   GitHub-side text; this worker makes no GitHub mutations. The in-tree notes
   (`docs/testing/inventory-notes/agent-m1-2311-assetinstance-cutover-b745.md`)
   record the truthful history.
3. The `/v2/canvas` surface answers 503 while `CANVAS_API_TOKEN` is unset —
   designed fail-closed behavior (June audit 3.2), not a regression; operability
   is the operator setting the threaded `.env` knob, now shipped.
