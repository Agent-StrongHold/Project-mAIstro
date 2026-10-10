---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/maistro-core/tests: +0
---

# Issue 358 — repair b2ae

## Frozen scope / preservation

Process only issue #358 in `/home/dev/Git/wt/auto-358`, starting HEAD
`cf26060d107d377d35899cbd4ac1a69455bee050`, supplied develop base / existing
MERGE_HEAD `045cfdfbe3eaa0c84493eb02754d7410b0c69378` (resolved locally).
Incoming merge has one conflict, `backend/routes/audit.py`. Both unstaged and
staged diffs preserved outside worktree in `../incoming-358-b2ae-{working,index}.patch`.
All staged incoming develop changes must be preserved, not rewritten.

Frozen repair files: audit route, its settings/schedules consumers if required
by the merge, adjacent audit/noop-contract tests, this note, and reviewed vulture
ledger identities if the exact gate requires them. Inspect existing audit query,
bridge, persistence, frontend and tests for acceptance only; do not expand to
unrelated issues. Named gates: integration-scope and exact vulture, ruff, focused
audit tests, relevant inventory and browser/DB checks where runnable.

Driver logs 0–7 inspected. Lint, format and backend collection fail on the
unresolved conflict. External integration test receives array-shaped audit data
from a service not proven to run this branch. Inventory check-6 names an
unregistered suite. Prior result inspected, not accepted as fresh validation.

Assumption: finish the already in-progress merge of the exact supplied develop
base rather than fetching a moving remote ref. Reconcile develop's shared audit
read used by settings/schedules with #358's bounded, principal-scoped page seam;
never restore the unbounded helper or weaken ADR-073 admin authorization.

## Merge reconciliation

Read repository instructions and accepted ADR-062/ADR-073. Canonical execution
is unchanged. Conflict resolution keeps the paginated main audit route and
reconciles develop's settings/schedule projections via an action-filtered async
page stream from the same bound authority. Projection outputs retain existing
1..1000 caps; they no longer materialize the corpus. Settings merges at most
three capped action streams; schedules merges two, retaining Workspace visibility.
Legacy scheduler records name `system`, not the reader, so their existing
Workspace authorization remains appropriate rather than applying personal actor
filters. Bound Sentinel records require admin before any query on *all* these
surfaces (ADR-073 overrides unrestricted secondary reads in develop).

Residual: legacy schedule target visibility is checked per page, not inside SQL;
it may scan many pages to find visible receipts. No claim of a bounded-work
schedule-history query is made. Main audit scope predicates remain inside SQL.

Added three collected convergence cases: secondary surfaces deny non-admins
before queries, and settings consumes multiple bounded action-filtered core
pages while the unbounded read is forbidden. Strengthened existing history test
with >1 page of newer foreign receipts and a limit assertion.

Fresh exact vulture gate: 1364 findings, zero unclassified; four live `get_page`
identities lack trusted-base authorization (base `8c8fc8d6706a`), and reports
removed `samples_evaluated` against that base. Review candidate ledger next;
no candidate grant will be edited. Initial lint found missing Request import
in repaired settings signature; corrected before tests.

## Executed validation (fresh)

- `uv sync --locked --extra dev`: passed.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **76 passed** (23.75s). Legacy million-row index construction 10.461s;
  first page 0.0009s; scoped page 0.0004s; maximum measured VM work <2800.
  Includes the actual PM audit acceptance function over in-process production
  routes for both real canonical SQLite and legacy authority bindings.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: **8 passed, 4 PostgreSQL cases skipped** (DSN not configured).
  Canonical SQLite million-row load 10.069s, max query work 3400 VM instructions.
- `uv run ruff format packages/hive-conductor/backend/tests/test_audit_convergence.py`:
  formatted one file after initial format failure. Final `uv run ruff check .`
  and `uv run ruff format --check .`: passed (2811 files).
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: passed (3340);
  same command for `packages/maistro-core/tests`: passed (12249).
- `uv run python scripts/check-api-route-contracts.py`: passed, 281 handlers,
  15 audited routes, zero canned handlers.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  failed because all nine required producer results are missing locally. This
  does not identify which remote producer failed. No invented success evidence.
