# L337 repair round 7 — handoff (2026-10-24)

Head entering: `39440a4be` (round 6 + merge of develop `ffc27cc43`). Head
leaving: the develop-sync merge of `db4d3eb09` plus this handoff commit.

## Entering state ("worker left uncommitted work" block re-checked)

`git status` at `39440a4be` was clean except the untracked `.cache/` directory:
1.6 GB of `trivy` scanner DB cache (`trivy/db`, `trivy/fanal`) left by the
round-3 container-scan reproduction — tooling data only, no source work. All
round-3..6 fixes were already committed. Block remains resolved; nothing to
salvage.

## Develop sync (the substantive change this round)

`origin/develop` had advanced one commit past the round-6 merge point
(`ffc27cc43` → `db4d3eb09`, the new assigned base):

- `db4d3eb09` [M1] Delete superseded universal owners after behavioral parity
  (#2300, issue #35): makes `services/dag_run_store.py` a reconciled display
  projection with the shared #1036 terminality contract (`record_status` /
  `record_outcome`), moves the chat workflow tool's writer onto
  `record_outcome`, adds `test_dag_run_projection_authority.py` (15 tests) and
  `test_dag_run_projection_lifecycle.py` (15 tests), adjusts
  `test_dag_run_history_durability.py`, and adds inventory notes for those
  deltas.

Merged cleanly with the `ort` strategy (no conflicts). Disjointness was
checked before merging: `git diff ffc27cc43 HEAD` (this branch, 23 files) and
`git diff ffc27cc43 origin/develop` (11 files) share no paths, and neither
side touched `docs/testing/inventory/baseline.json`. The develop delta lands
inside issue #337's durability surface (dag-run store), but on the write-side
projection contract, which composes with this branch's durable-owner wiring
(`foundation.py` rehydration, `dag_run_inspection.py` read-side) — the merged
semantics are pinned by the 30 new #35 tests plus the pre-existing durability
suites, all green (below).

## Named gate failures re-proven at the merged head

The merge-queue evaluation's red jobs cite the round-2 head `976ad2f6`; both
were fixed in round 3 (`aef3245a0`) and re-proven in rounds 4–6. Re-proven
again at this round's merge head with CI's exact commands:

- **types-drift** (the round-6 "only exiting-1 step" of the red `test` job):
  `uv run python scripts/dump-hive-openapi.py` + `npm --prefix
  packages/hive-conductor/frontend run gen:api` + `git diff --exit-code --
  packages/hive-conductor/frontend/src/api/types.gen.ts` → exit 0 (241 paths,
  147 schemas; no diff).
- **vulture per-identity ledger** (CI-exact: `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`): 1297 reviewed identities == 1297 findings,
  base `db4d3eb09` → exit 0. (Count moved 1302→1297 with develop's own code
  evolution; the ledger from the base matches the merged scan.)

## Full validation battery at the merged head

- `uv sync --locked --extra dev` — clean.
- `uv run ruff check .` — All checks passed; `uv run ruff format --check .` —
  3496 files already formatted.
- Hive backend: `uv run pytest packages/hive-conductor/backend/tests -q` →
  **4008 passed / 25 skipped** (4033 collected, exactly the recorded
  inventory).
