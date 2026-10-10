# #1572 repair round 5 — coverage gate fixed at head c5f3549d8

Round lane: `auto-1572` @ `c5f3549d81fb`, merge base with `origin/develop`
`cc6e4899ddef` (develop's upload-artifact bump; already merged into the
branch). The merge-queue evaluation named three failing gates: `test`,
`Quality gate (Pillars 1–4, 7, 8)`, and `Coverage gate (publish-set floor +
diff coverage)`.

## Root causes found, per gate

### Coverage gate — real, this branch, fixed

Reproduced first-hand by running every producer locally against a live
PostgreSQL 18 (`maistro:maistro@127.0.0.1:5432/maistro_test`, chain at `062`):

- coverage-unit (core/canvas/evolve/rsi/bootstrap under `coverage run
  --branch`), coverage-postgres (`tests/migrations` on an unmigrated database,
  then `alembic upgrade head` + the core PG suites + backlog + canvas), and the
  scripts producer (root `tests/` under `--source=scripts`).
- Publish-set floor: **93% ≥ 87, EXIT 0** — and this local database is missing
  only the MinIO archive producer's data, which CI adds on top.
- Diff gate (`check-diff-coverage.py coverage.xml --base cc6e4899ddef`): **FAIL
  — `scripts/verify-wheel-imports.py`: 20.0% of 5 changed lines (need 90%);
  uncovered 352, 353, 420, 421.** The sibling-wheel constraint pinning
  (`dd14d9a55`, the PyPI-shadowing fix) put new lines inside `check()` and
  `_wheel_dist_name()`, which no coverage producer executes: every existing
  test in `tests/test_verify_wheel_imports.py` deliberately routes around
  `check()`.

Fix: `TestTheSiblingConstraintPin` in `tests/test_verify_wheel_imports.py`
(+5 node IDs, note
`docs/testing/inventory-notes/1572-wheel-sibling-constraint-pinning.md`). The
tests drive `check()` end-to-end through a fake `uv` shim (millisecond venv +
offline wheel unpack + real minimal wheel) and assert from the shim's receipt
that the installer was handed `--constraints` pinning
`dummy @ file://<exact wheel>`. Regression sensitivity proven: against a copy
of the script with the constraint block removed, the installer argv carries no
`--constraints` and the assertions fail. After the addition:
**diff gate EXIT 0 — every measured file this change touches ≥ 90% lines / 80%
branch arcs**; goals modules measure 95.9–100% (model 100, authorization 100,
wiring 100, sqlite_store 99.1, pg_store 98.2, store 95.9).

### Quality gate — one real blocker (external), one unbanked improvement (banked), rest green

- `check-execution-lifecycles.py` (CI-exact): **still the known external red**,
  sole finding `maistro.goals.model::GoalStatus: NEW work-state vocabulary is
  absent from the trusted base and has no already-landed authorization`.
  `load_authorizations` reads `quality/ratchet-authorizations.json` from the
  merge base `cc6e4899ddef`; that file's `execution-lifecycles` grants there
  cover only `services.rsi::RunStatus` and
  `maistro.graph.nodes.agent_delegate_remote::DelegationStatus`. The grant can
  only close by landing on develop first (two-merge rule); this lane may not
  edit grants or push. Unchanged from rounds 2–4; it is the sole red this
  branch carries into CI, and it reds Pillar 7, the root-suite self-check
  (`tests/test_check_execution_lifecycles.py::test_the_shipped_ledger_matches_the_shipped_code`),
  and through it CI's `test` job.
