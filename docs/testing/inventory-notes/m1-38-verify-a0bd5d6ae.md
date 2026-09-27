# M1-A2 independent verification at auto-38 head a0bd5d6ae (2026-09-25)

Verifier round for issue #38 at merge head `a0bd5d6ae` (develop base `2c8022fe`).
All evidence below was executed by the verifier in `/home/dev/Git/wt/auto-38`, not inherited.

## Executed evidence

- `uv run pytest packages/maistro-core/tests/test_container_wiring.py packages/maistro-server/tests/api/test_projects_api.py -q` -> 64 passed (matches driver check-3).
- `uv run ruff check .` -> All checks passed.
- `uv run pytest packages/maistro-core/tests/projects -q` -> 72 passed, 22 skipped (PG legs skip without DSN).
- `uv run pytest packages/maistro-core/tests/workspaces -q` -> 90 passed, 37 skipped.
- PG legs on live container `auto-38-repair-pg` (pgvector:pg18 @ 127.0.0.1:5590, `alembic_version`=036_audit_log_org_scope == `alembic heads`):
  `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:5590/maistro uv run pytest packages/maistro-core/tests/projects packages/maistro-core/tests/workspaces -q` -> 218 passed, 3 skipped.
  Residual skips are by-design and documented in-code: test_scope_store_conformance.py:330 (FK-enforced backend) and test_workspace_store_conformance.py:455 (single-writer interleaving).
- Named acceptance tests PASSED on both sqlite and postgres:
  - test_workspace_creation_provisions_exactly_one_persisted_root_project
  - test_the_tree_rejects_cross_workspace_moves_cycles_and_root_mutation
  - test_concurrent_opposite_moves_cannot_both_commit_a_cycle (#1147)
  - test_concurrent_membership_writes_leave_exactly_one_row (#1148)
  - test_revoked_membership_is_gone_and_can_be_re_granted / test_a_membership_survives_a_fresh_store_and_a_removal (#1148)
  - test_project_resources_flow_downward_not_upward_or_to_siblings; test_denies_accumulate_and_win_over_descendant_grants
  - test_delete_requires_an_explicitly_empty_project; test_memberships_and_resources_survive_with_downward_visibility
- Live schema in `auto-38-repair-pg`: `ix_canonical_projects_one_root` (UNIQUE workspace_id WHERE is_root); PK (project_id, principal_id) on canonical_project_memberships; RESTRICT FKs canonical_projects.parent_project_id, memberships/resources/runs.project_id; project_id NOT NULL on canonical_project_resources and canonical_runs.
- Gates: `check-vulture-baseline.py` exit 0; `check-shipped-surface-truth.py` complete; `check-suite-inventory.py` 13/13 suites match; `check-integration-scope.py --event-name pull_request` (workflow invocation) exit 0, fail-closed listing required specialized CI evidence (docker-build, durable-events, hive e2e, MinIO, postgres pg17/pg18, strike-ladder, wheel-imports) — those remote CI runs remain externally UNVERIFIED per the PR snapshot.
- `uv run mypy` (documented 6-package command) -> Success, 713 source files.

## Findings resolution

- pg_store `_purge` unreachable: `_purge` absent under `packages/maistro-core/src/maistro/workspaces/` (grep). Moot.
- projects.py revocation route ledger: `DELETE /{project_id}/memberships/{principal_id}` disposition present in `quality/shipped-surface-truth.json`; surface-truth gate green.
- integration-scope MinIO/PG: gate exits 0 fail-closed; image pull concern addressed in-tree by checksum-verified `go install` build (ci.yml).
- Prior non-fast-forward push block: `origin/auto-38` == local HEAD == `a0bd5d6ae` (fetch dry-run shows no pending update); block moot, no push performed by verifier.

## Closure-keyword review

PR #1323 body (snapshot): "Refs #38" only — no fixes/closes/resolves. Commit messages in `2c8022fe..a0bd5d6ae`: no closure keywords. No premature issue closure.

## Scope note

Local lane verification only; writer handoff. Specialized CI evidence (MinIO/Hive/docker/PG matrix) not claimed.