- `node --test tests/ci/integration-scope.test.cjs`: 8 passed (aggregator contract,
  not proof of producer results).
- `git diff --check`: passed.

Candidate vulture ledger reviewed: four retained get_page rows already banked
at lines 1019, 1028, 1090, 1189; removed samples_evaluated already absent.
Relative to exact incoming develop, ledger diff is four additions, no removals.
No missing identities to bank or obsolete rows to prune; duplicating rows would
be incorrect. Gate still requires trusted-base authorization outside this lane.
Incoming develop grant/ledger changes are preserved verbatim, not authored here.

Regression check: executed pytest with a process-local plugin replacing only
settings' projection iterator with a full `get_entries(limit=10000)` read (the
develop regression). The new test failed at `forbidden_list` with
`projection must not materialize the corpus`, as intended. The driver asserted
TESTS_FAILED; source files were never changed. This proves the new test detects
the unbounded-read regression rather than merely observing a seeded count.

## Acceptance / residual risks

| Criterion | Evidence |
| --- | --- |
| Backend bounded cursors, stable order, max size | Fresh backend/core tests pass against reachable HTTP routes and real SQLite adapters (200-row ceiling, tied timestamps, invalid/past-end cursors). |
| Scope before DB pagination | Fresh SQLite scope/filter and authorization-before-query tests pass; core SQL predicates precede LIMIT. Secondary legacy schedule projection still filters target visibility after each page, an explicitly documented limitation. |
| Frontend incremental loading + virtualization | Source inspected: cursor continuation, retained 500-entry window, rendered slice + overscan. Runtime browser validation UNVERIFIED; existing E2E cases inspected but not executed against an unrelated running image. |
| Filters, export, retention without browser corpus | Fresh server filter, capped streaming export and retention-metadata tests pass; native download link avoids JS export accumulation. Actual retention/purge is absent (`corpus_purge: none`, #325), so that portion is NOT PROVEN. |
| Representative large-dataset strategy | Both real SQLite query seams measured on one million rows with deterministic VM-work bounds. PostgreSQL runtime UNVERIFIED (4 skipped tests). |
| Concurrent inserts, cursor stability, isolation, max limit, empty pages, million-row envelope | 76 backend + 8 core tests pass; PostgreSQL cases skipped. |
| Initial cost independent of corpus | Proven for indexed SQLite after startup migrations; NOT met by the legacy memory fallback, which copies/sorts the whole corpus (`audit_query.py:386`). |
| Bounded browser memory/DOM | Implementation retains 500 entries and mounts a window; runtime UNVERIFIED. |

## Disposition

BLOCKED, not integration approval. The merge conflict and unbounded shared-read
regression are repaired, with local tests and inventory passing. Named gates
remain blocked by missing producer evidence and trusted-base authorization.
No remote mutation, grant change authored here, dead-code cosmetic workaround,
or weakened assertion/gate. Existing staged develop changes are preserved.

Authored files: `backend/routes/{audit,settings,schedules}.py`,
`backend/tests/{test_audit_convergence,test_noop_route_contracts}.py`, and this
note (all backend paths under `packages/hive-conductor/`). The merge additionally
carries the pre-existing incoming develop changes listed in the salvaged index.

Next: obtain exact-candidate integration producer evidence and land trusted-base
authorization for retained get_page methods via the separate grant process;
then validate PostgreSQL/browser and resolve the retention/non-durable envelope
limitations before claiming all #358 acceptance criteria.

Merge committed locally as `e22d1fab5` (parents `cf26060d1`, `045cfdfbe`).
After the regression injection process exited, the normal convergence and
noop-route tests passed again: **30 passed**. Post-commit exact vulture rerun
now resolves the correct merged trusted base `045cfdfbe3ea`: **still fails on
exactly the four retained get_page identities**, zero unclassified findings.
The obsolete samples_evaluated report disappears with the base reconciliation.
Post-commit ruff lint/format pass; merge leaves a clean worktree.

Progress: checked 1, done 0, skipped 0, errors 1 (blocked); repair committed as
handoff, not completion of the issue.
