# Independent M1-A2 verification at a287cb2e (issue #38, PR #1323 lane auto-38)

Date: 2026-09-27 (verifier round). Head `a287cb2e2421d2a763261d9d43c51206939bf538`, develop base `31bddeb7b1eda5e671e0a82d62d4f47accdb9af1`. Worktree clean at start and untouched (read-only review; this note is the only addition).

## Driver checks reproduced

- `uv run pytest packages/maistro-core/tests/test_container_wiring.py packages/maistro-server/tests/api/test_projects_api.py -q` -> 66 passed (also driver check-3.log).
- `uv run ruff check .` -> clean. `ruff format --check` -> 2569 files formatted (driver logs).

## Acceptance evidence executed by this round

1. One immutable Root Project per Workspace
   - `uv run pytest packages/maistro-core/tests/projects/ -q` -> 72 passed, 22 PG skips.
   - With PG leg: `MAISTRO_TEST_PG_DSN=... uv run pytest packages/maistro-core/tests/projects/ -q` -> 93 passed, 1 skip. Covers idempotent `create_root` returning the same project id on a fresh store; root move/delete refused.
   - Durable workspace create roots in-transaction: `uv run pytest packages/maistro-core/tests/workspaces/ -q` -> 90 passed / 37 skipped; with PG DSN -> 125 passed, 2 skipped (`create_root_in(conn, ...)` on the same transaction in `workspaces/sqlite_store.py:167`, `workspaces/pg_store.py:135`).

2. Acyclic tree, no cross-Workspace moves, concurrent SQLite reparenting (#1147)
   - `test_concurrent_opposite_moves_cannot_both_commit_a_cycle` (both backends) and `test_an_unlocked_writer_cannot_collide_with_a_locked_one` (BEGIN IMMEDIATE interleaving) pass in the 93-passed run above.

3. Durable objects belong to exactly one Project
   - Resource/membership workspace-match refusals + `test_a_project_owning_runs_cannot_be_deleted` pass (same run).

4. Membership lifecycle (#1148)
   - `test_repeated_grants_update_the_one_canonical_membership`, `test_concurrent_membership_writes_leave_exactly_one_row`, `test_revoked_membership_is_gone_and_can_be_re_granted`, pre-#1148 legacy SQLite in-place migration test — all pass (both legs).
   - API: revoke DELETE route tests + delegated-regrant merge tests in `packages/maistro-server/tests/api/test_projects_api.py` pass (66 passed).

5. Downward-only flow; denies win
   - `test_memberships_and_resources_survive_with_downward_visibility`, `test_denies_accumulate_and_win_over_descendant_grants`, `test_inherited_deny_blocks_delegation_even_below_new_grant` pass.

6. Illegal moves/deletions fail closed
   - Root move/delete, cross-workspace, cycle, self-parent, non-empty delete, runs-owned delete — all pass (both legs).

7. Scope survives restart; historical Runs immutable
   - Fresh-store survival tests (both backends) pass; `test_spine_conformance.py` asserts `reloaded.project_id == project_id` (line 150) and `ProjectNotEmpty` guards delete: `MAISTRO_TEST_PG_DSN=... uv run pytest packages/maistro-core/tests/runs/test_spine_conformance.py -x -q` -> 361 passed. Retention scope conformance with PG: 24 passed, 2 skipped.

8. memory/SQLite/PostgreSQL conformance
   - Executed all three: in-memory (test_scope.py), SQLite + PostgreSQL parametrized conformance (projects/, workspaces/), spine + retention PG legs. Throwaway pgvector:pg17 on 127.0.0.1:55977, `DATABASE_URL=... uv run alembic upgrade head` -> `alembic current` = `042 (head)`, container stopped after.

## Prior findings disposition

- projects.py delegated POST replaced the canonical row -> FIXED at f0be0a5c4; merge-not-replace preserves owner-issued grants/delegable/role/denies, escalation guarded; regression tests `test_a_non_owner_delegated_regrant_preserves_owner_issued_authority` and `test_a_non_owner_delegated_post_cannot_grant_beyond_own_delegation` seen passing.
- vulture baseline exit 1 -> ROOT-CAUSED, not lane-caused. (a) The prior round's exact command scopes paths to core+server only, which deterministically false-fails on any tree because the trusted ledger spans all packages (canvas/evolve/bootstrap identities appear "no longer found"). (b) The canonical CI invocation (bare `scripts/check-vulture-baseline.py`, per .github/workflows/quality.yml:825) also exits 1 at this head, but every drift-named file (hive-conductor/backend/**, maistro-server api health/tasks/workspaces/main.py, canvas, evolve, bootstrap) is byte-identical between base and head (`git diff 31bddeb..a287cb2e` on those paths is empty), `quality/vulture-baseline.json` and the vulture >=2.14 pin are unchanged, and the branch's new route `remove_project_membership` is NOT flagged. Identical inputs + identical tool => the gate fails identically at the develop base: stale-ledger/tool drift owned outside this lane; requires a reviewed ledger grant.
- spine conformance PG failure (DB at Alembic 036) -> ROOT-CAUSED as a stale inspection DB; after `alembic upgrade head` (042) the suite passes 361/361.

## PR hygiene

- PR #1323 body snapshot and all commits in 31bddeb..a287cb2e contain no fixes/closes/resolves keywords (only "Refs #38").

## Not actionable here

- Previous round's push rejection (60eaff2d3 -> remote auto-38 non-fast-forward): pushing is prohibited for the verifier; the remote branch is ahead of local. Integration/reconcile lane must reconcile without force-push. Skipped.
