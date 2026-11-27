# Verification round — #37 at cb778dda06 (independent re-run)

Round L37-verify (job 2f984864): re-executed at the exact head `cb778dda06`
(docs-only over the merged head `aa42068120`, verified via
`git diff --stat aa42068120..cb778dda06`). Read-only except this note; no
GitHub actions.

## formal-conformance reproduced green at cb778dda06 itself

The prior round executed the gate at `aa42068120` and inferred validity for the
docs-only child. This round re-ran CI's exact steps **at cb778dda06** against a
fresh CI-shaped database (pgvector/pgvector:pg18, `maistro:maistro`, db
`maistro_test`):

- `alembic upgrade head` on a dropped/recreated DB: full chain → **071**;
  `canonical_workspace_deletions` + `canonical_orphan_project_quarantine` exist.
- `pytest formal/models/ --timeout=300 --hypothesis-seed=0` → **672 passed**.
- `python scripts/extension_lifecycle_proof.py` → **13/13 stages, 62/62
  checks, exit 0**.
- `check-formal-oracle-independence.py --base 80242f2852` → OK;
  `check-m1-convergence-freeze.py --base 80242f2852` → OK.

**Operational finding for future rounds:** a local PG left stamped at 071 with
071's DDL missing (e.g. tables dropped after `alembic_version` was written)
makes `PgWorkspaceStore.create` fail with
`UndefinedTableError: relation "canonical_workspace_deletions" does not exist`,
which surfaces as 4 formal-model failures (`TestRunLeaseFenceMachine`,
`TestExecutionLifecycleMachine` + 2 earned-completion tests) and can masquerade
as a real gate regression. `alembic current` reports 071 and is not evidence
the DDL exists. Recreate the database and re-apply the chain before debugging
the tree.

## Prior finding: RESTRICT expectation (fixed at head by 40f961d1ef)

`personas/test_durable_store_pg.py` expects
`asyncpg.exceptions.RestrictViolationError` (SQLSTATE 23001) at the RESTRICT
fence. With `MAISTRO_TEST_PG_DSN` set:
- `...::test_persona_migration_cascade_is_enforced_by_the_database_itself` → **1 passed**;
- full `test_durable_store_pg.py` → **14 passed**.

## PG acceptance evidence at this head (DSN set, pgvector:pg18)

- persistence `test_workspace_scope_fence_pg.py` +
  `test_workspace_orphan_disposition_migration.py` → **9 passed**.
- `tests/projects tests/workspaces tests/persistence` → **1544 passed,
  89 skipped** (skips are memory/sqlite-parametrized legs, not DSN-gated PG
  arcs; the fence suite above gates on the DSN and passed).
- Hive authority/journal/recovery:
  `test_workspace_authority(_durable)`, `test_canonical_recovery_cadence`,
  `test_manual_fire_canonical`, `test_schedule_manual_fire_canonical` →
  **69 passed, 0 skipped**.
- Salvaged repair 4601ecce18 (`tasks/admission.py` store-bound `_existing_runs`)
  re-proven at head: `tests/tasks/test_workspace_routing.py` → **22 passed**,
  including
  `test_deleting_the_default_workspace_leaves_existing_run_operations_working`.
  (Fail-before proof for that test was executed by the prior round and is
  recorded there; this read-only round confirms pass-after only.)

## Hygiene

- `ruff check .` clean; `ruff format --check .` clean (3703 files).
- `scripts/check-suite-inventory.py` → **21/21 suites match, 37436 IDs,
  0 duplicates**.
- `scripts/check-durable-table-inventory.py` → ok (129 durable tables).
- `quality/` delta vs develop `80242f2852` is additive-only
  (`durable-table-retention.json` +25/-0); merge `aa42068120` brought only
  develop's own edits — no row loss.
- Closure keywords: none in the 19 commits `80242f2852..HEAD`; PR #2525 body
  says "Refs #37" only (live refresh head matches cb778dda06).
