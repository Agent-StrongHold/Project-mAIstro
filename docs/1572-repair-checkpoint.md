# Issue 1572 repair checkpoint

Frozen scope: issue #1572 only; assigned worktree `/home/dev/Git/wt/auto-1572`, starting HEAD `8bc958bfd8e5ed3e530393f04a44349286d15578`, supplied base `675db8be6c41b020ffffb224b2748c159c78a122`. Worktree initially clean. Process supplied dispatch context and check-0 through check-4 logs only; no GitHub enumeration or mutation.

Role assumption: writer, as explicitly assigned a repair. Inspect existing Goal implementation, adjacent tests, ADRs and CI commands before changes. Prior lifecycle authorization finding is not assumed current. Only vulture ledger edits are permitted; other authorization blockers must be reported, not bypassed.

Inspection scope: canonical Goal package and its existing integration/tests, relevant ADRs and migration/CI files from the supplied dispatch. Frozen edit list: this checkpoint only unless an actual code defect is demonstrated; no other issue will be processed.

Fresh initial results: CI-exact vulture passed (1326 reviewed identities / findings, no unclassified); no ledger amendment warranted. Lifecycle gate failed at the assigned HEAD: `maistro.goals.model::GoalStatus` lacks already-landed authorization (19 -> 20; selected trusted base `e46ad6708fda`). Docker probe failed at the prescribed socket: daemon unavailable. Driver check-0 through check-4 logs were read: sync/lint/format/inventory passed; focused tests 55 passed / 16 skipped. Previous job result and report were inspected, not accepted as fresh proof. Missing grant remains an external prerequisite; do not manufacture an in-branch grant or rename the required domain state to evade policy.

Read primary issue body (including installed-base migration acceptance), accepted hierarchy/runtime ADRs, ADR-032 lifecycle authorization contract, adjacent Run binding/restart tests, and integration-scope workflow. No conflicting architecture instruction needs reconciliation: Goal domain state stays separate from execution state and still requires prior authorization. Fresh focused Goal/parity tests and static migration tests exited 0; lifecycle regression tests and explicit supplied-base gate exited 1. Convergence freeze with supplied base, Ruff lint and formatting passed. Log inspection: focused tests **55 passed / 16 skipped**; migration tests **2 passed / 23 skipped**; lifecycle regression **28 passed / 1 failed**, at `tests/test_check_execution_lifecycles.py:374`. Integration-scope aggregates specialized same-candidate producer results, not this lifecycle job; its reported failure cause must not be guessed.

Integration-scope classification/resolution succeeded against the supplied base. Required producers: docker-build, durable-events, hive-conductor-e2e, hive-conductor-e2e-ui, object storage (MinIO), postgres (pg17), postgres (pg18), strike-ladder, wheel-imports. Frozen dispatch has no check-run evidence for exact starting HEAD. Producer success and cause of reported aggregation failure remain UNRESOLVED; no remote re-enumeration was performed. The supplied base also contains no GoalStatus authorization, and its merge base with HEAD is `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`. No conflict exists to resolve and a sync with that base cannot supply the missing grant.

Fresh core inventory passed. No test was added or modified, so no inventory delta is needed. Production path traced: Hive `backend/adapters/maistro_core.py:195` and server `maistro_server/main.py:344` call `create_container`; `container.py:2362,2648` selects/exposes the store, `:284` exposes the Workspace-authorized wrapper. Wiring fails closed when a selected PostgreSQL pool lacks Goal tables. These source paths and factory tests are not proof of full application restart.

## Acceptance evidence at the assigned HEAD

Test paths are relative to `packages/maistro-core/tests/goals/` unless specified.

