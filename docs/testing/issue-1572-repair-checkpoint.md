# Issue #1572 CI repair checkpoint

Frozen scope: issue #1572 only; branch auto-1572; starting head
24c20e0d13fead743b32c8af02a4421e085793b3; supplied develop base
8fbbbfb91d78d30d756cf675b7b1a4c1ccff06e5. No GitHub mutations.

Repair targets: evidence from supplied check-0 through check-4 logs,
execution-lifecycle gate, vulture exact-debt ledger. Candidate edit scope:
quality/vulture-baseline.json (explicit CI-repair permission), this report,
and only Goal implementation/tests if an actual failure requires a fix.
Inspect adjacent Goal code/tests, relevant ADRs and CI commands before changes.
No other ledger/grant edits are authorized.

Initial state: clean worktree; HEAD matches dispatch. Existing implementation
is committed and preserved. The prior lifecycle blocker is historical evidence,
not assumed to remain true. Full issue acceptance includes both supported PostgreSQL majors (17/18)
installed-base upgrades and restart durability; do not infer these from unit tests.

## Reproduced gate results

- Supplied check-0..4 logs inspected: dependency sync, lint, format, Goal tests
  (55 passed / 16 skipped), core inventory (15797) pass. These are driver evidence.
- Executed CI-exact Vulture scan: PASS, 1326 reviewed identities / 1326 findings,
  zero unclassified. No evidence warrants a vulture ledger amendment.
- Executed `uv run python scripts/check-execution-lifecycles.py`: FAIL,
  19 classified / 20 discovered at trusted merge base e46ad6708fda;
  `maistro.goals.model::GoalStatus` lacks already-landed authorization.
  CI invokes this exact command at `.github/workflows/quality.yml:1508`.
- No conflict exists, so the conditional develop-conflict sync instruction does
  not apply. No lifecycle grant/ledger edits are authorized in this lane.
- BLOCKED on external policy prerequisite. Continue bounded acceptance checks;
  do not rename the lifecycle or weaken discovery to bypass trusted-base policy.

## Focused validation and architecture

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3205 files.
- `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q -rs`:
  55 passed, 16 skipped (PostgreSQL DSNs unset).
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`:
  FAIL, daemon unavailable. No live database success is claimed.
- Read accepted ADR-081226-a66b, ADR-082826-d9f5, ADR-092326-97c4,
  ADR-091726-7c2a, and relevant ontology text. Goal desired-state lifecycle must
  not become execution authority. Interview orchestration is upstream consumer
  scope, not an additional scheduler or store here. No ADR reconciliation edit
  is needed; preserve canonical Run/NodeRun/Attempt and Workspace authorization.
- Source reachability: Hive adapter `maistro_core.py:195` and server `main.py:344`
  call core `create_container`; `container.py:2362,2648` wires/exposes Goal storage.
  `goals/wiring.py` refuses an unmigrated configured PostgreSQL backend rather
  than silently substituting ephemeral storage. Wiring tests exercise that refusal.
- Existing restart test reopens SQLite stores, not product processes, and leaves
  Goal and Run at revision 2. It cannot establish historical binding preservation
  across subsequent Goal revision advancement. This is an evidence boundary,
  not a demonstrated defect in production code.

## Final checks

- `uv run pytest tests/test_check_execution_lifecycles.py -x -q`: FAIL,
  28 passed / 1 failed; line 374 reproduces the trusted-base GoalStatus blocker.
- `uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q -rs`:
  2 passed / 23 skipped; real PostgreSQL server required for skipped legs.
- `uv run python scripts/check-m1-convergence-freeze.py --base 8fbbbfb91d78d30d756cf675b7b1a4c1ccff06e5`:
  PASS, no unapproved new architecture island.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS, 15797 unique identities, no duplicate evidence.
- `git diff --check`: PASS.
- Integration scope: measured `git diff --no-renames --name-only` against the
  frozen supplied base through `scripts/ci_merge_group_scope.py --json`; all
  seven scope flags true. Executed `uv run python scripts/check-integration-scope.py
  --event-name merge_group --scope-json <measured JSON>`: FAIL, nine required
  specialized results missing (docker-build, durable-events, both Hive E2E jobs,
  MinIO, PG17, PG18, strike-ladder, wheel-imports). No fake success inputs given.
  This is a local evidence insufficiency, not a reproduced remote producer fault.
  The supplied dispatch contains zero check-result objects for the exact starting
  head. Actual remote integration-scope failure cause remains UNRESOLVED; cannot
  safely attribute it to Vulture or the independent lifecycle gate.

## Acceptance map

| Criterion | Executed evidence / remaining boundary |
| --- | --- |
| Three-backend Goal/revision round-trip | Shared conformance line 171 passes memory/SQLite; PostgreSQL UNVERIFIED. |
| Append-only, stale CAS refusal, one concurrent winner | Conformance lines 197, 229, 278 pass memory/SQLite; PostgreSQL UNVERIFIED. |
| Parent/Project lineage; recorded Agent reassignment | Conformance lines 294, 333 pass memory/SQLite; PostgreSQL UNVERIFIED. |
| Admission binding and immutable historical revision | Run-binding tests pass memory/SQLite across terminal transitions; PostgreSQL and binding across later Goal revision advancement UNVERIFIED. |
| Workspace isolation; foreign equals missing | Scoped conformance lines 398, 472 pass memory/SQLite; PostgreSQL UNVERIFIED. |
| Shipped Container and both production compositions | Container exposure/authorized seam and backend-selection tests pass; both product callers inspected. Actual durable product restart UNVERIFIED. |
| No competing GoalRun/executor/product lifecycle | Convergence freeze passes; separate lifecycle authorization gate fails. |
| Preserve user-model 056/planner 057 identity; append Goal migration | Installed-base static identity and snapshot-byte checks pass (2 tests); live upgrades UNVERIFIED. |
| Populated c560d4c/4675101 snapshots, data/index/constraint preservation, reopened bound provenance | PostgreSQL tests skipped; both PG17/PG18 UNVERIFIED. |
| Fresh install, single head/unique IDs, downgrade/refusal/reapplication, older quota-door history | Full database-chain and supported-history acceptance UNVERIFIED; no runtime migration success inferred from static tests. |

## Handoff

BLOCKED. Only this report changed; no production code, tests, workflows,
ledger or grant changed. No test inventory delta is needed. Existing branch
work remains intact. No demonstrated Vulture defect exists to repair.

Next: authorized policy owner must separately land GoalStatus authorization
before a subsequent synchronized implementation can pass trusted-base policy.
Supply exact-candidate specialized producer logs and working PostgreSQL 17/18
services for remaining acceptance. Do not repeat speculative ledger repairs.

Progress: checked 1 issue, done 0 repairs, skipped 0 issues, blocked 1.
This evidence-only checkpoint is committed locally; it is not integration approval.

