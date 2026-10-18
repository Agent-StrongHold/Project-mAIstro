# Issue #358 repair checkpoint (84a1)

## Frozen scope

Only issue #358 / existing PR #1712 evidence is in scope. Starting HEAD:
`249b8ca299afb195f6dbc417218fb70cc2993808`; assigned base:
`56332162cf636e9a1e8a7e346101803ed6ec7b1f`. Worktree started clean.
No GitHub mutations or ref refreshes are planned.

Inspection/repair scope: Conductor audit routes, audit_query/audit_bridge,
audit stores, AuditLog/Profile UI, existing audit pagination/convergence/route
and PM workflow tests, core persistence audit pages and tests, audit migration,
relevant ADRs, integration-scope/vulture gate implementation and workflow,
quality/vulture-baseline.json (only reviewed identities if required), and this
report plus an inventory note if tests change. Other issues are excluded.

## Initial evidence and assumptions

Driver check-3 failed: external PM workflow expected HTTP 403, received 200.
Driver check-6 failed: `packages/hive-conductor/tests` has no inventory recipe.
Driver checks 0/1/2/4/5/7 passed; not treated as acceptance proof.
Prior result reports trusted-base vulture authorization and integration producer
evidence blockers, an O(corpus) memory fallback, and unverified browser/retention
behavior. Assume this is a focused repair, not a develop-sync conflict; no merge
is warranted without conflict evidence. Inspect actual gates before changing code.

## Gate checkpoint

The exact requested Vulture scan exited 1 (repair-vulture.log in the job directory):
four retained `get_page` identities require trusted-base authorization. This is
not evidence that another candidate-ledger amendment can fix the gate. The
integration-scope checker requires hosted producer conclusions; its command has
no base/head validation mode. Captured check parsing initially failed on nullable
`output.summary`; handle that once and do not refresh remote evidence.

The second parse succeeds: the captured remote PR head `84081fba82fc` actually
has integration-scope and all nine specialized producers successful. That is not
the assigned candidate `249b8ca299af`, so it cannot prove this candidate's gate.
No candidate-specific failed producer diagnostic is supplied: UNRESOLVED rather
than an invented source repair. Docker socket probe failed (daemon unavailable).

Reviewed ledger lines 1001/1010/1072/1175 already contain exactly the four reported
`get_page` identities. `services/audit_bridge.py:186` calls the protocol in the
production route path outside the scanner's packages/*/src scope. These APIs
are retained, not dead. Do not duplicate their multiset entries or add a fake
scanner-only caller. A trusted-base grant is still required; this lane cannot
self-authorize it.

Read Accepted ADR-068, ADR-073 and ADR-081226-69ee. The initially guessed ADR-068
filename did not exist (skipped); the resolved authorization ADR was then read.
Canonical decision audit remains admin-only; personal actor-scoped reads apply
only to the unbound legacy fallback. No execution or authorization authority
change is appropriate to accommodate the external E2E response.

## Fresh validation checkpoint

Ruff check/format PASS; 77 focused backend tests PASS; 45 core tests PASS with
four PostgreSQL skips. Million-row legacy SQLite migration 8.378s; first/scoped
pages 0.0006/0.0003s, maximum VM work <2,800. Canonical million-row SQLite load
7.693s; maximum VM work 3,400. Registered inventory suites all PASS. Integration
checker exits 1 without nine candidate producer results (this diagnoses missing
evidence, not a reproduced hosted producer failure). Its Node unit tests PASS.
Frontend production build PASS. External PM E2E still exits 1. Memory read probe
calls production `page_entries(limit=1)` and counts 100/100 and 10,000/10,000
visited rows: corpus-independent initial cost is NOT MET on legacy memory reads.
Logs are `repair-*.log` in the assigned job directory. No tests changed.

## Executed command record

All test/gate/build command batches used 1,200-second timeouts.

| Command | Outcome |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | FAIL: four already-banked identities lack trusted-base authorization |
| `uv run python scripts/check-integration-scope.py --event-name pull_request` | FAIL: nine missing candidate producer conclusions; no manufactured `--result` values supplied |
| `node --test tests/ci/integration-scope.test.cjs` | PASS; checker tests are not producer evidence |
| `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s` | 77 passed |
| `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s` | 45 passed, four PostgreSQL skipped |
| `uv run pytest packages/hive-conductor/tests/e2e/test_pm_agent.py packages/hive-conductor/tests/e2e/test_pm_workflow_api.py -q -x` | 1 failed, 7 passed, 13 skipped; expected 403, got list-shaped 200 at test_pm_workflow_api.py:271 |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests --suite packages/hive-conductor/tests/e2e` | PASS: 3,396 / 13,780 / 23 |
| `npm --prefix packages/hive-conductor/frontend run build` | PASS |
| `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format '{{.Names}} {{.Ports}}'` | FAIL: daemon unavailable |
| Inline `PYTHONPATH=packages/hive-conductor/backend uv run python` instrumented memory read | Reproduced whole-corpus visitation for a one-row request |

The E2E service on localhost:8101 has unverified code provenance: its array-shaped
response is not the worktree route's `AuditPage` response. Do not change the local
admin-only assertion to accept this incompatible external service. Candidate
Conductor/Container convergence tests pass independently.

## Acceptance matrix

| Criterion | Evidence / residual gap |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum page size | Focused route and SQLite/memory tests passed; maximum, floor, malformed cursor and timestamp ties covered. PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before DB pagination | SQLite filtered/scope tests and canonical non-admin route denial tests passed. External E2E fails expected authorization. |
| Incremental frontend loading and virtualization | AuditLog.tsx inspected: cursor requests, 500-entry retained window, viewport slicing, stale-response generations. Build passed. Browser runtime UNVERIFIED; do not run candidate UI assertions against the unidentified external UI. |
| Filters/export/retention without whole browser corpus | Filtered/scoped streamed export tests and retention metadata tests passed. Export uses a download link, not JS accumulation. Retention lifecycle UNVERIFIED: audit_query.py:79 explicitly declares no purge, with policy owned by #325. |
| Representative measured query/index strategy | Both million-row SQLite production-query tests passed with the VM-work measurements above. PostgreSQL performance UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, max limit, empty pages, million-row tests | Executed backend/core tests cover these for SQLite/memory; four PostgreSQL cases skipped. |
| Initial page cost bounded independently of corpus size | NOT MET on reachable legacy memory path: audit_query.py:402 snapshots every row, then sorts. SQLite indexed path measured bounded. |
| Bounded browser memory/DOM row count | Source has bounded retained rows/virtualization, build passed; browser execution and byte-level heap bound UNVERIFIED. |

## Disposition and handoff

BLOCKED; no evidence-supported gate repair is available within this lane's
permissions. This report is the only changed file. No production changes, test
additions, inventory delta, ledger/grant edits, policy weakening, remote mutation,
or destructive git operations. Prior implementation remains intact.

The allowed vulture amendment was reviewed and is unnecessary: the candidate
ledger already contains all retained findings. The missing trusted-base grant
cannot be supplied by this implementation commit. Integration-scope needs
candidate-specific producer results or the actual failed producer log before
there is a source failure to repair. The supplied captured PR checks at another
SHA are explicitly not substituted.

Progress: checked 1, done 0, skipped 0, errors 4 (vulture authorization,
integration evidence, unavailable Docker, external E2E contract). Next: provide
trusted authorization and candidate producer diagnostics plus an identified
candidate service stack. Substantive memory-path/retention/browser acceptance
remains open. Do not repeat this same repair dispatch expecting a ledger
amendment or documentation-only commit to make the issue merge-ready.
