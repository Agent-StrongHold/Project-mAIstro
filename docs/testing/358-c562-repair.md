# Issue #358 repair checkpoint (c562bfd8)

## Frozen scope

Only issue #358 / existing PR #1712 on `auto-358`; starting HEAD
`939430f8424a551fdc6839ddc6cc1e2ac1b68ed7`, supplied base
`e1b13dcd15dedd637404c38dfe1900921aba2b8c`. Worktree initially clean.
Process existing audit pagination implementation, its adjacent tests, integration
scope gate and specifically requested vulture gate. No remote mutations or gate
weakening. Changes limited to evidenced repairs and this validation record;
additional tests require an inventory note.

## Initial evidence / ambiguity

Driver logs inspected: lint/format and 78 audit backend tests pass;
`check-3.log` fails in live `/v1/dag-runs` (500), not audit pagination.
`check-6.log` requests an unregistered inventory suite
`packages/hive-conductor/tests`; this is a driver recipe error, not a test failure.
Assumption: reproduce the integration-scope gate locally with supplied resolved
base/head before determining whether any production repair is warranted.
Previous claims are not reused as acceptance proof.

## Progress

- `uv sync --locked --extra dev`: PASS.
- Requested exact vulture gate: PASS, 1328 reviewed identities / 1328 findings,
  trusted base e1b13dcd15de. No ledger mismatch to amend.
- Frozen dispatch check runs at the exact starting HEAD report
  `integration-scope` success (112685461043) and `exact-debt-ledger` success
  (112685460126), contradicting the lane failure labels. Other captured checks
  (coverage, quality, test, lint/typecheck) failed; those labels alone are not
  evidence of a defect in audit pagination. No expansion into unrelated lanes.
- Read ADR-073 and ADR-081426-1f7c: canonical decision audit remains admin-only;
  pagination must not introduce a new authorization/execution authority.
- Source inspection confirms legacy memory pages still sort the corpus
  (`audit_query.py:402-403`) and retention explicitly has no purge (`:79`).
  These are acceptance limitations, not findings from the vulture scanner.
  No claim of complete acceptance will be made unless reconciled/proven.

- Fresh focused backend audit command: **78 passed** in 18.85s. Million-row
  legacy SQLite startup index migration 8.871s; initial page 0.0007s, scoped
  page 0.0004s; maximum measured page work <2800 VM instructions.