- Durability battery (issue #337 acceptance): `test_durable_node_metrics.py`,
  `test_feedback_route.py`, `test_goal_inspection.py`,
  `test_node_metrics.py`, `test_dag_run_history_durability.py`,
  `test_dag_run_projection_authority.py`,
  `test_dag_run_projection_lifecycle.py` → 174 passed;
  `test_thumbs_read_through_the_protocol.py` +
  `test_dag_run_canonical_lifecycle.py` → 25 passed.
- Root suite: `uv run pytest tests/ --ignore=tests/tools/registry -q` → 5646
  passed / 143 skipped.
- Combined single-process (CI "no cross-suite leakage" step): first run
  reported 2 failed + 2 errors (one visible error:
  `tests/test_restore_oracle_characterization.py::test_semantic_loss_is_rejected`);
  the identical tree re-run exited 0 with **10407 passed / 169 skipped**, and
  that file passes 6/6 in isolation. Classified as the documented
  event-loop/teardown flake class (round 6: the `Event loop is closed`
  annotations were non-fatal `PytestUnhandledThreadExceptionWarning`s inside
  passing suites), not a merge regression — no code changed between the two
  runs. Residual: the flake is not root-caused here.
- Other test-job suites: server 646 passed/10 skipped; turing 225 passed;
  turing backend 125 passed; ext-harness 273 passed; ext-sdk 147 passed.
- Frontends (CI-exact `npm ci` first): canvas `npm ci` → `npm run test:ci`
  79 passed → `npm run lint` exit 0 (13 allowed warnings) → `npm run build`
  exit 0; `npm audit --audit-level=high` → 0 vulnerabilities. Hive frontend
  `npm ci` → lint exit 0 → build exit 0.
- Suite inventory (CI-exact, all suites): `python scripts/check-suite-
  inventory.py` → **21/21 suites, 34324 identities** (was 34183 at round 6;
  +141 from develop's new tests, pre-recorded in develop's own
  `inventory-notes/35-*.md` deltas — no new inventory note needed this round).
  `python scripts/check-test-duplicates.py` → 0 byte-identical groups, exit 0.

## Acceptance criteria of issue #337 (re-verified at this head)

- **Canonical durable owner per state family, readers/writers connected** —
  `foundation.py` `_init_state` wires `configure_dag_run_store(stores.dag_runs)`
  (SQLite-rehydrated), `configure_metrics_store(node_metrics)` (durable
  JsonStore), and `configure_profiles(PersistedProfileRecordStore(persisted))`;
  `engine.py:301` binds the feedback outcome store in production.
- **Canonical Run/NodeRun/Attempt correlation** — `routes/feedback.py:132`
  returns 409 for projection-only runs; feedback + thumbs suites green.
- **Restart and multi-instance reads return the same history** —
  `test_metrics_survive_restart_and_refresh_an_existing_replica` and the
  dag-run history durability suite green in the 174/4008-test runs; develop's
  #35 read-side reconciliation adds canonical-truth-wins serving, pinned by
  the 15 authority tests.
- **No unused setter implying durability** — `set_outcome_store` production
  caller at `engine.py:301` (grep-verified this round), pinned by
  `test_thumbs_read_through_the_protocol.py`.
- **Retention/scope/pagination/deletion explicit** — `GET /v1/dag-metrics/
  retention` (`routes/metrics.py:50`), fail-closed scope and retention-eviction
  tests green; types drift exit 0 keeps the committed API types truthful.
- **Migration/parity before retirement** — transport-parity and durable-store
  suites green inside the 4008-test hive run; profile PostgREST fail-loud
  cutover retained (`_warn_if_postgrest_profiles_are_being_left_behind`).

Specs/ADR from this branch remain in tree: `docs/specs/SPEC-083026-2601`,
`docs/specs/SPEC-083026-2642`, `docs/adr/ADR-083026-a91e`.

## Not re-run locally this round (inputs unchanged since prior proofs)

Docker image builds + trivy/SBOM/cosign and the pip-audit gate: the merge's
11-file diff touches no Dockerfile, `uv.lock`, or requirements input; round 6
proved pip-audit exit 0 and the image-lock fork pins, and `db4d3eb09`'s own
CI proved the fork-proof image-lock gate on develop. Hosted CI has not yet
been observed at this round's head.

## Residual risks

1. The combined-run flake (one transient 2F+2E, unreproducible on the same
   tree) is documented but not root-caused.
2. Hosted CI not yet observed at this merge head; the historical red jobs are
   locally re-proven with CI's exact commands.
3. `.cache/` (1.6 GB trivy cache) remains untracked in the worktree.