| Criterion | Executed evidence and limits |
| --- | --- |
| Goal/revision round-trip on three backends | `test_goal_store_conformance.py:171` passed on memory/SQLite; PostgreSQL skipped, UNVERIFIED. |
| Append-only revisions, stale refusal, exactly one concurrent winner | Conformance `:197,229,278` passed on memory/SQLite. PostgreSQL and independent-connection race acceptance UNVERIFIED. |
| Subgoal parent/Project and recorded ownership transition | Conformance `:294,333` passed on memory/SQLite, including cross-scope parent rejection and explicit old/new Agent records. PostgreSQL UNVERIFIED. |
| Admission binding and immutable historical revision | `test_run_goal_binding.py:102,115` passed on memory/SQLite through admission and Run terminalization. PostgreSQL UNVERIFIED. Existing reopen test advances Goal before admission, not afterward; preservation after a subsequent Goal revision advance remains UNVERIFIED. |
| Workspace authorization; foreign equals missing | Conformance `:398,472` passed on memory/SQLite through the canonical Workspace authorizer. PostgreSQL UNVERIFIED. |
| Production composition and shipped Container | `test_goal_wiring.py:43,158` passed factory exposure and scoped access; source traces both applications to that factory. SQLite store reopen test passed, but durable full Hive/server restart and PostgreSQL durability remain UNVERIFIED. |
| No competing executor or private lifecycle | `check-m1-convergence-freeze.py --base 675db8be6c41b020ffffb224b2748c159c78a122` passed. Separate lifecycle authorization gate fails; this is not waived by architecture classification. |
| Preserve merged 056/057 identities/ancestry; append unused Goal migration | Two static `test_goal_installed_base_upgrade.py` tests passed including historical byte equality; current Goal migration is 062 after 061. Central allocation coordination remains UNVERIFIED. |
| Populated upgrades from actual historical snapshots | Live PostgreSQL fixtures skipped. Normal forward upgrade from c560d4c/4675101 on PG17 and PG18, without stamp reset, UNVERIFIED. |
| Goal tables usable after each upgrade; old facts/keys/Runs/planner artifacts preserved; durable provenance reopen | PostgreSQL legs skipped, UNVERIFIED on both supported majors. SQLite reopen is not substituted for these tests. |
| Fresh install, unique IDs/single head, downgrade/refusal, reapplication; quota-door supported-history audit | Static identity/graph assertions passed. Live migration legs and full earlier shipped-history compatibility remain UNVERIFIED. |

## Executed commands and outcomes

Validation used 900–1800-second command timeouts. All commands ran in the assigned worktree; no services or background commands were started.

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
  PASS: 1326 reviewed identities = 1326 findings, no unclassified
uv run python scripts/check-execution-lifecycles.py
  FAIL: GoalStatus has no trusted-base authorization
RATCHET_BASE_REV=675db8be6c41b020ffffb224b2748c159c78a122 uv run python scripts/check-execution-lifecycles.py
  FAIL: same missing grant at trusted merge base e46ad6708fda
DOCKER_HOST=unix:///var/run/docker.sock docker info
  FAIL: cannot connect to daemon
uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q
  PASS: 55 passed, 16 skipped
uv run pytest tests/test_check_execution_lifecycles.py -x -q
  FAIL: 28 passed, 1 failed at line 374 (same authorization blocker)
uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q
  PASS: 2 passed, 23 skipped (not live migration evidence)
uv run python scripts/check-m1-convergence-freeze.py --base 675db8be6c41b020ffffb224b2748c159c78a122
  PASS: no unapproved new architecture island
uv run ruff check .
  PASS
uv run ruff format --check .
  PASS: 3205 files already formatted
uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests
  PASS: 15797 unique nodes, no duplicates
```

Integration-scope resolution used the actual `git diff --no-renames --name-only <supplied-base>...HEAD` paths with `uv run python scripts/ci_merge_group_scope.py --json`, then `uv run python scripts/check-integration-scope.py --event-name pull_request --scope-json <output> --required-json`; both succeeded. Resolving requirements does not execute or approve the nine producers.

## Disposition

**BLOCKED**. Only `docs/1572-repair-checkpoint.md` changes. No source, tests, workflows, inventory, ledgers or grants were altered; no evidence justifies a vulture amendment. ADR-032 requires an independently landed grant before the candidate-only GoalStatus can pass. This lane cannot land it or disguise the required domain lifecycle to evade it. The supplied base lacks that grant, so merging it would not fix this blocker. Existing work is preserved; no GitHub mutations occurred.

Required handoff: owner lands the lifecycle authorization separately, supplies exact-candidate specialized CI results and reachable PG17/18 infrastructure, then rerun blocked acceptance. No integration approval or closure claim.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: external trusted-base authorization and missing acceptance infrastructure/evidence}. The one error is the lifecycle gate blocker, also reproduced by its regression test; Docker is an additional environmental limitation. Evidence report committed locally.
