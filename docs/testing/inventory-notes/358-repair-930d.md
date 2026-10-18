---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/maistro-core/tests: 0
  packages/hive-conductor/tests/e2e: 0
  tests/: 0
---

# Issue 358 interrupted-merge repair (930d)

Frozen item: #358 only, initial HEAD `e28cead5071353646dcc5558d95211627cc64a0e`,
assigned develop base `83db0175dd9465727691d9429c36c4b4c597f2a7`.
Incoming unstaged/conflicted and staged work preserved in job-directory patches.
`git fetch origin` resolved origin/develop to the same in-progress MERGE_HEAD;
complete that merge rather than starting a second merge or discarding work.

## Conflict reconciliation

- `backend/routes/audit.py`: retain bounded canonical core list/export and
  pre-query admin authorization. ADR-073 overrides legacy personal-scope access
  to canonical decision audit. Keep canonical Principal (ADR-068); introduce no
  scheduler, Goal store, execution/event authority, or authorization alternative.
- `backend/services/agent_materialization.py`: retain incoming develop's scan of
  every forwarded message, including trailing assistant/tool/system messages,
  with bounded canonical context and pre-serialization budgets (ADR-073).
- Keep inventory front matter in both conflicted historical inventory notes.
- Preserve all other incoming develop changes. In particular, integration-scope
  now selects the largest check-run ID rather than trusting API response order.
  Its eight shipped-script regression tests are supplied by develop; this repair
  adds no test nodes, grants, or quality-ledger entries.

## Independently executed initial validation

Logs: `/home/dev/maistro/jobs/930d49bfca1a47cd946714b290eee220/repair-*.log`.

