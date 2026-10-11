# Issue #1572 CI repair checkpoint

## Round 36 (2026-10-11, head ac9d155f182f, develop base 7d3b8ae6918 -> merged origin/develop 0dcbc91c24fc)

Prior rounds' claims were not trusted; every leg below was re-executed
first-hand on fresh round-36 databases (r36g18 on pgvector:pg18, r36g17 on
pgvector:pg17) after merging the five new develop dependency commits
(semgrep/typer/fastmcp/hypothesis/boto3; zero file overlap with this branch,
clean ort merge, `uv sync --locked --extra dev` green).

Acceptance re-executed:

- pg18: `alembic upgrade head` empty -> 063, `canonical_goals`,
  `canonical_goal_revisions`, `canonical_goal_transitions` catalog-verified,
  `alembic heads` = single head `063`; goals suite 70/70 passed with
  `MAISTRO_REQUIRE_PG_LEGS=1` and both DSNs set.
- pg17: identical — empty -> 063, three tables, single head, goals 70/70.
- `tests/migrations` 168/168 passed per major (`MAISTRO_TEST_DATABASE_URL` set):
  includes installed-base forward upgrades from the real develop snapshots
  `c560d4c` (user-model 056), `4675101` (planner 057) and `66f3cea` (HITL 061)
  with no stamp edit, merged-identity preservation, single-head/unique-ID,
  downgrade-refusal and reapplication coverage, and
  `_drive_and_reopen_the_durable_composition` — Goals, revisions and immutable
  bound Run provenance written, pool closed, reopened fresh, read back.
- `test_goal_restart_readback.py` durable leg PASSED (not skipped) with the
  PostgreSQL DSN set.
- `check-m1-convergence-freeze.py --base 7d3b8ae69...` and `--base
  origin/develop`: exit 0 (no GoalRun/OrchestratorRun/second executor).
- `ruff check .`, `ruff format --check .`: green. `mypy` (7 packages, 899
  files): clean. `check-suite-inventory.py --suite packages/maistro-core/tests`:
  matches the recorded inventory; no inventory delta (merge added no tests).
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (CI argv): exit 0, 1323 = 1323 — no ledger amendment
  applies in this lane.
- Merge-queue red re-confirmed as the single external gap against the UPDATED
  develop: `check-execution-lifecycles.py` exit 1, sole delta
  `maistro.goals.model::GoalStatus: NEW work-state vocabulary ... no
  already-landed authorization` (base 0dcbc91c24fc);
  `tests/test_check_execution_lifecycles.py` = 28 passed / 1 failed with the
  identical delta. `quality/ratchet-authorizations.json` is byte-identical to
  `origin/develop` (sha256 2f7b95dc5f09f8e6...) and carries zero GoalStatus
  grants; `scripts/ratchet_provenance.py` `load_authorizations` provably reads
  the grant file from the base revision (two-merge rule), so no on-branch
  repair exists. Disposition unchanged: grant-only develop landing of the
  GoalStatus execution-lifecycles authorization is the sole remaining action
  for this issue.

New finding — pre-existing on develop, OUT OF #1572 SCOPE, recorded not
repaired (candidate-edit scope for this lane excludes approval-store files,
and both sides of the mismatch are byte-identical to origin/develop):

- On any alembic-migrated PostgreSQL database,
  `PgApprovalStore.create` fails with `asyncpg
  InvalidColumnReferenceError: there is no unique or exclusion constraint
  matching the ON CONFLICT specification`.
- Evidence: `packages/maistro-core/src/maistro/capabilities/approval_store.py`
  inserts `ON CONFLICT (run_id, effect_scope, binding_id, effect_key)`
  (:414 area; its own bootstrap DDL at :274-276 declares
  `UNIQUE(run_id, effect_scope, binding_id, effect_key)`), but migration
  `alembic/versions/043_invocation_quota_door.py` ships
  `uq_capability_approval_effect UNIQUE (run_id, node_run_id, binding_id,
  effect_key)` — a migrated table therefore lacks the constraint the runtime
  SQL targets. Reproduced first-hand on a pristine migrated pg18 database:
  `packages/maistro-core/tests/conformance/test_approval_store_conformance.py`
  = 6 failed / 17 passed (postgres legs only; memory/SQLite legs pass). The
  full `packages/maistro-core/tests` run (16205 passed, 137 skipped, 3
  xfailed) shows these 6 as the ONLY failures; the same file passes its
  non-postgres parametrizations, so suites without a DSN never see it.
- Attribution: `approval_store.py`, `tests/conformance/` and 043's DDL are
  byte-identical between this branch and `origin/develop` (this branch's 043
  delta is docstring-only), so develop inherits the defect; no migration ever
  adds an effect_scope-keyed unique constraint on `capability_approvals`
  (035's effect_scope work is on `capability_invocations`). It surfaced now
  because this round ran the conformance directory with a migrated PG DSN;
  CI's failing merge-queue jobs do not collect it.
- Owner: the capability/approval-store lane (#1196/#55 effect path), not this
  issue. No edit made here by scope discipline.

Round-36 verdict: all #1572 acceptance criteria proven first-hand on both
supported majors; no Goal-scoped defect found; the branch is merged current
with develop and left with this note as the only delta.

---

Earlier checkpoint (round of head 24c20e0d13, base 8fbbbfb91d8) retained
below for provenance.

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

