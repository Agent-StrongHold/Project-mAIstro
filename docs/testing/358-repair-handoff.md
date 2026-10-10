# Issue #358 repair checkpoint

## Frozen scope

One item: issue #358 / PR #1712, branch auto-358, starting HEAD
bd4c2763a870e5fffd15bb089860531f9008afdb. Supplied base:
9bd1a93eefc4e564041b3cc512f20b229cde64b9.

On entry an unfinished merge of b0912ce590d51bcfe4944da57770575e50ae2e8a
was already staged. Preserve all incoming work. Backups outside this worktree:
`../incoming-358.patch`, `../incoming-358-staged.patch`,
`../incoming-358-status.txt`.

Repair file snapshot: the three existing conflict files
`packages/maistro-core/src/_vulture_whitelist.py`,
`tests/migrations/test_capability_invocation_effect_index_migration.py`,
`tests/migrations/test_task_admission_generation_upgrade.py`;
`quality/vulture-baseline.json` only for the explicitly authorized CI repair;
this checkpoint. Inspect existing audit implementation/tests and supplied logs
for acceptance; do not expand feature scope.

Assumption: the pending merge is the driver's develop synchronization and is
the integration-scope failure to repair. Resolve it in place rather than start
another merge or discard any work. No network/GitHub mutations.

Status: salvage complete. Supplied check-1/2 fail on conflict syntax; check-3
fails at the unrelated live `/v1/dag-runs` route (500); check-6 uses an
unregistered inventory suite. Checks 4/5/7 passed in the supplied logs, but
fresh validation remains required.

The merge also introduces a concrete duplicate revision `059` (audit indexes
and incoming backlog). Integration repair therefore includes renaming only
this lane's unlanded audit revision to `061` on incoming `060`, and updating
`tests/migrations/test_audit_cursor_indexes.py` and the existing audit round-trip
in `tests/migrations/test_migration_chain.py`. Preserve incoming 059/060.
These files and a zero-delta inventory note complete the repair snapshot.
No unrelated feature work or gate changes are planned.

## Repair and validation checkpoint

Resolved all three conflicts, retaining both whitelist blocks and migration
ancestor assertions. Renamed audit migration to 061 on 060; incoming migrations
are unchanged. Strengthened the existing live rollback test to preserve all
five backlog tables. Zero inventory delta documented in
`inventory-notes/358-ccf3-merge.md`.

The updated chain regression failed before the migration change (duplicate 059,
missing 061); afterwards `uv run alembic heads` returns only `061 (head)`.
`uv sync --locked --extra dev`, `uv run ruff check .`, and
`uv run ruff format --check .` pass (3126 files).
Focused migration tests: 4 passed, 32 skipped because PostgreSQL is not configured.
`DOCKER_HOST=unix:///var/run/docker.sock docker ps` cannot connect to the daemon.
No shared DB or existing external deployment was modified.
The exact requested Vulture scan passes: 1329 findings, 1332 reviewed identities,
zero unclassified. No additional ledger edits are justified; incoming ledger
changes are preserved. `git diff --numstat MERGE_HEAD -- quality/` is empty.

Read ADR-068/073: retain Sentinel decision audit's admin-only scope before I/O;
legacy personal audit reads are not permission to expose canonical decisions.
No scheduler, Goal store, event authority, or authorization path is changed.
The guessed ADR-068 filename was not found and skipped; the actual resolved
`ADR-068-unified-authorization-and-elevation.md` was then read.
Other broad filename globs yielded no audit/principal ADR; no file was edited
based on those misses.

Fresh focused validation: Hive audit/convergence/routes/noop tests **78 passed**;
core audit pages and scope conformance **50 passed, 4 PostgreSQL cases skipped**.
Legacy durable million-row index build: 8.901s; first page 0.0006s; scoped page
0.0004s; maximum VM work <2800 instructions. Canonical SQLite million-row load:
7.856s; maximum query VM work 3400 instructions. These exercise production
queries, not an alternate implementation.

Frontend `npm run build` passes TypeScript and Vite. Browser runtime remains
UNVERIFIED (no fresh isolated live stack; Docker unavailable). No claims from
prior browser runs are reused as executed evidence.

The named integration-scope gate was executed with `--event-name pull_request`:
fails closed on nine missing producer results (docker-build, durable-events,
hive-conductor-e2e, hive-conductor-e2e-ui, MinIO, pg17, pg18, strike-ladder,
wheel-imports). The 12 aggregator unit tests pass; they do not stand in for
current-head CI producer evidence. No success results were fabricated.

Inventory initially failed because this round's zero-delta note used
`tests/migrations`, which has no recipe. Corrected the note to the actual
`tests/` suite; no gate or baseline was changed. Corrected validation passes:
core 14792, root tests 4793, Hive backend 3466, Hive e2e 23; 23074 unique
collected identities, no duplicate evidence.
Raw fresh logs are in the supplied job directory as `repair-*.log`.

## Integration evidence reconciliation

