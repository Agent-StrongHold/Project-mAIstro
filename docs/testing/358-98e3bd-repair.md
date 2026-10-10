# Issue #358 repair checkpoint (98e3bd)

## Frozen scope

Only issue #358, assigned branch `auto-358`, initial HEAD
`38efa40db2d2562491ff063435bb2d25e7a1a1bd`, supplied develop base
`30144ad0f508a6ee5d67c719ed04df5692fb64ea`.
Process the supplied dispatch evidence and check-0 through check-7 logs; resolve
the existing merge's two migration-test conflicts; validate audit pagination,
virtualization, integration-scope, and the requested vulture gate. No GitHub mutations.
Implementation inspection is limited to the audit routes/query/stores, frontend
AuditLog, related tests/migrations, repository instructions and relevant ADRs/gates.

## Incoming state preserved

The worktree arrived mid-merge, MERGE_HEAD and origin/develop both equal the
supplied base. Existing staged changes are develop's merge, not new lane work.
Backups (outside the worktree): `../incoming-358-98e3bd3-working.patch`,
`../incoming-358-98e3bd3-index.patch`, `../incoming-358-98e3bd3-conflicts.txt`.
Conflicted files: `tests/migrations/test_capability_invocation_effect_index_migration.py`
and `tests/migrations/test_task_admission_generation_upgrade.py`.
Assumption: finish this already-started merge rather than fetch a moving scope.
Validation pending; previous claims are not accepted as evidence.

## Evidence checkpoint

Driver check-1 fails on unresolved conflict markers. Inspection also finds two
revision `055` migrations after the develop merge: admission generations and
this lane's unlanded audit indexes. Repair will re-parent only audit indexes to
`056` and preserve both sets of migration assertions. Driver check-3 reaches
the live PM audit route but receives an unexpected error (investigation pending).
The supplied PR review concerns are already represented by pagination, scope,
streaming, cursor-spelling, snapshot and stale-request tests; they still require
fresh execution. The retention owner decision excludes legal policy from core.

## Repair checkpoint

Resolved both test conflicts, preserving transactional downgrade assertions and
all chain ancestors. Renumbered only the unlanded audit-index migration from
055 to 056, parent 055. `uv sync --locked --extra dev` passed;
`uv run pytest tests/migrations/test_capability_invocation_effect_index_migration.py -x -q`
passed (2 tests); `uv run alembic heads` reports the sole head 056.

The requested exact Vulture command fails: four live `get_page` methods are
absent from the trusted base, although already retained by the candidate
ledger. It explicitly requires a previously landed grant; duplicating those
identities cannot repair it. No ledger/grant or scanner changes made.
The first guessed ADR-073 filename was not found; skipped it and resolved the
actual filename with a local glob (`ADR-073-warden-sentinel.md`).

## Focused validation checkpoint

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2,956 files).
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  failed for nine missing specialized producer results. This checks current-SHA
  CI evidence, not local unit-test outcomes. No fabricated results supplied.
- `node --test tests/ci/integration-scope.test.cjs`: 12 passed; aggregator
  semantics only, not evidence that producers ran.
- Focused Hive audit/convergence/routes/noop suite: exit 0; raw output saved to
  the job directory's `repair-hive.log`.
- Docker prerequisite failed: `DOCKER_HOST=unix:///var/run/docker.sock docker ps`
  cannot connect to the daemon. Live PostgreSQL validation remains unavailable;
  no shared database has been modified.
- Read ADR-068 and ADR-073: canonical decision audit stays admin-only, using the
  existing Sentinel authority. The migration-only repair changes no execution,
  event, Goal or authorization authority.
- The guessed top-level Hive Playwright config path does not exist; skipped.
  Browser execution is not claimed on the strength of source inspection.
- Updated existing live audit-index round-trip test to use predecessor 055,
  preserving checks that admission columns and audit rows survive downgrade.
  Inventory delta is zero; note: `inventory-notes/358-98e3bd-migration.md`.

## Executed results

- Hive focused command: `uv run pytest
  packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **77 passed**. Million-row index build 9.749s; first page 0.0007s, scoped page
  0.0004s; maximum query work below 2,800 SQLite VM instructions.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py
  -x -q -s`: **45 passed, 4 PostgreSQL cases skipped**. Million-row canonical
  SQLite load 9.805s; maximum query work 3,400 VM instructions.
