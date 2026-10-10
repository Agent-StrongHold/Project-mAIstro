# Issue 1572 repair checkpoint

## Frozen scope

- Assigned issue: #1572 only; branch `auto-1572` in the assigned worktree.
- Starting head: `2cb13ec889218fe45a768fbe5545604ea6b35d00`.
- Supplied develop base: `30a8ff9d7307deb5595a634e0d359810538e313f`.
- Input snapshot: `/home/dev/maistro/jobs/f0c98796aad04e8982363642928c3392/dispatch-context.json`; no GitHub mutations or re-enumeration.
- File scope: canonical Goal implementation and adjacent tests, relevant migration/composition/ADR files, named gate scripts/workflow, permitted vulture ledger if executed evidence requires it, and this report. No unrelated repairs or authorization/other ledger changes.

## Initial evidence and assumptions

The worktree started clean at the exact assigned head. The five supplied check logs report dependency sync, Ruff lint/format and inventory success; focused tests report 55 passed and 16 skipped. These are driver results, not proof of skipped PostgreSQL acceptance. The supplied prior result reports a missing trusted-base GoalStatus authorization and unavailable Docker. Both require fresh validation. `integration-scope` failure has no supplied producer log; its cause is unresolved, not assumed to be vulture.

Role assumption: this is a writer repair lane. Preserve existing implementation; change production code only for demonstrated defects. A missing already-landed authorization cannot be repaired by adding a candidate grant.

## Fresh gate/environment results

