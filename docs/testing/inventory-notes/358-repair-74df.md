# Issue 358 repair — 74df

## Frozen scope

One item: issue #358, worktree `/home/dev/Git/wt/auto-358`, branch `auto-358`,
starting head `be237e16edd59e9a567ec6ec31adc1bb021ae12d`, supplied develop base
`8c8fc8d6706a0837bd991c4e92138bf4d776ac9e`. Worktree initially clean.
Inspect only audit pagination production paths, adjacent tests/ADRs, saved job
checks 0–7, and the named integration-scope/vulture gates. Potential edits are
restricted to those paths, the explicitly permitted vulture ledger, and this
note. No grants, unrelated code, remote mutations, or speculative CI repairs.

Initial state: prior result reports authorization rather than missing ledger
identities, missing integration producer evidence, obsolete external service,
and incomplete acceptance evidence. These claims require fresh checks.
The supplied develop base is not an ancestor of HEAD (merge base is
`15157c6f2bc57d5f7dc7d9e212adb323864d32ef`); the large two-dot diff is not
assumed to be issue-owned changes. No sync conflict is present. Ambiguity:
remote integration-scope producer failure is unspecified; inspect local gate
and supplied logs, never fabricate producer successes.

## Fresh gate evidence

- Saved checks 0–2 pass sync/lint/format; 4 passes 58 backend tests; 5 and 7
  pass backend/core inventory. Saved check 6 uses an unregistered suite path.
  Saved check 3 fails `test_pm_workflow_api.py:271`: service health identifies
  canonical bridge but audit responds 200 with an array instead of required 403.
- Fresh `uv sync --locked --extra dev`: passed.
- Exact requested vulture command: FAILED, 1363 findings, zero unclassified,
  four added `get_page` identities against trusted base `15157c6f2bc5` lacking
  authorization. No candidate bookkeeping mismatch reported. No grant edit
  permitted; inspect production reachability before changing retained methods.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  FAILED, all nine producer results missing. This is not evidence identifying
  the remote failing producer. `node --test tests/ci/integration-scope.test.cjs`:
  8 passed. Remote failure cause remains UNRESOLVED absent producer logs.

## Architecture and focused validation

Read repository instructions and accepted ADR-073/ADR-062. Decision audit stays
admin-only; do not weaken the external test to permit a canonical non-admin read.
No change to Goal → Graph → Run → NodeRun → Attempt or any authority is warranted.
The four vulture identities are already retained at ledger lines 1021, 1030,
1089, 1188; `audit_bridge.py:186` invokes the actual protocol/adapters. Deleting
these methods breaks bounded production reads. Adding the same ledger rows
again cannot authorize them, and artificial callers would only hide evidence.
Therefore no ledger edit is justified by the actual gate output.

Fresh commands (1200-second timeout):

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 2776 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py -x -q -s`:
  8 passed, 4 PostgreSQL cases skipped (no DSN). Million-row SQLite load 8.027s,
  maximum production query work 3400 VM instructions over filter/cursor shapes.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py -x -q -s`:
  58 passed. Legacy million-row startup index migration 11.367s; initial/scoped
  pages 0.0009s/0.0004s, maximum measured query work below 2800 VM instructions.

Production source confirms the retained browser window is capped at 500 rows,
with a virtual viewport and cursor loading. Export uses a native download link,
not a browser corpus array. Retention remains metadata-only (`corpus_purge:
none`), and in-memory reads sort the corpus per request. The unqualified initial
cost definition is therefore unmet even though both SQLite paths are bounded.

## Additional acceptance review

Read the actual route/convergence/pagination tests, not just test names. They
exercise real SQLite queries, canonical Container binding, admin rejection
before any store query, separate scoped legacy pages, export caps, timestamp
ties, concurrent acknowledged inserts, missing scope, malformed cursors, and
empty/past-end pages. The convergence test reuses the saved failing external PM
assertion against both production bindings in-process; both pass. That does
not make the external service an instance of this candidate.

`DOCKER_HOST=unix:///var/run/docker.sock docker ps --format ...` FAILED:
Cannot connect to the Docker daemon. No database fixture was pointed at a
shared/unknown database (the fixtures truncate tables). PostgreSQL execution
remains UNVERIFIED. Browser tests in `tests/e2e/pm-workflow.spec.ts:238–352`
assert stale-response rejection, repeated visible-sentinel loads, an eight-page
cursor walk, at most 30 mounted rows and 500 retained entries. These were
inspected but NOT executed against this candidate; the supplied service's audit
contract already differs, and no background server was started. Do not infer
browser acceptance from source inspection or an unrelated running service.

## Acceptance disposition

| Criterion | Executed evidence / limitation |
| --- | --- |
| Backend bounded cursor pagination, stable ordering, maximum size | 66 backend/core tests passed; SQL and route behavior exercised; limit 200 plus one lookahead. PostgreSQL adapter execution UNVERIFIED. |
| Authorization/scope filters before database pagination | Real-route denial-before-query tests, SQLite org/user/boundary/verdict and legacy actor-scope/filter parity tests passed. |
| Incremental frontend loading and virtualization | Production cursor loader, 500-entry window and virtual slice inspected; browser execution UNVERIFIED. |
| Filters/export/retention without browser corpus | Scoped/filtered export and cap tests passed; frontend download anchor inspected. Retention only exposes constants (`audit_query.py:79` says no purge); actual retention operation UNVERIFIED/absent. |
| Query/index measurements on large datasets | Both million-row SQLite production paths measured above; PostgreSQL UNVERIFIED due to unavailable daemon/no DSN. |
| Concurrent inserts, cursor stability, scope isolation, max limit, empty pages, million-row envelope | Passing focused tests cover these cases on SQLite/memory; PostgreSQL cases skipped. |
| Initial page cost independent of corpus | SQLite work bounds pass; in-memory path at `audit_query.py:386` still sorts all keys and canonical in-memory adapter also scans/sorts. Unqualified criterion NOT met. |
| Browser memory/DOM remains bounded | Entry-count cap/virtual slice and meaningful existing browser assertions inspected; runtime DOM/heap evidence UNVERIFIED. |

## Handoff

BLOCKED. The explicit ledger exception permits correcting candidate bookkeeping,
not granting trusted-base authorization. The candidate already contains all four
reviewed retained identities, so no ledger amendment can resolve this evidence.
No production/test/gate changes are justified by the two named CI failures.
Need authorized trusted-base provenance plus candidate-specific failed producer
logs; then validate the deployed branch, PostgreSQL and browser, and resolve the
retention/in-memory definition-of-done gaps without creating a new authority.

Fresh inventory gates passed: `uv run python scripts/check-suite-inventory.py
--suite packages/hive-conductor/backend/tests` (3310) and the same command with
`--suite packages/maistro-core/tests` (12141). `git diff --check` passed.

Only this evidence note changed; no tests added/removed (no inventory delta),
no grants/ledgers/gates changed, no GitHub mutations. Progress: checked 1, done 0,
skipped 0, errors 1 (blocked); next: external prerequisites above. Commit this
handoff locally rather than leave uncommitted work.