The lane brief reports an earlier merge-queue integration-scope failure. The
frozen dispatch snapshot instead contains successful latest specialized checks
and integration-scope for **starting** HEAD bd4c2763a870. Parsed the captured
check objects, verified each head SHA, selected the greatest check ID per name,
and passed their actual conclusions as `--result` inputs to the unchanged gate:
**passes** (`repair-integration-captured-head.log`). This is historical input
validation, not fresh producer execution or approval of the repaired commit.
No producer failure log for that earlier merge candidate was supplied; no
speculative gate repair is justified. Current repaired-head CI evidence remains
UNVERIFIED. Other captured check failures are not newly assigned repair scope.

## Acceptance disposition

| Criterion | Fresh evidence / residual gap |
| --- | --- |
| Bounded stable cursor pagination, maximum page size | Hive/core tests pass for SQLite and memory, including duplicate timestamps/request IDs and limit clamp. PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before database pagination | Executed real-Container convergence, pre-I/O admin refusal, org/actor isolation and filtered-query tests pass. ADR-073 admin restriction retained. |
| Incremental loading and virtualization | TypeScript/Vite build passes; source retains 500 rows and mounts an overscanned slice. Browser runtime UNVERIFIED this round. |
| Filters/export/retention without browser corpus loading | Executed filtered/capped/lazy export and retention-metadata tests pass. UI uses a download link. Actual retention/purge remains UNVERIFIED: production `retention()` reports `corpus_purge: none`; policy work is related issue #325, not permission to claim completion here. |
| Representative large-dataset query/index measurements | Both million-row SQLite work-bound tests pass with measurements above; PostgreSQL million-row envelope UNVERIFIED. |
| Concurrent inserts, cursor stability, scope, max, empty, million-row tests | 128 focused tests pass; 4 PostgreSQL cases skipped. Threaded memory writes and acknowledged durable concurrent writes covered. |
| Initial cost independent of corpus | Canonical memory read-budget and durable SQLite VM-budget tests pass. Legacy unbound fallback NOT MET: a fresh counted-mapping probe called production `page_entries(limit=1)` and visited 100/100 then 10000/10000 rows at `audit_query.py:402`. The route still selects this path without a core binding or persistence. |
| Bounded browser memory/DOM | Source inspection only plus frontend build; fresh browser execution/heap evidence UNVERIFIED. |

## Changed files and executed commands

Lane changes (all incoming staged merge work is additionally preserved):
- Rename `alembic/versions/059_audit_cursor_indexes.py` to `061_audit_cursor_indexes.py`
  and revise only its parent/id metadata.
- Resolve `packages/maistro-core/src/_vulture_whitelist.py`,
  `tests/migrations/test_capability_invocation_effect_index_migration.py`, and
  `tests/migrations/test_task_admission_generation_upgrade.py`.
- Update `tests/migrations/test_audit_cursor_indexes.py` and strengthen
  `tests/migrations/test_migration_chain.py`'s audit-only rollback assertions.
- This report and `docs/testing/inventory-notes/358-ccf3-merge.md`.

Validation commands (all Python run with uv):
- `uv sync --locked --extra dev`: pass.
- `uv run ruff check .`; `uv run ruff format --check .`: pass.
- `uv run pytest tests/migrations/test_audit_cursor_indexes.py
  tests/migrations/test_capability_invocation_effect_index_migration.py
  tests/migrations/test_migration_chain.py
  tests/migrations/test_task_admission_generation_upgrade.py -x -q`:
  4 pass, 32 PostgreSQL skips. Pre-renumber chain test failed as expected.
- `uv run alembic heads`: one head, 061 (before: duplicate-059 warning).
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  78 pass.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py
  -x -q -s`: 50 pass, 4 PostgreSQL skips.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: pass, no new amendment needed.
- `uv run python scripts/check-suite-inventory.py --suite tests/
  --suite packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e
  --suite packages/maistro-core/tests`: pass after note correction described above.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  missing-evidence failure; replay with actual captured starting-head results passes.
- `node --test tests/ci/integration-scope.test.cjs`: 12 pass.
- `npm run build` in `packages/hive-conductor/frontend`: pass.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps`: daemon unavailable.
- `git diff --check` / staged check: pass. Quality files match incoming MERGE_HEAD
  exactly, preserving multisets; differences from supplied origin/develop are
  incoming reachability/vulture changes, not amendments in this round.

## Handoff

**NEEDS-REPAIR**, not integration approval: the assigned merge/duplicate-revision
repair is finished and ready for local commit, but the issue's complete acceptance
cannot be claimed. Remaining work: legacy fallback corpus-independent reads,
retention disposition, live PostgreSQL/browser acceptance and current-head CI
producer evidence. Do not alter unrelated DAG routes to conceal the driver's
external `/v1/dag-runs` 500, fabricate CI conclusions, or relax gates.

Progress: checked 1, done 1 focused merge repair, skipped 0 assigned issues;
complete issue acceptance remains unresolved. Preserve the salvage patches
outside the worktree. No pushes, GitHub mutations, destructive git operations,
background commands, or new execution/authorization authorities.