- Fresh canonical persistence/scope command: **50 passed, 4 skipped** in 9.89s.
  Canonical million-row SQLite load 7.816s; maximum page work 3400 VM
  instructions. Four PostgreSQL cases skip without `MAISTRO_TEST_PG_DSN`.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format
  '{{.ServerVersion}}'`: FAIL, cannot connect to daemon. Container validation
  unavailable despite dispatch's generic environment description.
- Browser configurations inspected: both require an already-running service;
  neither builds/serves this worktree. The production component retains 500 rows
  and virtualizes a 560px viewport; existing Playwright tests cover stale
  responses, repeated sentinel visibility, and 800-entry walks with ≤30 mounted
  rows. Fresh branch-built browser validation remains UNVERIFIED.

## Gate replay and final validation

- `uv run python scripts/ci_merge_group_scope.py --json <frozen base...head paths>`
  requires docker build, Hive E2E, PostgreSQL, wheel imports. Replayed
  `uv run python scripts/check-integration-scope.py --event-name merge_group
  --scope-json <computed scope> --result <captured required check=result> ...`:
  **PASS**. Captured successful producer IDs at the exact starting HEAD:
  docker-build 112685768566; hive-conductor-e2e 112685768554;
  hive-conductor-e2e-ui 112685768648; postgres (pg17) 112685768604;
  postgres (pg18) 112685768671; wheel-imports 112685768591.
  This evaluates actual frozen evidence, not invented results or a new CI run.
  The first extraction attempt failed with a local `TypeError` because snapshot
  check data is a list, not a `check_runs` object; corrected once and replay passed.
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**; actual workflow
  aggregator tested for latest-attempt selection, failures and fail-closed scope.
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3149 files.
- `uv run pytest tests/migrations/test_audit_cursor_indexes.py
  tests/migrations/test_revision_metadata.py
  tests/migrations/test_single_migration_head.py -x -q`: **7 passed**.
- `uv run python scripts/check-suite-inventory.py
  --suite packages/hive-conductor/backend/tests
  --suite packages/maistro-core/tests`: **PASS**, 3519 / 15160 collected tests,
  no duplicate evidence. No tests added or changed; no inventory delta needed.
- `uv run pytest
  packages/hive-conductor/tests/e2e/test_pm_workflow_api.py::TestDAGLifecycle::test_06_list_dag_runs
  -x -q`: **FAIL**, HTTP 500 at line 198. This reproduces driver check-3 against
  the external localhost:8101 service, not an in-process branch-built service.
  Its deployed revision/traceback remains UNRESOLVED; changing the assertion or
  repairing unrelated DAG execution from this symptom would not be justified.
- `git diff --check`: **PASS** before final note update; repeated before commit.

Focused audit commands executed (separately to preserve package import isolation):

```sh
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
```

## Acceptance accounting

| Criterion | Fresh evidence / gap |
| --- | --- |
| Bounded backend cursor, stable order, maximum page | 78 backend + 50 core/scope tests pass; production list route chooses the bound core authority or legacy store and caps pages at 200. Timestamp/row identity breaks ties. |
| Authorization/scope before DB pagination | Real SQLite route/convergence and adapter tests pass. Canonical decision-audit authorization is admin-only before I/O per ADR-073; explicit org and equality filters precede SQL LIMIT. Legacy actor aliases are bounded SQL seeks. |
| Incremental loading and virtualization | Production component inspected; requests 100-row cursor pages and mounts only a visible slice. Existing Playwright tests cover the component; fresh branch-built browser execution UNVERIFIED. Captured successful UI producer is not case-level proof. |
| Filters/export/retention without browser corpus loading | Backend tests prove lazy scoped/filtered NDJSON export with a 10,000-entry cap; UI uses a native download link and server filters. Retention is metadata only (`corpus_purge: none`), not an operating purge policy; #325 remains the stated policy owner. Browser download UNVERIFIED. |
| Measured representative large query/index strategy | Two real million-row SQLite tests execute production queries and measure bounded VM work (<2800 legacy; 3400 canonical). PostgreSQL execution UNVERIFIED, four tests skip. |
| Concurrent inserts, stability, isolation, maximum, empty, million-row envelope | Executed tests cover all named behaviors on SQLite/memory; skipped PostgreSQL cases are not counted as proof. |
| Corpus-independent initial page cost | Durable SQLite and canonical indexed memory have bounded-work tests. Unconditional criterion NOT MET by reachable unbound legacy memory path: `_sorted_ascending` copies/sorts every entry per page. Startup migration cost is separately reported, not counted as a bounded page. |
| Bounded browser memory/DOM rows | Source caps retained entries at 500 and virtualizes rows; existing browser test walks 800 entries and asserts ≤30 mounted rows. Fresh browser execution UNVERIFIED. |

## Disposition / handoff

**BLOCKED**. Only `docs/testing/358-c562-repair.md` changed. No production,
ledger, gate, grant, test or authority changes: neither named gate reproduces an
actual defect, so changing a matching ledger or weakening a gate is unjustified.
Canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` remains unchanged.

To continue: supply the failed integration-scope candidate/producer logs (the
frozen exact-head evidence succeeds), and an isolated branch-built service/browser
harness plus PostgreSQL DSN or working Docker endpoint. The external DAG 500
requires deployed revision and traceback before assigning a repair. Separately,
resolve legacy-memory bounded-cost and retention-policy acceptance gaps without
introducing a second audit or retention authority. No remote re-enumeration,
GitHub mutations, destructive git operations, or service changes performed.

Snapshot outcome: checked 1, done 0, skipped 0, errors 1 (live E2E failure).
Local commit is an evidence checkpoint, not implementation completion or
integration approval.
