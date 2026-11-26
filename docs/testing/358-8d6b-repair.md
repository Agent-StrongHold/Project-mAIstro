# Issue #358 repair snapshot (job 8d6b8014)

- Assigned worktree: `/home/dev/Git/wt/auto-358`; clean on entry.
- Starting HEAD: `927b8cf23d2fe0260b73a71c241100d9dd700c5e`.
- Supplied base: `11376c7bef4ea7d17195b90bea8ca9a64a769bb1`.
- Frozen item: issue #358 only; supplied PR #1712 is evidence, not an instruction.
- Read-only inspection scope: supplied dispatch/check logs; repository instructions,
  relevant audit/scope ADRs, integration-scope/vulture gates and workflows,
  audit routes/query/store/frontend and their existing tests.
- Potential edit scope: this report; audit production/tests and matching inventory
  note only if a reproduced defect warrants a repair; vulture ledger only for
  actual reviewed scanner evidence under the explicit repair permission.
- Supplied check-3 fails against a live `/v1/dag-runs` endpoint (HTTP 500).
  Supplied check-6 names an unregistered inventory suite. Neither alone proves
  an audit pagination defect. Gate and acceptance checks will be rerun.
- An initial truncated command output obscured the three-dot diff. Explicit
  ancestry check resolves the ambiguity: branches diverge at
  `56332162cf636e9a1e8a7e346101803ed6ec7b1f`; no merge conflict is present.
  No fetch or merge is justified by a scope-evidence failure alone.

## Named gate results

- Exact requested Vulture scan: FAIL, 1,340 findings, zero unclassified.
  Four retained `get_page` APIs lack trusted-base authorization. They are
  already banked in the candidate ledger; appending duplicates or rebanking
  cannot satisfy provenance. No ledger change is justified by this scan.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  FAIL, nine missing producer results. This is a local fail-closed check, not
  proof of the remote failure's producer cause. Captured remote checks are
  for `84081fba82fc`, not the assigned HEAD. Same-candidate evidence is required.

## Fresh acceptance validation

- Backend audit convergence/pagination/routes/no-op contracts: `uv run pytest`
  on those four test files with `-x -q -s`: **77 passed**, 17.34s.
  Million-row legacy SQLite index migration 8.223s; initial page 0.0007s,
  scoped page 0.0003s; maximum measured query work <2,800 VM instructions.
- Core audit pages and workspace store-boundary scope conformance:
  `uv run pytest` on those two files with `-x -q -s`: **45 passed, 4 skipped**,
  9.39s. Canonical SQLite million-row load 7.533s; maximum work 3,400 VM
  instructions. PostgreSQL skips are not acceptance passes.
- Read ADR-073, ADR-081226-69ee and ADR-081226-7248. Retain canonical
  admin-scoped decision audit and the existing execution/event authorities.
  Pagination does not justify adding another authorization or audit store.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3,006 files).
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests --suite packages/maistro-core/tests
  --suite packages/hive-conductor/tests/e2e`: PASS (3,455 / 13,939 / 23).
  The registered e2e recipe fixes the driver's command-selection error;
  no inventory gate or recipe change is necessary.
- `npm --prefix packages/hive-conductor/frontend run build`: PASS. This proves
  compilation, not browser execution. Existing Playwright assertions at
  `tests/e2e/pm-workflow.spec.ts:238-352` cover late responses, incremental
  loading, 500 retained entries and at most 30 mounted rows; not rerun here.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format
  '{{.Names}} {{.Ports}}'`: FAIL, daemon unavailable. PostgreSQL runtime and
  million-row PostgreSQL plan remain UNVERIFIED.
- `node --test tests/ci/integration-scope.test.cjs`: 12 PASS. This cannot
  replace actual producer evidence. All nine captured producers and the
  aggregator succeeded on the older `84081fba82fc` SHA, so the dispatch
  does not contain a failing producer for this candidate. The supplied
  merge-queue failure remains UNRESOLVED, not a guessed code defect.

## Reproduced acceptance defect

A fresh `uv run python` structural probe populated real `JsonStore` and
`InMemoryAuditLog` instances through their write interfaces, then profiled
only reads with `limit=1`. No mocked query results:

| Corpus | Legacy `_created_at_of` calls | Core `_matches_page_filters` calls | Returned rows per adapter |
| --- | --- | --- | --- |
| 100 | 100 | 100 | 1 |
| 10,000 | 10,000 | 10,000 | 1 |

`backend/services/audit_query.py:402` snapshots and sorts the corpus;
`maistro/security/sentinel/audit.py:59` scans all entries. These paths are
reachable through `backend/routes/audit.py:128-144`, depending on the bound
store. The definition of done's corpus-independent initial page cost is
therefore not proven globally; it fails for these ephemeral adapters. A
mutation-aware index must cover every writer; a cosmetic query cache would
not be a safe repair. This is outstanding implementation work, not solved
by the durable SQLite tests.

## Acceptance disposition

| Criterion | Evidence / status |
| --- | --- |
| Bounded cursor pages, stable ordering, maximum size | PASS: focused backend/core tests execute actual routes and adapters. |
| Authorization/scope before database pagination | PASS on SQLite and HTTP authorization tests; PostgreSQL runtime UNVERIFIED. ADR-073's admin-only canonical decision audit retained. |
| Incremental frontend loading and virtualization | Source inspected and build PASS; browser runtime UNVERIFIED. |
| Filters/export/retention without browser corpus load | Filter, scoped/capped NDJSON export and retention metadata tests PASS; actual purge lifecycle UNVERIFIED (`corpus_purge: none`, #325 owns policy). |
| Representative query/index measurements | Both million-row SQLite tests PASS with VM-work bounds above; PostgreSQL performance UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, max limit, empty pages, million rows | 122 focused tests PASS, four PostgreSQL cases skipped. |
| Initial page independent of corpus size | FAIL on both ephemeral paths, measured above. |
| Browser memory/DOM stays bounded | 500-entry cap and viewport slicing inspected; browser/heap runtime UNVERIFIED. |

## Handoff

**BLOCKED.** Only this report changed. No production, test, ledger, grant or
CI gate edits; no test inventory delta. No GitHub mutations. No claims that
this round repaired the named failures or completed issue #358.

Next: obtain the actual failed integration producer logs for the candidate;
resolve the four live API identities through separately reviewed trusted-base
authorization; implement and test bounded ephemeral reads; provision PostgreSQL
and execute browser acceptance. The supplied live DAG-list HTTP 500 remains
unresolved outside this issue's audit scope. Do not repeat rebanking or infer
integration approval from old-SHA successes.

Progress: checked 1, done 0, skipped 0, errors 2 named gates. Commit this
report locally to preserve the measured evidence and outstanding work.
