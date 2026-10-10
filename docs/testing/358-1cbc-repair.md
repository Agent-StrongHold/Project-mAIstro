# Issue 358 focused repair (job 1cbc)

## Frozen scope

- Issue #358 only; branch auto-358, starting HEAD
  `1fb2dc3d052af852a71c5d32b4229bc1bbfc0dcf`, supplied base
  `291bdd187a512a9cda5a33cb98cff655564d7f4d` (both resolve locally).
- Starting worktree clean. Preserve prior implementation and notes.
- Process the supplied integration-scope/vulture failures and audit workflow
  regression; inspect existing audit route/service/store/UI and adjacent tests.
  Candidate edits limited to those audit files, workflow tests, reviewed vulture
  identities if the actual scan requires them, and this report/inventory note.
- No remote enumeration, sync, GitHub mutation, or unrelated repairs.

## Initial evidence / ambiguity

Driver check-3 fails at test_pm_workflow_api.py:271 (expected 403, got 200).
Driver check-4: 77 audit tests pass. Check-6 requests an unregistered suite
`packages/hive-conductor/tests`; this is not evidence of a product failure.
The supplied integration-scope failure has no diagnostic in the short prompt;
run the existing gate against the supplied resolved base/head before deciding
whether any change is justified. Prior claims are not acceptance evidence.

## Gate evidence checkpoint

The exact requested Vulture command exits 1: four `get_page` identities are
already present in the candidate ledger but not authorized by trusted base
`c560d4ccad82`. Production `audit_bridge.py:186` calls the protocol method;
these are retained APIs, not dead code. No further ledger amendment is justified
by this scan, and ordinary grant edits are prohibited.

The integration checker consumes hosted producer results, not git base/head.
Correction to the initial assumption: do not pass invented base/head arguments
or fabricate successful producer evidence. No sync conflict exists locally.

The prior report establishes why repeated repairs stalled, but its acceptance
claims will be rechecked locally. No authorization relaxation or scanner-only
call site is an acceptable fix.

Fresh focused tests: 77 backend passed; 45 core passed, 4 PostgreSQL skipped.
Both million-row SQLite tests executed: legacy index migration 8.730s, initial
page 0.0008s, scoped page 0.0004s, maximum VM work <2,800; canonical load 7.937s,
maximum VM work 3,400. Ruff lint/format and the three registered inventory
suites pass (3,396 backend / 13,780 core / 23 E2E). Docker socket is unavailable.
Integration checker exits 1 with missing producer results, not a source failure.

## Final validation

Logs are preserved under the supplied job directory with `repair-1cbc-*.log`
filenames. Commands used 1,200-second timeouts where tests/builds were involved.

| Command | Outcome / log suffix |
| --- | --- |
| `uv run ruff check .` | PASS / ruff |
| `uv run ruff format --check .` | PASS / format |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | FAIL: trusted-base authorization / vulture |
| `uv run python scripts/check-integration-scope.py --event-name pull_request` | FAIL: nine missing producer results / integration |
| `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format '{{.Names}} {{.Ports}}'` | FAIL: cannot connect to daemon |
| `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s` | 77 passed / backend |
| `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s` | 45 passed, 4 skipped / core |
| `uv run pytest packages/hive-conductor/tests/e2e/test_pm_agent.py packages/hive-conductor/tests/e2e/test_pm_workflow_api.py -q -x` | 1 failed, 7 passed, 13 skipped / e2e |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests --suite packages/hive-conductor/tests/e2e` | PASS / inventory |
| `npm --prefix packages/hive-conductor/frontend run build` | PASS / build |
| `node --test tests/ci/integration-scope.test.cjs` | PASS (checker tests, not hosted producer evidence) / integration-tests |
| `git diff --check` | PASS |

The fresh E2E fails at `test_pm_workflow_api.py:271`: the external localhost:8101
service returns a list-shaped 200 where a bound canonical authority requires
403. Its code provenance is unknown and its response does not match this
worktree's page-shaped route. Do not weaken the assertion to accommodate it.
Local route/Container convergence tests pass; they do not certify that service.

A fresh inline `PYTHONPATH=packages/hive-conductor/backend uv run python` probe
wrapped a dict's `items()` to count visits, then called production `page_entries`
with `limit=1`. It visited 100/100 and 10,000/10,000 entries, returning one row
in each case. `audit_query.py:402,474` therefore still violates corpus-independent
initial page cost on the reachable memory fallback. Fixing that architectural
read-path gap is not an evidence-based repair of the named CI gate failures.
It remains a substantive issue-358 acceptance gap, not a cosmetic finding.

## Acceptance matrix

| Criterion | Current executed evidence / remaining gap |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum size | SQLite/memory and real route tests pass, including ties and clamped limits; PostgreSQL runtime UNVERIFIED (four skips). |
| Authorization/scope before DB pagination | SQLite scope/filter tests and local canonical admin-denial tests pass. External deployment fails the expected contract. |
| Incremental frontend loading and virtualization | Production source has cursor requests, sliding 500-entry window and viewport slicing; build passes. Browser runtime UNVERIFIED. |
| Filters, export, retention without browser corpus load | Scoped filtered exports and retention metadata route tests pass; download link avoids JS buffering. Actual retention lifecycle UNVERIFIED: `audit_query.py:79` declares no corpus purge (#325 owns policy). |
| Measured representative query/index strategy | Both million-row SQLite production query tests execute with bounded VM work, measurements above. PostgreSQL envelope UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, maximum, empty pages, million-row tests | Focused suites exercise these successfully for SQLite/memory. PostgreSQL cases remain skipped. |
| Initial page cost independent of corpus size | NOT MET for memory fallback: counted traversal above. Durable SQLite path measured bounded. |
| Bounded browser memory/DOM | Source bounds rows; build passes. Browser execution/heap evidence UNVERIFIED. |

Read repository instructions, documentation map and Accepted ADR-068, ADR-073,
ADR-081226-69ee. Reconciliation: canonical decision audit stays admin-only per
ADR-073; own-actor legacy fallback is not permission to expose canonical audit.
No execution, event, authorization or store authority was introduced or changed.

## Disposition

BLOCKED. Only this report changes; no production repair is claimed. No tests
added/removed/changed, hence no inventory delta. The four reviewed retained
identities are already banked in `quality/vulture-baseline.json`; adding them
again would corrupt its multiset. No grant or gate edits, remote actions, sync,
or destructive commands. Prior work preserved. Commit this report locally.

Progress: checked 1, done 0, skipped 0, errors 4 (Vulture authorization,
integration producer evidence, Docker unavailable, external E2E failure).
Next: obtain trusted-base authorization and candidate-specific integration
producer evidence; supply an identified candidate test stack; address memory
fallback cost and execute browser/PostgreSQL acceptance. Repeating identical
repair dispatches cannot establish these prerequisites.