- `check-ac-state.py --run-tests --ratchet --mandate cc6e4899ddef`: was FAIL
  `unbanked improvement — design_coverage: 44.2377, floor still says 43.8998`
  (the branch's own criterion-marking work improved design coverage). Banked
  with the gate's own remedy: `quality/ac-state-notes/auto-1572.json`
  (branch-scoped, conflict-free by design, not a grant). Re-run: **EXIT 0** —
  10 counters on ceilings, 1 on floor, mandate clean, chain clean.
- Everything else re-run green at this head with CI's exact arguments: ruff
  check + format (3249 files), vulture ledger 1323→1323, radon 137→137,
  xenon 139 ≤ 145 (avg 0, module ledger 0), mypy --strict core (780 files),
  pyright 17 ≤ 21, interrogate (all 11 floors), enumerations,
  workspace-retirement 86→86, route-permissions 41/0, principal-identity,
  frontend-typed-client, wiring-reads, agent-store-writes, contract-markers,
  convergence-matrix, reachability + dispositions, security-inventory,
  image-inventory, image-pins, workflow-inventory, backlog-consistency,
  model-egress, foreign-harness-egress, vendor IFEval/BFCL `--check`,
  doc-links, release-consistency, version consistency (42 sites),
  m1-convergence-freeze `--base cc6e4899ddef` EXIT 0, durable-table-inventory
  110 tables, fitness 23 passed, formal/ 666 passed (after installing
  `maistro-evolve`, as CI does).

### test job — one real red (same external cause), one local artifact, rest green

- `tests/test_branch_independence_repository.py` failed locally only because a
  prior round's `check-ac-state.py` run had left the gitignored generated
  `quality/ac-state.json` on disk, which the branch-independence discovery
  reads as an unclassified surface. Removed the artifact; test green. CI's
  fresh checkout never had it — not a CI failure.
- Root suite re-run (12 min): **5055 passed / 134 skipped / 1 failed** — the
  one failure is the GoalStatus self-check above. In CI this single test is
  what reds the `test` job at this head.
- Every other Python leg re-run green first-hand: maistro-server 535,
  maistro-turing 210 + backend 90, maistro-design 572, ext-harness 273,
  ext-sdk 147, core unit 15110 passed/1053 skipped, core PG legs 5961 passed,
  goals suite 70 passed with PG legs live (0 skipped), tests/migrations 165
  passed on a fresh pg18 database, pack contracts 110. Frontend/Hive/OpenAPI
  legs are untouched by this branch's diff (`git diff cc6e4899d..HEAD --
  packages/hive-conductor packages/maistro-server` is empty) and were
  CI-proven at 23800125b; suite inventory ok (17 suites, 30814 node IDs, +5
  recorded), no duplicate test files.

## Acceptance re-verified first-hand this round (pg18, chain at 062)

- Three-backend conformance (`test_goal_store_conformance.py`, 11 tests ×
  memory/sqlite/postgres) green in both the unit and PG producers.
- Append-only/CAS, terminal-is-final, subgoal lineage, agent reassignment as a
  recorded transition, two-principals/two-Workspaces isolation, foreign-Goal ≡
  missing-Goal, authorized-member seam coverage — all green on all three
  backends.
- Run binding: admission binds `goal_id`/`goal_revision`, immutable after
  admission, half-binding refused, a Run outcome never moves Goal state
  (`test_run_goal_binding.py`, ×3 backends).
- Restart readback (`test_goal_restart_readback.py`) green.
- Container wiring (`test_goal_wiring.py`) green; the shared
  `create_container` (called by hive-conductor's adapter and maistro-server's
  main) exposes `goal_store` + the `goal_reader` seam.
- Installed-base upgrades: `tests/migrations/test_goal_installed_base_upgrade.py`
  builds fixtures from develop `c560d4c` (user-model 056), `4675101`
  (planner 057) and HITL 061, upgrades forward without restamping, asserts the
  three Goal tables serve the durable composition and pre-existing rows
  survive; merged identities keep meaning and Goals appends as 062. Green on
  pg18 this round; the pg17 leg is unchanged SQL since the CI proof at
  `23800125b` (`git log 23800125b..HEAD -- alembic/versions/` is empty).

## Residual risk

The GoalStatus lifecycle grant remains the sole known red anywhere and can
only close by landing on develop first. The MinIO archive producer and the
pg17 matrix leg were not re-executed locally this round (no Docker daemon;
archive data only increases the floor margin; pg17 SQL unchanged since its
last green CI run).
