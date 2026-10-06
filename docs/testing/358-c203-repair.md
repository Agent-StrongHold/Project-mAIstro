# Issue 358 repair checkpoint

## Frozen scope

Only issue #358, starting HEAD `222b5e0415dcbc40845a48b98833797a69923ec0`,
assigned develop base `56332162cf636e9a1e8a7e346101803ed6ec7b1f`.
Process the existing merge, the named integration-scope and vulture gates, and
focused audit-pagination acceptance validation. No remote mutations.

Initial state: unfinished merge with MERGE_HEAD exactly the assigned base.
Preserved unstaged and staged diffs in `../incoming-358.patch` and
`../incoming-358-index.patch`. Two unresolved files:
`tests/migrations/test_capability_invocation_effect_index_migration.py` and
`tests/migrations/test_task_admission_generation_upgrade.py`.
Assumption: finish the existing exact-base merge rather than fetch moving develop.
Other staged files are inherited merge content, not a new implementation scope.
Potential repair files are those two conflicts, reviewed retained audit identities
in `quality/vulture-baseline.json` (explicit lane exception), audit pagination
production/tests if executed evidence demands it, and this validation note.

Prior result reports unapproved retained vulture identities, missing integration
producer results, memory fallback full-corpus visits, external E2E mismatch, and
unverified frontend/PostgreSQL behavior. These are claims to revalidate.

## Initial executed evidence

Driver check-1/check-2 fail on the two conflict markers; check-3 targets an
external API returning the obsolete array contract (200 where canonical admin
protection requires 403). check-4 passes 77 focused tests; check-6 names an
unregistered inventory parent rather than `packages/hive-conductor/tests/e2e`.
All eight supplied logs inspected. Docker probe cannot connect to
`unix:///var/run/docker.sock` in this job.

Fresh exact Vulture command fails: its default trusted base is stale
`c560d4ccad82`, not the assigned develop base. Four retained get_page identities
are reported new and six inherited identities removed. Candidate ledger versus
assigned base differs only by the four get_page rows; no merged ledger rows lost.
Fresh integration-scope invocation fails closed with nine missing producer
results; no synthetic success evidence will be supplied.

Merge inspection proves a duplicate revision 057: develop's Run-store planner
migration and this lane's unlanded audit indexes. Necessary merge-resolution
scope therefore also includes renaming/reparenting the audit revision to 058
and updating its existing chain/rollback test. Preserve develop revision 057.
Keep the admission rollback assertion against the captured original stamp,
rather than weakening it to a hardcoded previous head. No execution authority or
authorization changes; ADR-073 keeps canonical decision audits admin-only.

## Merge repair checkpoint

Renamed `057_audit_cursor_indexes.py` to `058_audit_cursor_indexes.py` and
reparented it onto develop's unchanged 057. `uv run alembic heads` changed from
a duplicate-057 warning/two heads to exactly `058 (head)`.
Added `tests/migrations/test_audit_cursor_indexes.py` (two parametrized cases)
to independently pin upgrade and downgrade DDL; inventory delta recorded in
`inventory-notes/358-c203-migration.md`. Existing chain test pins both 057/058
filenames and parent edges. Live rollback test now preserves the Run-store index.

Executed `uv run pytest` over the audit DDL, effect-index, status-domain,
chain, and admission-upgrade migration files: **12 passed, 28 PostgreSQL skips**.
`uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3,006 files).
`git diff --check`: PASS.
Explicit RATCHET_BASE_REV still resolves the old merge base until the existing
merge is committed; gate will be rerun after recording the merge.

## Final validation and disposition

Merge repair committed as `0df6da31789d`. New regression test was also run in
an isolated temporary directory against the starting commit's migration body:
it fails `assert '057' == '058'`, as expected. No candidate files were reverted
or temporarily replaced. The passing candidate checks above are not vacuous.

Fresh validation (all long-running commands allowed 1,200 seconds):

- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **77 passed**. Legacy SQLite million-row index build 11.159s, initial page
  0.0008s, scoped page 0.0005s, maximum query work <2,800 VM instructions.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s`:
  **45 passed, 4 PostgreSQL skips**. Canonical SQLite million-row load 10.143s,
  maximum query work 3,400 VM instructions.
- `uv run python scripts/check-suite-inventory.py --suite tests/ --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests --suite packages/hive-conductor/tests/e2e`:
  **PASS** (4,733 / 3,455 / 13,939 / 23 tests respectively; no duplicate evidence).
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**. These unit
  tests validate the aggregator, not the missing specialized producer results.
