# Issue #358 — frozen-snapshot CI repair handoff

## Scope and disposition

Assigned worktree `auto-358`, starting head
`179575d9441a87fd0db8d75985f238ad2d493692`, base
`b672b799aba6d3db9edc3e1be18b1a3335dd3bc0`; both resolved, initial tree clean.
Processed only issue #358, its supplied branch diff, and named integration-scope
and Vulture failures. No GitHub requests/mutations, sync conflicts, discarded
work, gate changes, or grant changes. This report is the only changed file.
No tests changed, so no inventory delta is required.

**BLOCKED, not merge-ready.** The integration claim is stale for the captured
PR head; trusted-base Vulture authorization remains absent. No speculative
runtime or ledger changes are justified by those gate findings.

## New evidence versus the prior handoff

Logs are in `/home/dev/maistro/jobs/41a5aa27b6944c47b7ad23c1e2c12e71/`.
Read the supplied dispatch, prior result, and driver check logs. Replayed the
captured latest-by-ID specialized conclusions through the real integration
checker (no invented successes):

- All nine required specialized checks **succeeded**, as did integration-scope
  check `111876945769`. Replay exits 0 (`repair-integration-snapshot.log`).
- These checks belong to linked PR head `84081fba82fc`, **not** assigned head
  `179575d9441a`. They resolve the captured historical failure claim, but do not
  establish candidate-specific CI success. No re-fetch or polling performed.
- Running the checker without results exits 1 as designed
  (`repair-integration-no-input.log`); that invocation is not CI equivalence.
- The exact requested Vulture scan still exits 1: 1,346 findings against 1,342
  trusted identities (`repair-vulture.log`). Four live `get_page` definitions
  are identified at `pg_audit.py:49`, `sqlite_audit.py:96`,
  `protocols/memory.py:536`, and `security/sentinel/audit.py:42`.
  `backend/services/audit_bridge.py:186` calls this protocol in production.
  Candidate ledger rows already exist at `quality/vulture-baseline.json:1001`,
  `:1010`, `:1072`, and `:1175`. Duplicating them cannot authorize new debt.
  No ledger amendment is needed to match the scan, and this lane cannot create
  trusted-base authorization. Retaining reachable APIs is not dead-code repair.

Read accepted ADR-068 and ADR-073: canonical Sentinel audit remains admin-only;
legacy personal-trail access cannot override that rule. No execution, event,
store, or authorization authority was introduced.

## Fresh validation

| Command | Outcome |
| --- | --- |
| `uv run ruff check .` | Pass (`repair-ruff.log`) |
| `uv run ruff format --check .` | Pass (`repair-format.log`) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Fail: trusted-base authorization, above |
| `uv run python scripts/check-integration-scope.py --event-name pull_request` with captured `--result CHECK=RESULT` arguments | Pass for captured PR head only; full argv in replay log |
| `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s` | 77 passed (`repair-backend.log`) |
| `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s` | 45 passed, 4 PostgreSQL cases skipped (`repair-core.log`) |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e --suite packages/maistro-core/tests` | Pass: 3,393 / 23 / 13,738 tests (`repair-inventory.log`) |
| `npm --prefix packages/hive-conductor/frontend run build` | Pass (`repair-build.log`); not browser-runtime proof |
| `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format '{{.Names}} {{.Ports}}'` | Cannot connect to daemon; no PostgreSQL validation claimed |

The driver's `check-3.log` fails at
`packages/hive-conductor/tests/e2e/test_pm_workflow_api.py:271`: health selects
canonical behavior (403), but the external service returns 200 with a legacy
array. Its deployed revision is unknown; local route tests pass. Do not weaken
the assertion to accept either response. Driver `check-6.log` specifies the
unregistered suite `packages/hive-conductor/tests`; the registered `tests/e2e`
recipe passes above. These are not grounds to change production authorization
or inventory gates.

## Acceptance assessment

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Bounded cursor pagination, stable ordering, max size | Passing focused adapter and HTTP tests cover ties, malformed cursors, maximum/floor, empty pages. PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before database pagination | Passing scope/filter tests and convergence tests; inspected route authorization before core reads and SQL scope predicates before limits. |
| Incremental frontend loading and virtualization | Production build passes; inspected cursor loading, generation guard, observer and viewport slices in `AuditLog.tsx`. Browser runtime UNVERIFIED. |
| Filters, export, retention without whole-corpus browser load | Passing filter and lazy capped-export tests. Retention route returns constants and declares purge absent; actual retention lifecycle UNVERIFIED (separate #325 policy owner). |
| Measured large-dataset query/index strategy | Real million-row SQLite tests pass: legacy index build 9.596s, first page 0.0007s, scoped page 0.0003s, work <2,800 VM instructions; canonical load 7.661s, max work 3,400. PostgreSQL envelope UNVERIFIED. |
| Tests for inserts, cursors, isolation, max, empty, million rows | 122 passed, four PostgreSQL cases skipped. Tests execute production adapters/query functions, not mocked SQL. |
| Initial-page cost independent of corpus size | **NOT MET** for reachable memory fallback: fresh counted-mapping probe of production `page_entries(limit=1)` visits 100/100 and 10,000/10,000 entries (`repair-memory-probe.log`). `audit_query.py:386` sorts the corpus each request; core memory adapter also scans. Durable SQLite work bounds pass. |
| Bounded browser memory/DOM | Source retains at most 500 entries and renders a viewport slice; browser runtime UNVERIFIED. |

## Next prerequisites

Do not repeat identical ledger amendments: the gate explicitly requires a
reviewed authorization already on the trusted base for these retained APIs.
Obtain actual candidate-specific producer evidence, then address the memory
query-cost gap and run PostgreSQL/browser acceptance in a functioning test
stack. This report preserves the current implementation; it does not claim a
runtime fix or integration approval.

Progress: checked 1 issue, done 0 complete repairs, skipped 0 issues,
errors 1 unresolved named gate (Vulture). Historical integration evidence is
resolved for its recorded head only. Local commit required for this handoff.