- `uv sync --locked --extra dev`: PASS.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2772 files.
- `uv run node --test tests/ci/integration-scope.test.cjs`: 8 PASS. Actual shipped
  workflow exercised with fake GitHub API results; this is not remote producer
  success evidence.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_chat_scan_forwarded_history.py -x -q -s`:
  84 PASS. Legacy million-row first page 0.0007s, scoped page 0.0004s, all measured
  query shapes <2800 VM instructions; index migration 9.379s.
- Named vulture command: FAIL before merge commit, 1363 findings vs 1359 trusted
  identities. Four `get_page` declarations are already banked exactly and retained:
  protocol plus PostgreSQL, SQLite, memory adapters. Production consumer is
  `services.audit_bridge.page_core_audit_entries`, outside `packages/*/src` scan.
  Candidate ledger banking does not authorize new debt; no duplicate rows or
  guessed findings added. Recheck against completed merge before final report.

Driver logs also show invalid inventory recipe `packages/hive-conductor/tests`
and a live-service test returning 200 instead of admin-only 403. The latter ran
against an external service, not proof of this checkout's behavior. In-process
booted-container tests above enforce 403 before any canonical store query.

## Merge and validation checkpoint

Interrupted merge committed as `9d40ce989`. The requested subsequent
`git merge origin/develop` created `b44c2242a35c`: the shared remote-tracking ref
had moved from the initially resolved SHA to `d7f7f6f81a83` while validation ran.
That merge brought only 35 pre-existing authorization lines for #1572; no grants
were manually edited, none authorize #358, and no further refs will be followed.
Both incoming merges are preserved; no history or work discarded.

- Canonical audit pages: **8 passed, 4 skipped**. Real canonical SQLite million
  rows loaded in 7.997s; all 16 query/filter shapes <=3400 VM instructions.
  PostgreSQL cases skipped because no configured scratch database.
- Core persistence + Sentinel: **597 passed, 178 skipped** (13.26s).
- Suite inventory: **PASS**, core 12091 / Hive backend 3301 / Hive E2E 23.
  Used actual E2E recipe rather than driver's invalid parent-directory recipe.
- Integration-scope CLI: **FAIL**, nine specialized producer conclusions absent.
  The eight workflow tests prove the incoming retry-selection repair, not the
  absent Docker/PG/storage/durable-events/strike-ladder/wheel/E2E producer results.
- Post-merge vulture: **FAIL**, still exactly four reviewed/banked `get_page`
  identities without trusted-base authorization. Do not alter the scan, invent
  a caller, remove live public APIs, or duplicate ledger rows to evade that gate.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps`: **FAIL**, cannot connect.
  Live migrated PostgreSQL and isolated full-stack browser validation unavailable.
- Existing browser `pm-workflow.spec.ts` expected PM audit access (200),
  inconsistent with executed canonical admin-only route tests (403). Repaired
  that existing test to assert PM list/export refusal, then admin one-row cursor
  traversal using the same setup credentials and contract as the Python E2E
  test. No new test node. This follows actual booted-container 403/200 evidence,
  not a weakened assertion. Browser execution still UNVERIFIED; no foreign :8101
  service was treated as evidence for this checkout.

Retention/purge is explicitly delegated to #325; do not invent a purge policy
to claim #358 complete. `audit_query.py` reports `corpus_purge: none`; canonical
memory adapter `get_page` still scans linearly. These remain acceptance gaps.

## Final focused validation

- `uv run pytest packages/hive-conductor/backend/tests -x -q`: **3296 passed,
  5 skipped**, 142.56s. 104 warnings (including existing aiosqlite thread teardown
  and model serializer warnings); no test failure.
- `uv run pytest tests/test_check_integration_scope.py -x -q`: **18 passed**.
- `uv run python scripts/check-principal-identity.py`: **PASS**, 4 existing
  violations and no new ones.
- `uv run python scripts/check-radon-baseline.py`: **PASS**, 66/66 blocks,
  none new/regressed/stale. Prior artifact's radon failure is not reproduced.
- `npm --prefix packages/hive-conductor/frontend run build`: **PASS**, TypeScript
  and Vite production bundle. This is not browser runtime evidence.
- `uv run alembic heads`: **PASS**, single head 051.
- Offline `DATABASE_URL=postgresql://offline:offline@127.0.0.1/offline uv run
  alembic upgrade 050:051 --sql`: **PASS**, renders eight indexes; not applied
  to a live PostgreSQL database.

Browser collection attempts initially failed because the E2E directory has no
installed `@playwright/test`; pointing NODE_PATH at existing frontend dependencies
resolved that, then unrelated accessibility specs lacked `@axe-core/playwright`.
These are dependency/collection failures, not executed browser assertions. Scope
the final collection check to the changed `pm-workflow.spec.ts` file; do not
install or modify unrelated suites. Final focused collection **PASS**: five
audit browser cases collected with NODE_PATH pointing at frontend dependencies.
This proves syntax/discovery only. Final Ruff lint/format, three-suite inventory,
and `git diff --check` also **PASS**.

## Acceptance disposition

1. Bounded cursor pages / stable order / max: executed canonical SQLite/memory
   adapter tests and booted-container HTTP tests; 200-row maximum, stable row IDs,
   no unbounded get_entries call. Real PostgreSQL UNVERIFIED.
2. Authorization/filtering before pages: executed exact-org, combined-filter,
   actor-isolation and pre-query admin refusal tests. Real PG UNVERIFIED.
3. Incremental frontend + virtualization: production component inspected and
   TypeScript/build passed; browser runtime UNVERIFIED.
4. Filters/export: canonical filtered streaming and capped NDJSON tests PASS;
   retention metadata PASS but purge remains absent, so criterion incomplete.
5. Query/index measurement: both canonical and legacy SQLite million-row suites
   PASS (<=3400 and <2800 VM instructions). PG measurement UNVERIFIED.
6. Inserts/cursor/scope/max/empty/million: executed SQLite/memory cases PASS;
   all four real-PG cases skipped, not counted as evidence.
7. Bounded initial cost: demonstrated for SQLite; memory read remains O(n).
8. Browser memory/DOM: source caps retained rows at 500 and uses windowing;
   browser runtime and byte-level heap measurement UNVERIFIED.

Writer handoff verdict: **NEEDS-REPAIR**, not integration approval. Remaining
external actions: authorize the four retained APIs through the trusted-base
process and supply real specialized CI producer conclusions. Remaining product
work/validation: retention-policy dependency, linear memory adapter, live PG and
browser bounds. No GitHub mutations or closure actions.

Changed directly in this round: four merge-conflict resolutions (audit route,
agent materialization, two historical inventory front matters), existing browser
audit contract test, and this inventory/validation note. All incoming develop
changes preserved in merge commits; vulture ledger already contains exactly the
four required identities and needed no duplicate amendment.

Progress: checked=1, done=0 acceptance-complete, skipped=0, errors=2 outstanding
gates (vulture authorization and integration producer evidence). Next: external
gate prerequisites and the explicitly unverified/incomplete acceptance items.