- `npm --prefix packages/hive-conductor/frontend run build`: **PASS** (both
  TypeScript projects and Vite). No browser runtime acceptance claim.
- Exact `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` after merge:
  **FAIL** against the correct base `56332162cf63`: 1,336 trusted identities,
  1,340 current findings. Four get_page identities lack trusted-base approval.
  They already appear exactly once in the candidate ledger at lines
  997/1006/1068/1170. The production caller is
  `backend/services/audit_bridge.py:186`, outside this scan's packages/*/src
  roots. Retaining them is necessary; removing the methods breaks the route.
  The merge preserves all incoming ledger rows. No additional evidence-backed
  ledger amendment exists; duplicate rows would be wrong and candidate edits
  cannot authorize themselves. No grants/whitelist/gates changed.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  **FAIL** with nine missing producer results (docker-build, durable-events,
  hive-conductor-e2e, hive-conductor-e2e-ui, object storage (MinIO), postgres
  (pg17), postgres (pg18), strike-ladder, wheel-imports). No producer success
  invented and no remote CI/GitHub mutation attempted.
- Instrumented production `services.audit_query.page_entries(limit=1)` with a
  counting mapping: 100 entries -> 100 visited; 10,000 -> 10,000 visited.
  `_sorted_ascending` at line 402 still snapshots the full reachable memory
  corpus. This is an actual remaining acceptance failure, not a scanner guess.

### Acceptance matrix

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Bounded backend cursor, stable ordering, maximum page | 77 backend + 45 core tests pass. Includes same-timestamp ties, concurrent inserts, maximum/floor limits and malformed/empty pages. |
| Authorization/scope before DB pagination | SQLite query and route tests pass; canonical decision reads retain ADR-073 admin gate before I/O. PostgreSQL runtime UNVERIFIED (4 skipped cases). |
| Incremental frontend and virtualization | Routed AuditLog source uses 100-row pages and viewport slicing; TypeScript/Vite build passes. Browser runtime UNVERIFIED. |
| Filters/export/retention without whole corpus in browser | Filtered, scoped, lazy export tests pass; frontend uses a direct download, not a blob accumulator. Retention honestly reports `corpus_purge: none`; purge lifecycle remains UNVERIFIED, owned by #325. |
| Representative large-dataset query/index measurements | Both million-row SQLite tests executed with deterministic VM work bounds above. PostgreSQL million-row and live migration execution UNVERIFIED (Docker unavailable). |
| Concurrent inserts/cursor stability/scope/max/empty/million-row tests | Focused suites execute all named cases for SQLite/memory; PostgreSQL cases explicitly skipped. |
| Initial page cost independent of corpus size | Durable SQLite query work bounded. NOT MET for reachable memory fallback: counting probe visits every entry. |
| Bounded browser memory/DOM | Source caps retained entries at 500 and virtualizes visible rows; browser runtime/heap bounds UNVERIFIED. |

### Changed files and handoff

Manual repair paths:
- `alembic/versions/057_audit_cursor_indexes.py` renamed/reparented to
  `alembic/versions/058_audit_cursor_indexes.py`.
- `tests/migrations/test_capability_invocation_effect_index_migration.py`.
- `tests/migrations/test_task_admission_generation_upgrade.py` (conflict resolved,
  original-head rollback invariant preserved).
- `tests/migrations/test_migration_chain.py`.
- `tests/migrations/test_audit_cursor_indexes.py` (new).
- `docs/testing/inventory-notes/358-c203-migration.md` (new, +2).
- This report.

Other changes in the merge commit are the preserved incoming exact develop
snapshot, not unrelated manual repairs. No competing store, scheduler, event or
authorization authority introduced; accepted ADR-081226-69ee preserved.

**BLOCKED, partial repair completed.** The merge/syntax/revision collision is
fixed and committed, but this is not integration approval. Next owner needs
trusted-base authorization for the four retained public API findings, actual
same-candidate specialized CI producer evidence, PostgreSQL/browser validation,
and a mutation-aware bounded memory-query design. Do not substitute a length
cache (same-size replacement makes it stale) or weaken security/E2E expectations.
Logs for this execution are `/tmp/358-c203-*.log`; initial salvage patches are
beside the worktree. Final report is committed locally; no push or GitHub actions.

Progress: checked 1, done 0 (issue acceptance incomplete), skipped 0, errors 2
(named gate blockers); next: the explicit prerequisites and remaining acceptance
failure above. No additional items started.