- CI-exact vulture command passed: 1326 reviewed identities / 1326 findings, zero unclassified. No vulture ledger amendment is justified.
- `uv run python scripts/check-execution-lifecycles.py` failed: `maistro.goals.model::GoalStatus` has no already-landed authorization (19 classified / 20 discovered). The default gate selected local trusted base `e46ad6708fda`, which differs from the supplied base; explicit-base verification follows.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` failed: cannot connect to the daemon. PostgreSQL acceptance remains unavailable in this environment.
- ADR-032 explicitly requires already-landed grants for candidate-only lifecycle identities. This repair will not disguise GoalStatus or alter gate/authorization policy.
- The existing tracked `issue-1572-repair-checkpoint.md` was preserved verbatim; this round's report is the separate `goal-1572-repair-f0c98796.md`.
- Focused Goal/schema-parity tests: **55 passed, 16 skipped** (1.89s).
- Lifecycle gate regression tests: **28 passed, 1 failed** (13.79s), `tests/test_check_execution_lifecycles.py:374`, reproducing the same missing GoalStatus authorization.
- Migration installed-base/chain tests: **2 passed, 23 skipped** (0.82s). PostgreSQL upgrades, downgrade/reapplication, preserved populated data and PG17/18 durability are **UNVERIFIED**.
- Explicit supplied-base lifecycle run (`RATCHET_BASE_REV=30a8ff9d7307deb5595a634e0d359810538e313f`) also fails with the same trusted merge base `e46ad6708fda` and missing grant.
- Ruff lint/format passed (3205 files formatted); suite inventory passed (15797 core tests, no duplicates); `git diff --check` passed.
- An initial convergence-freeze invocation omitted its required `--base` and exited 2; the corrected invocation with the supplied base passed: no unapproved new architecture island. Two guessed Hive source paths were not found; skipped, no source files changed. Actual Hive composition resolves to `packages/hive-conductor/backend/adapters/maistro_core.py:195`, which calls `create_container`; server calls it at `packages/maistro-server/src/maistro_server/main.py:344`.
- `git merge-base HEAD 30a8ff9d7307deb5595a634e0d359810538e313f` resolves to `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`, explaining the gate's baseline. The supplied base's authorization file also has no `maistro.goals.model::GoalStatus` entry. No sync conflict exists; a merge cannot supply the missing grant from this supplied base.
- Integration-scope classifier and required-check resolver ran successfully using the actual diff against the supplied base. Required producers: docker-build, durable-events, hive-conductor-e2e, hive-conductor-e2e-ui, object storage (MinIO), postgres (pg17), postgres (pg18), strike-ladder, wheel-imports. Their same-candidate successful check-run evidence is unavailable; the remote aggregation failure remains **UNRESOLVED**. The lifecycle failure is a separately reproduced quality failure, not asserted to be an integration-scope producer.

## Acceptance map (this round)

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Goal/revision round-trip on all three backends | Shared `test_goal_store_conformance.py` passed for memory/SQLite; PostgreSQL skipped, **UNVERIFIED**. |
| Append-only, stale revision refused, exactly one concurrent winner | Shared conformance tests passed for memory/SQLite; PostgreSQL **UNVERIFIED**. |
| Parent/Project lineage and recorded Agent reassignment | Shared conformance tests passed for memory/SQLite; PostgreSQL **UNVERIFIED**. |
| Admission binding and immutability | `test_run_goal_binding.py` passed for memory/SQLite admission and Run transitions; PostgreSQL **UNVERIFIED**. A historical Run after subsequent Goal revision advancement is **UNVERIFIED**: existing restart test advances the Goal before admission, not after. |
| Two-Workspace isolation; foreign equals missing | Shared conformance authorization tests passed for memory/SQLite through `ScopedGoalStore` and `WorkspaceAuthorizer`; PostgreSQL **UNVERIFIED**. |
| Shipped Container exposes store | `test_goal_wiring.py` passed for Container exposure, authorized read/write seam, SQLite selection and fail-closed PostgreSQL schema probes. Source traces both product compositions to `create_container`; live durable restart through both full products **UNVERIFIED**. |
| No competing execution authority | Convergence-freeze passed with supplied base. ADR-062 retired legacy top-level execution; this round introduces no execution code. Lifecycle quality authorization still fails independently. |
| Preserve merged migration identities | Two static installed-base tests passed, including identity/ancestry and byte identity to historical snapshots. Diff of merged 056/057 files against supplied base is empty; Goal appends as 062 after 061. Central allocation coordination beyond this snapshot **UNVERIFIED**. |
| Populated historical upgrades and preserved records/indexes | PostgreSQL fixtures from c560d4c/4675101 were skipped; **UNVERIFIED** on PG17/18. No version stamp was changed. |
| Fresh install, downgrade/refusal, reapplication, durable provenance restart | SQLite store reopen test passed; PostgreSQL migration legs skipped; full historical quota-door compatibility and both supported PostgreSQL majors **UNVERIFIED**. |

## Commands

All validation used the assigned worktree and long command timeouts (600s).

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run python scripts/check-execution-lifecycles.py
RATCHET_BASE_REV=30a8ff9d7307deb5595a634e0d359810538e313f uv run python scripts/check-execution-lifecycles.py
DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'
uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q
uv run pytest tests/test_check_execution_lifecycles.py -x -q
uv run pytest tests/migrations/test_goal_installed_base_upgrade.py tests/migrations/test_migration_chain.py -x -q
uv run python scripts/check-m1-convergence-freeze.py --base 30a8ff9d7307deb5595a634e0d359810538e313f
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests
git diff --check
```

The integration-scope resolution used `ci_merge_group_scope.py --json` with `git diff --no-renames --name-only <supplied-base>...HEAD`, then `check-integration-scope.py --event-name pull_request --scope-json <classifier-output> --required-json`. Resolution success is not producer success.

## Disposition and handoff

**BLOCKED**. Only this evidence report changes in this round; no production code, tests, inventory, grants or ledgers changed. Existing implementation was preserved. No meaningful in-scope vulture repair is indicated by the clean scanner. ADR-032 and repository policy prohibit self-authorizing the newly discovered lifecycle, and this lane cannot land the prerequisite grant. An authorized separate grant must land first, followed by a sync and gate rerun. A working PostgreSQL environment and actual same-SHA specialized CI evidence are also required before readiness can be claimed.

Progress: checked 1 assigned issue; done 0 repairs; skipped 0 issues; errors 1 unresolved lifecycle gate blocker (also reproduced by its test). Next: owner resolves the trusted-base authorization prerequisite and supplies PG17/18 validation infrastructure; then rerun skipped acceptance and integration producers. Report committed locally; no GitHub mutation.
