# Issue 1572 repair checkpoint (bba2)

Frozen scope: issue #1572 only, starting HEAD
`21c0f045dd9ecc0808f4593b8bbf285a8dd590ef`, supplied develop base
`af799688335f9a7dba7999a05e0e13f102c6c5ae`. No PR enumeration or GitHub mutations.
Incoming worktree contains an unfinished merge of
`bbc35234556c8802dd617daf23d9029cc2851045`, with one conflict in
`alembic/versions/043_invocation_quota_door.py` (documentation only).
Preserved unstaged and staged incoming changes in `../incoming-1572.patch`
and `../incoming-1572-index.patch`. Assumption: finish this already-started
sync, preserving all incoming staged changes rather than starting another merge.

Repair file scope: that migration conflict, this evidence report, and
`quality/vulture-baseline.json` only if the required scan identifies reviewed
retained debt. Inspect existing Goal/Run source, tests, relevant ADRs and gates
for acceptance; no unrelated feature repairs.

Supplied driver logs inspected: dependency sync succeeded; ruff check/format
passed; Goal tests 55 passed / 16 skipped; core inventory passed (15448).
These are prior evidence, not proof of the current merged working tree.
First-hand exact vulture scan passes (1,328 findings / reviewed identities);
no ledger amendment is justified. Execution-lifecycles fails: GoalStatus has
no already-landed authorization in trusted base `9bd1a93eefc4` (19 -> 20).
Docker probe fails at `unix:///var/run/docker.sock`; live PostgreSQL legs are
unavailable. Continue the existing merge conflict resolution and focused
validation; no policy bypass or speculative vulture change will be made.

The single conflict is resolved and staged. Only the migration docstring
changed: quota door stays parented on 055, followed by shipped 056/057,
then integrated 058/059/060 and new Goal 061. No migration DDL was changed.
Read accepted ADR-081226-9944, ADR-081226-a66b, ADR-087,
ADR-082426-2192 and ADR-092326-97c4; no competing authority or architectural
exception is introduced.

Focused core validation passed: 1,916 passed / 328 skipped / six adjacent
aiosqlite closed-event-loop warnings. Migration suite: 38 passed / 125 skipped.
Lifecycle regression: 28 passed / one failed at
`tests/test_check_execution_lifecycles.py:374`, same missing authorization.
Ruff lint/format pass (3,170 files). Alembic has single head 061. Convergence
freeze against supplied base passes. Core inventory passes (15,448 unique
identities). No tests added or removed by this repair; no new inventory delta.

## Commands executed in this pass

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1,328 identities. |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL; GoalStatus lacks trusted-base authorization. CI exact arguments checked at `.github/workflows/quality.yml:1501`. |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` | FAIL; daemon unavailable. |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py packages/maistro-core/tests/test_container_chat_runs.py -x -q` | 1,916 passed / 328 skipped / 6 warnings; full output `/tmp/1572-core-validation.log`. |
| `uv run pytest tests/migrations -x -q` | 38 passed / 125 skipped. |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed / 1 failed, reproducing lifecycle blocker. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS; 3,170 files. |
| `uv run alembic heads` | PASS; single head 061. |
| `uv run python scripts/check-m1-convergence-freeze.py --base af799688335f9a7dba7999a05e0e13f102c6c5ae` | PASS. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS; 15,448 unique identities. |
| `git diff --check; git diff --cached --check; git ls-files -u` | PASS; no unresolved index entries. |

## Acceptance review

Inspected actual Goal model, protocol, all three implementations, Workspace
seam, backend wiring, Run admission/storage and adjacent tests. Production
callers use the shared factory: server `main.py:344`, Hive
`backend/adapters/maistro_core.py:195`; `container.py:2362,2648` wires the
Goal store and `container.py:274-284` derives its Workspace-authorized seam.
No new execution or authorization path was introduced by this repair.
References below are under `packages/maistro-core/tests/goals/` unless noted.

