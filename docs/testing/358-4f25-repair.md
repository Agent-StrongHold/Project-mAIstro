# Issue 358 repair — job 4f25d9

## Frozen scope

Only issue #358, branch `auto-358`, starting HEAD `af93726fbb79e8d8fb1875f384607883e0b71c2d`, supplied develop base `c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250`.
Preserve the existing merge (MERGE_HEAD resolves to that exact develop base). Initial staged and unstaged changes backed up outside the worktree to `../incoming-358-index.patch`, `../incoming-358.patch`, and index conflict identities to `../incoming-358-unmerged.txt`.

Repair file scope: the two existing conflicted migration tests, audit cursor migration if revision collision is confirmed, adjacent migration assertions and inventory note, and `quality/vulture-baseline.json` only for evidence-backed exact-debt repair explicitly authorized in dispatch. Review-only scope: existing issue 358 audit production paths/tests, repository instructions/ADRs, job dispatch and check logs, gate scripts/workflows. Incoming unrelated develop changes are preserved, not independently modified.

Ambiguity: dispatch requests a develop sync if conflicted, but a merge of the exact supplied develop base is already in progress. Proceed with that frozen resolved merge target rather than fetch a moving target.

## Progress

- Initial state recorded; merge conflicts are in `tests/migrations/test_capability_invocation_effect_index_migration.py` and `tests/migrations/test_task_admission_generation_upgrade.py`.
- Read supplied check logs: checks 1/2 fail on conflict markers, check 3 targets an external server and receives 200 instead of admin-only 403, check 6 names an unregistered inventory suite; checks 4/5/7 passed in the driver (not yet independently verified).
- Confirmed semantic merge conflict: both audit-index and incoming user-model migrations declare revision `056` with the quota-door parent. Preserve incoming develop revision 056 and re-parent only the unlanded audit migration as 057; update adjacent chain tests.
- Prior handoff reports a trusted-base Vulture authorization gap and an unbounded memory fallback. These remain hypotheses until fresh validation; do not rebank duplicate identities or weaken gates.
- Resolved conflict markers, moved only audit indexes to revision 057 after incoming 056, strengthened the chain identity/edge assertions, and adjusted the audit-index round trip to preserve incoming user-model tables. Added zero-count inventory note. Regression demonstrated before repair: duplicate revision 056 warning and missing 057 failure (`repair-migration-before.log`).
- Fresh ruff check and format check PASS (2,987 files). Migration tests: 2 passed, 28 skipped (database unavailable); Docker daemon socket unavailable. Live migration validation is UNVERIFIED, not a pass.
- Fresh exact Vulture command FAILS on four live `get_page` identities requiring trusted-base authorization, not missing candidate banking. Production `audit_bridge.py:186` calls this protocol. No safe duplicate ledger amendment is justified.
- Read accepted ADR-068, ADR-073, ADR-081226-69ee and production list/export/query/bridge/frontend paths. Preserve admin-only canonical audit authority and Goal -> Graph -> Run -> NodeRun -> Attempt; no new authorization or execution authority. Retention endpoint explicitly reports no purge (#325), not lifecycle implementation.
- Focused backend suites: 77 passed. Core audit/store-scope suites: 45 passed, 4 PostgreSQL cases skipped. Frontend production build PASS. Legacy million-row index build 8.250s, first page 0.0007s, scoped page 0.0004s, query VM work <2,800; canonical SQLite load 7.844s, maximum VM work 3,400.
- Inventory gate PASS for registered suites: tests/ 4,703; backend 3,396; core 13,780; Hive E2E 23. No collection-count change from this repair.
- Integration-scope checker tests: 12 passed. Actual checker with `--event-name pull_request` and no fabricated producer results FAILS closed on nine missing results. Captured PR checks are not proof for this repaired HEAD. No gate change is warranted.
- Browser runtime remains UNVERIFIED; production build is not browser proof. An attempted read of `packages/hive-conductor/playwright.config.ts` found no such file; no command was run against that unresolved config path.
- Fresh counted-mapping production probe confirms unbounded memory work: `page_entries(limit=1)` visits all 100/100 and 10,000/10,000 entries (`repair-memory-probe.log`), through `_sorted_ascending` at `audit_query.py:386`. This is a real unmet initial-page criterion, not a scanner artifact. Frozen gate/migration repair scope does not include redesigning the memory store.
- `uv run alembic heads` reports exactly `057 (head)`. `git diff --check` passes. Candidate Vulture ledger has precisely the four retained `get_page` identities (4 additions, 0 deletions versus supplied develop), so it already matches the requested reviewed banking; no ledger edit can satisfy the missing trusted-base grant. Incoming unrelated develop files, including its quality files, remain preserved without independent edits.

## Commands and executed acceptance evidence

Logs are in the supplied job directory, prefixed `repair-`.

- `uv run ruff check .` — PASS (`repair-ruff.log`).
- `uv run ruff format --check .` — PASS (`repair-format.log`).
- `uv run pytest tests/migrations/test_capability_invocation_effect_index_migration.py tests/migrations/test_migration_chain.py tests/migrations/test_task_admission_generation_upgrade.py -x -q` — 2 passed, 28 skipped (`repair-migration.log`).
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s` — 77 passed (`repair-backend.log`).
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s` — 45 passed, 4 skipped (`repair-core.log`).
- `npm --prefix packages/hive-conductor/frontend run build` — PASS (`repair-build.log`).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — FAIL, four retained APIs need trusted-base authorization (`repair-vulture.log`).
- `uv run python scripts/check-integration-scope.py --event-name pull_request` — FAIL, nine required producer results missing (`repair-integration.log`); deliberately no invented `--result ...=success` arguments.
- `node --test tests/ci/integration-scope.test.cjs` — 12 passed (`repair-integration-tests.log`).
- `uv run python scripts/check-suite-inventory.py --suite tests/ --suite packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e --suite packages/maistro-core/tests` — PASS (`repair-inventory.log`).
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format '{{.Names}} {{.Ports}}'` — FAIL, daemon unavailable; PostgreSQL not started.
- `uv run alembic heads` — PASS, one head 057.
- `git diff --check` — PASS.

| Acceptance criterion | Evidence / remaining gap |
| --- | --- |
| Backend bounded cursor pagination, stable ordering, maximum page size | Executed real SQLite and memory adapter tests: clamps, ties, malformed cursors, last/empty pages; route suites pass. PostgreSQL runtime UNVERIFIED. |
| Authorization/scope filters before database pagination | Real canonical SQLite and legacy SQL tests pass; real bound Container test `test_core_decision_audit_is_admin_scoped` returns 403. `page_query` scopes before LIMIT. Driver external E2E still returns 200 instead of expected 403; deployed source provenance UNVERIFIED, assertion not weakened. |
| Frontend incremental loading and virtualization | Inspected production cursor/observer/window code and adjacent routed Playwright scenarios; production build passes. Browser runtime UNVERIFIED. |
| Filters/export/retention without browser corpus loading | Executed filter/scoped/capped NDJSON export and retention-metadata tests pass; frontend uses direct download, not blob accumulation. Retention endpoint reports `corpus_purge=none`; lifecycle retention remains UNVERIFIED (#325), not implemented by this repair. |
| Representative large-dataset query/index measurements | Two executed million-row SQLite envelopes pass with deterministic VM-work limits and measurements above. PostgreSQL million-row envelope skipped, UNVERIFIED. |
| Concurrent inserts, stable cursors, scope isolation, maximum limit, empty pages, million-row tests | 122 focused cases passed, including real threaded durable writes, timestamp ties and scoped seeks; four PostgreSQL cases skipped. |
| Initial page cost independent of corpus size | NOT MET on reachable unbound memory path: fresh counted probe reads every entry for limit=1. Durable SQLite path is bounded after startup indexing. |
| Browser memory/DOM row count bounded | Source retains at most 500 entries, renders viewport slice; Playwright source asserts <=30 mounted rows across eight pages. Build passed, actual browser behavior UNVERIFIED this round. |

## Handoff

**BLOCKED, partial repair committed locally.** Merge conflict/revision collision is repaired and regression-tested, but integration approval is not established. No remote mutations, grant changes, gate weakening, or destructive Git operations performed.

Focused changes: rename/re-parent `056_audit_cursor_indexes.py` to `057_audit_cursor_indexes.py`; resolve two conflicted migration tests; strengthen chain identity and user-model-preservation assertions in adjacent tests; zero-count inventory note and this report. Existing incoming develop changes are included only to finish the already-started merge of the frozen supplied base.

Next: obtain authorized trusted-base Vulture grant through the owning workflow; establish candidate-specific integration producer results on an available stack; repair the memory-path initial-page cost in a separately bounded implementation round. Do not repeat duplicate rebanking or accept an external admin-audit 200 as correct.

Progress: checked 1 issue; done 1 bounded merge repair (issue acceptance incomplete); skipped 0 issues; errors 2 unresolved named gates. PostgreSQL migration/browser runtime acceptance remains explicitly UNVERIFIED.