- `uv run pytest tests/migrations/test_capability_invocation_effect_index_migration.py
  tests/migrations/test_migration_chain.py
  tests/migrations/test_task_admission_generation_upgrade.py -x -q`:
  **2 passed, 28 live-PostgreSQL cases skipped**. No DSN configured.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e
  --suite packages/maistro-core/tests`: passed (3,393 / 23 / 13,432 tests).
  Driver check-6 used the unregistered `packages/hive-conductor/tests` recipe;
  no gate or inventory recipe was changed to conceal that invocation error.
- `npm run build` in `packages/hive-conductor/frontend`: passed TypeScript and
  Vite production build. Browser runtime tests remain UNVERIFIED.
- Fresh foreground Python probe called production `page_entries(limit=1)`
  on counted mappings: visited 100/100 rows and 10,000/10,000 rows respectively.
  `retention()` returned `corpus_purge: none`.
- Final pre-commit ruff lint/format and `git diff --check`: passed.
- Ledger preservation check `git diff --numstat origin/develop -- quality/`:
  only the lane's four existing Vulture identities differ; no rows lost.
- Driver check-3's live PM failure is `200 == 403` at
  `packages/hive-conductor/tests/e2e/test_pm_workflow_api.py:271`; its response
  is an old array, unlike this worktree's envelope. External target provenance
  is not established; not repaired by changing expectations. In-process tests
  freshly exercise both bound canonical and unbound legacy production routes.

## Acceptance disposition

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Bounded cursor, stable ordering, maximum size | Hive and core tests pass for SQLite/memory; PostgreSQL runtime UNVERIFIED. |
| Scope filters before database pagination | Scope/filter/convergence tests pass, including pre-I/O admin rejection for canonical audit (ADR-073) and SQL legacy personal scopes. |
| Incremental loading and virtualization | Frontend build passes; inspected generation checks, cursor loads and virtual slices. Browser runtime UNVERIFIED. |
| Filters/export/retention without browser corpus loading | Filter and lazy/capped export tests pass; UI exports via download link. Retention reports bounds only; no purge mechanism on this surface. Full retention behavior UNVERIFIED. |
| Measured large-dataset query/index strategy | Both SQLite million-row work-bound tests pass with measurements above. PostgreSQL million-row envelope UNVERIFIED. |
| Concurrent inserts/cursor stability/isolation/max/empty/million-row tests | 122 focused tests passed, four PostgreSQL cases skipped. |
| Corpus-independent initial-page cost | Durable SQLite bound proven; memory fallback NOT MET (counted full-scan probe). |
| Bounded browser memory/DOM | Source caps retained rows at 500 and renders visible slice plus overscan; browser runtime UNVERIFIED. |

## Handoff

**BLOCKED**, not integration approval. The existing merge conflict and duplicate
migration revision are repaired. Named gate prerequisites remain unresolved:
Vulture requires trusted-base approval for the four already-reviewed candidate
identities (`quality/vulture-baseline.json:1001,1010,1072,1171`), and integration-scope
requires genuine specialized current-head check results. Do not duplicate ledger
rows, add dummy callers, invent successful check results or relax gates.

New lane changes (separate from preserved incoming develop merge):
- Rename `alembic/versions/055_audit_cursor_indexes.py` to
  `alembic/versions/056_audit_cursor_indexes.py`; update revision/parent metadata.
- Resolve `tests/migrations/test_capability_invocation_effect_index_migration.py`
  and `tests/migrations/test_task_admission_generation_upgrade.py` conflicts.
- Update `tests/migrations/test_migration_chain.py` audit round-trip predecessor.
- This report and `docs/testing/inventory-notes/358-98e3bd-migration.md`.

All incoming staged develop changes are preserved in the merge commit. No
pushes, GitHub mutations, gate weakening, ledger/grant edits, background commands
or destructive git operations. Backups remain at the paths above. Build output
is ignored, not committed. Live migration/PG and browser validation remain risks.

Progress: checked 1, done 0 complete issue repairs (merge repair completed),
skipped 0 issues, errors 2 gate blockers. Next: trusted-base authorization and
current-head integration producers, then remaining acceptance gaps. Finish this
checkpoint with a local merge commit.