| Criterion | Executed evidence / remaining limits |
| --- | --- |
| Three-backend Goal/GoalRevision round-trip | `test_goal_store_conformance.py:171` passes memory/SQLite; PostgreSQL UNVERIFIED. |
| Append-only revisions, stale refusal, concurrent single winner, terminal finality | Conformance at lines 197, 229, 278 passes memory/SQLite. Tests race calls through one store instance; independent durable writers and PostgreSQL UNVERIFIED. |
| Subgoal preserves parent/Project; recorded Agent transition | Conformance at lines 294, 333 passes memory/SQLite; PostgreSQL UNVERIFIED. |
| Admission binds immutable historical Goal revision, no implicit Goal outcome | `test_run_goal_binding.py:102,115` and outcome test pass memory/SQLite. Advancing a Goal revision *after* admission is not exercised by these tests; that scenario and PostgreSQL UNVERIFIED. |
| Two-Workspace principal isolation, foreign equals missing | Conformance at lines 398, 472 passes through real WorkspaceAuthorizer/ScopedGoalStore, memory/SQLite; PostgreSQL UNVERIFIED. |
| Production composition and shipped Container exposure | `test_goal_wiring.py:43,171` passes shared factory and authorized seam; source callers confirmed above. Missing/partial PG schema refuses startup (`goals/wiring.py:61-65`), including when SQLite is available. Live durable Hive/server deployment legs UNVERIFIED. |
| Restart and read same Goal/revisions/bound Run | `test_goal_restart_readback.py:36` passes SQLite store close/reopen; not an actual deployed Container/process restart. Live durable Hive/server and PostgreSQL UNVERIFIED. |
| No competing GoalRun/OrchestratorRun/executor/private lifecycle | Convergence freeze passes against supplied base; execution-lifecycle policy remains separately blocked. |
| Preserve merged 056/057 identities/ancestry; append coordinated new Goal identity | `tests/migrations/test_goal_installed_base_upgrade.py:389,416` graph and historical byte-identity checks pass. Head 061 follows 060. Central reservation UNVERIFIED. Conflict resolution preserves these identities. |
| Populated actual c560d4c/4675101 snapshot forward upgrades without restamping/reset | Live installed-base tests skipped; PG17 and PG18 UNVERIFIED. |
| After upgrade: three Goal tables, retained facts/keys/Run data, planner artifacts, head and reopened Goal/Run provenance | Live tests skipped; both majors UNVERIFIED. |
| Fresh install, unique IDs/single head, downgrade/refusal, reapplication; older quota ancestry compatibility audit | Static migration checks and head command pass; live PG17/18 and complete older-history compatibility audit UNVERIFIED. |

## Remaining blockers and handoff

- `scripts/ratchet_provenance.py:478` reads authorizations from the trusted
  base. The gate selected `9bd1a93eefc4`; neither supplied develop
  `af799688...` nor incoming merge parent `bbc35234...` contains a GoalStatus
  grant. Finishing this merge cannot supply that missing prerequisite. An
  independently landed authorization is required; this lane cannot amend
  lifecycle grants or disguise the legitimate domain lifecycle.
- `scripts/check-integration-scope.py:20-27` aggregates specialized PostgreSQL,
  object-storage, durable-events, strike-ladder, Hive E2E, wheel and Docker
  results, not vulture or execution-lifecycles. Captured check-run records
  provide no exact-starting-head producer result. The aggregate failure is
  UNRESOLVED; no fabricated `--result` evidence or aggregate-green claim.
- Docker's unavailable daemon prevents live PostgreSQL acceptance. Skipped
  legs are not passing evidence. Supply the actual failing integration
  producer log and working PG17/18 infrastructure before further repair.

Authored changes: conflict resolution in
`alembic/versions/043_invocation_quota_door.py` and this report. All other
staged changes are preserved incoming merge results, including upstream
ledger/grant changes; none were independently edited by this worker. No new
tests or count changes were authored, so no inventory-delta note is required.
Existing migration tests validate the documentation-only conflict repair.

Progress: checked 1 assigned item; done 1 merge-conflict repair; skipped 0
items; errors 1 reproduced policy blocker plus unavailable Docker. Overall
issue remains **BLOCKED**, not integration approval. Local commit completes
the salvaged merge and preserves these findings. No GitHub mutations or
issue-closure actions. No new item will be started in this pass.
