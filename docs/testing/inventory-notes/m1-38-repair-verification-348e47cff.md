# M1-A2 repair-phase verification record (head 348e47cff)

Focused re-validation of the merged branch (bd3f9213a + develop 60862b6c5) against the
new base. No code or test changes: every claim below was re-executed at this head,
not inherited from the earlier verification run (whose base was 8bb344e32).

## Gate results at 348e47cff

- `uv run ruff check .` / `ruff format --check .` — pass (2533 files formatted).
- `scripts/check-shipped-surface-truth.py` — pass. The merge's only ledger edits are
  develop's own (credential-store effect owners, design.py dispositions); the #1148
  `remove_project_membership` classification survived at quality/shipped-surface-truth.json:1850.
- `scripts/check-ratchet-provenance.py` — pass (7 metrics, no expansion).
- `scripts/check-suite-inventory.py` — pass, 13/13 suites match.
- `scripts/check-integration-scope.py` — exits 0 with all-success inputs for
  `pull_request` and in-scope `merge_group`; fail-closed re-proven (missing results and
  out-of-scope failures both exit 1).
- `uv run mypy` (canonical six-package command) — Success, 713 source files.

## check-vulture-baseline.py fails at base too — zero branch-attributable delta

The gate exits 1 at this head (1432 findings vs 1415 reviewed). Attribution was re-proven
against the CURRENT base, not assumed from the prior run: the raw Vulture finding multiset
(`path::message`, line-independent) is byte-identical between base 60862b6c5 and head
348e47cff — `python -m vulture packages tests --exclude '*/.venv/*'` yields exactly 1432
sorted identities on both, `diff` empty. The debt (hive-conductor routes, maistro-rsi,
stale ledger rows such as `api/projects.py::create_project`) is trunk/environment ledger
drift; the branch's nine-file diff contributes nothing. Repairing it here would require a
reviewed ledger grant, which is out of scope for an implementation branch.

## Runtime acceptance against a real PostgreSQL

pgvector:pg18 container, fresh `maistro_test` database, `alembic upgrade head` applied,
`MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=postgresql://…@127.0.0.1:55391/maistro_test`:

- `packages/maistro-core/tests/workspaces` + `packages/maistro-core/tests/projects`:
  218 passed, 3 skipped. Skips are the documented by-design pair (memory backend cannot
  express the single-writer interleaving; the PostgreSQL leg of
  `test_a_project_owning_runs_cannot_be_deleted` enforces via foreign key instead of a
  predicate).
- The 23 selected #1147/#1148 conformance cases pass on BOTH sqlite and postgres legs,
  including `test_concurrent_opposite_moves_cannot_both_commit_a_cycle`,
  `test_concurrent_membership_writes_leave_exactly_one_row`,
  `test_repeated_grants_update_the_one_canonical_membership`,
  `test_revoked_membership_is_gone_and_can_be_re_granted`,
  `test_the_tree_rejects_cross_workspace_moves_cycles_and_root_mutation`,
  both fresh-store restart-survival tests, and the pre-#1148 SQLite in-place upgrade test.
- Fail-closed deletion re-verified live via `pg_constraint` on the migrated database:
  `canonical_projects_parent_project_id_fkey`, `canonical_runs_project_id_fkey`,
  `canonical_project_memberships_project_id_fkey`,
  `canonical_project_resources_project_id_fkey` — all `FOREIGN KEY … REFERENCES
  canonical_projects(…) ON DELETE RESTRICT`, with NOT NULL project ids on runs and
  memberships.
- `packages/maistro-server/tests/api/test_projects_api.py` +
  `test_workspaces_api.py` + `packages/maistro-core/tests/test_container_wiring.py`:
  78 passed, including both #1148 revocation-authorization tests by name.

## Still environment-limited

A live `docker pull quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z` from this sandbox
still answers 401 on the manifest HEAD request (anonymous egress blocked here). The in-tree
fix is present and correct at `.github/workflows/ci.yml:320-339` (quay pin + 4-attempt
pull-only retry). Whether GitHub runners can fetch the pinned tag remains verifiable only
in CI; this worktree cannot prove it either way.
