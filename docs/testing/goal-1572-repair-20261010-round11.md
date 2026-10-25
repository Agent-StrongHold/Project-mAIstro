# #1572 repair round 11 — independent re-verification at 8501b051f; Docker reachable, every previously-UNVERIFIED PostgreSQL leg executed first-hand

Head: `8501b051f625709bc26e9c7ae33e053ced494971`, base: `4aa68edc0b6b85ae23f97e611d693927218863dc` (= origin/develop head, verified via fetch). Worktree clean before and after; no source, test, workflow, ledger or grant file touched. This round is verification-only: driver checks inspected, then every acceptance criterion re-proven first-hand, including the PostgreSQL legs prior rounds had to mark UNVERIFIED because the daemon was unreachable.

## Driver checks (job cf0147dfc13c48209f7625645171bc78, check-0..check-4.log)

All five green: `uv sync --locked --extra dev`; `ruff check .`; `ruff format --check .` (3281 files); focused Goal/parity pytest **161 passed, 28 skipped**; `check-suite-inventory.py --suite packages/maistro-core/tests` (**16269** unique nodes, 0 duplicates).

## PostgreSQL legs — executed this round (daemon was down in rounds ≤ 10)

Containers `auto-1572-pg` (pg18, 127.0.0.1:55712) and `auto-1572-pg17` (pg17, 127.0.0.1:55717), both `pgvector/pgvector`, up before this round started.

- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=…:55712/postgres MAISTRO_TEST_DATABASE_URL=…:55712/postgres uv run pytest packages/maistro-core/tests/goals -q` → **70 passed** on pg18; same invocation against :55717 → **70 passed** on pg17. Includes the shared conformance suite's PostgreSQL leg (round-trip, append-only CAS, single concurrent winner, Subgoal lineage, Agent reassignment records, two-principal/two-Workspace isolation, foreign==missing) and `test_goal_pg_schema_agreement.py` (migration-063 vs `ensure_goal_schema`).
- `MAISTRO_TEST_DATABASE_URL/MAISTRO_TEST_PG_DSN=… uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -q` → **26 passed** on pg18 (88.7s) and **26 passed** on pg17 (80.5s): live forward upgrades from the actual develop snapshots (`c560d4c` → user-model 056, `4675101` → planner 057, HITL 061 base) **without stamp reset**, merged 056/057 identity/ancestry and byte-equality assertions, unique-ids/single-head, and `test_the_upgraded_base_serves_the_durable_goal_composition` reopening the upgraded database to read back Goals, revision chains and immutable bound Run provenance.
- Acceptance-state ratchet with PG: `check-ac-state.py --run-tests --ratchet` → EXIT 0 (38 notes folded incl. `auto-1572.json`); regenerated gitignored `quality/ac-state.json` removed afterwards (byproduct procedure, `.gitignore:77-81`).

## CI `test` job legs at HEAD (env `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`)

- Root tree `tests/ --ignore=tests/tools/registry`: **4977 passed, 1 failed** — sole red is `tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`, the external GoalStatus authorization (below).
- `packages/maistro-server/tests`: **545 passed, 8 skipped**. Turing (both trees) + design + ext-harness + ext-sdk: **1292 passed, 1 skipped**. Hive backend: **3625 passed, 20 skipped**.
- Combined no-cross-suite-leakage run `tests/ packages/hive-conductor/backend/tests packages/maistro-design/tests -q --timeout=60`: 9266 passed, 2 failed. Failure 2 = `test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once` — **disproven as this round's own byproduct**: the scan reported `unclassified quality state: quality/ac-state.json`, the file my acceptance-state run had generated; it is gitignored and never present in CI's `test` job. Removed the byproduct; the test passes standalone (1 passed) and the scanner returns `[]`. Matches the round-9 finding exactly.
- Full suite inventory `check-suite-inventory.py` (all 17 suites) → ok; `check-test-duplicates.py` → ok.

## Coverage producer legs (quality.yml `coverage (no services)`)

- `packages/maistro-core/tests --timeout=30 -q`: **15209 passed, 1057 skipped, 3 xfailed** — no failure of any kind in the publish-set core suite.
- canvas + evolve + rsi + bootstrap: **3320 passed, 92 skipped**.

## Quality gate steps re-run first-hand at HEAD

ruff lint/format (driver); `check-radon-baseline.py` 137=137; `bump_version.py --check` 42 sites; `check-release-consistency.py`; `check-doc-links.py`; `check_enumerations.py`; `check-workspace-retirement.py` 89 entries; `check-route-permissions.py`; `check-principal-identity.py`; `check-frontend-typed-client.py`; `vendor_ifeval.py --check`; `vendor_bfcl.py --check`; xenon 0 block / 0 module / 0 average violations (≤ 145 / empty ledger / 0); `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → **1323 = 1323, unclassified 0, no amendment**; `check-reachability.py`; `check-credential-authority.py`; `check-wiring-reads.py`; `check-agent-store-writes.py`; `check-contract-markers.py`; `check-convergence-matrix.py` (52 subsystems / 1399 modules); `check-reachability-dispositions.py`; `check-security-inventory.py`; `check-image-inventory.py`; `check-image-pins.py`; `check-workflow-inventory.py` (28 workflows); `check-backlog-consistency.py`; `check-model-egress.py`; `check-foreign-harness-egress.py`; `check-durable-table-inventory.py` (110 tables incl. the three `canonical_goal*` rows); `mypy --strict packages/maistro-core/src` → no issues in 787 files; pyright 17 errors ≤ baseline 21 with **zero diagnostics in `maistro/goals/`**; interrogate all nine floors pass; `packages/maistro-core/tests/fitness` 23 passed; `formal/` **666 passed, 1 skipped** (after CI's own `uv pip install -e packages/maistro-evolve` setup step); both synthetic proof validators (`validate-installed-workspace-proof.py` structural-valid/closeout-SYNTHETIC_NOT_CLOSEOUT, `installed_workspace_proof_contract.py` valid/DISPATCH_LINK_MISMATCH) fail closed as CI asserts; `check-m1-convergence-freeze.py --base 4aa68edc0` → no unapproved new architecture island.

## Criterion → first-hand evidence map (delta over the round-10 checkpoint)

| Criterion | Evidence this round |
| --- | --- |
| Round-trip on all three backends, shared conformance suite | 70/70 on pg18 **and** pg17 (PG leg executed, was skipped before); memory/SQLite in the 15209-pass core run |
| Append-only revisions; stale refused; one concurrent winner | Conformance `:197/:229/:278` on all three backends (executed) |
| Subgoal lineage + recorded ownership change | Conformance `:294/:333` on all three backends (executed) |
| Run admission binding, immutable after admission | `test_run_goal_binding.py` in the 70/70 runs and core run; provenance read back after live PG upgrades (`test_the_upgraded_base_serves_the_durable_goal_composition`) |
| Two Workspaces isolated; foreign == missing | Conformance `:398/:472/:515/:577` on all three backends (executed); `goals/authorization.py` rides `maistro.workspaces.authorization` (#1150), no second path |
| Production composition + shipped Container | `test_goal_wiring.py` in 70/70; source: `container.py` `create_container` → `wire_goal_store`; Hive `backend/adapters/maistro_core.py:195`, server `maistro_server/main.py:344` |
| No `GoalRun`/`OrchestratorRun`/second executor | grep over `packages/*/src`: none; convergence freeze green at develop base |
| Migration identity/installed-base/upgrades | Live 26/26 on both supported majors, from the actual merged snapshots, forward-only, durable read-back after upgrade |
| Restart durable composition, read back | SQLite restart test + PG upgraded-composition read-back (both executed) |

## Sole remaining red — unchanged, external

`check-execution-lifecycles.py`: `maistro.goals.model::GoalStatus` is NEW work-state vocabulary vs trusted base `4aa68edc0b6b` (current develop head; re-fetched this round) "and has no already-landed authorization" (19 → 20). The gate's own contract (and the repo's two-merge rule) requires the grant to land on develop in a separate change; the branch ledger already carries the DOMAIN classification with rationale, which cannot self-authorize. ADR-032 regression tests confirm (`tests/test_check_execution_lifecycles.py`: 28 passed, 1 failed = the same authorization). This lane may not land non-vulture grants. Every other CI step re-proven green at this exact head.

Disposition: all acceptance criteria proven first-hand except the one externally-owned GoalStatus authorization prerequisite. Not fixable in-branch without violating the lifecycle-authorization policy; hand off for the grant to land on develop, then the gate (and the two tests that drive it) go green without any change here.
