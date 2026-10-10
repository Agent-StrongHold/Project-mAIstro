---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue 358 — repair f53a

## Frozen scope

One assigned item: #358, branch `auto-358`, worktree `/home/dev/Git/wt/auto-358`.
Starting HEAD verified as `ed10539becd12d9e8403d9149cf7da2f33665041`; incoming
tree clean. Supplied base: `cf4a562b65e0f459eec8e77e8b10ca7aa4f847d0`.
Inputs: this job's check-0 through check-7 logs, supplied previous check-3 and
0f14 result, audit production routes/services/adapters/UI and adjacent tests,
ADRs governing audit/execution, integration-scope and vulture CI definitions.
Changes limited to evidence-supported repairs in those files and this note;
no new issue enumeration, remote mutations, grants, or speculative sync.

Initial evidence: current driver check-3 receives HTTP 200 and an unpaginated
list from an external service reporting MaistroCoreBridge, where candidate
canonical audit requires admin authorization. Prior artifact reports missing
integration producer conclusions and trusted-base vulture authorization;
these claims will be rechecked, not assumed. No merge conflict is present.
Ambiguity: external deployment revision and exact merge-queue producer evidence
are not supplied. Do not infer either from the candidate source.

## Results

- `uv sync --locked --extra dev`: passed. Supplied base resolves.
- Exact requested vulture command failed: 1364 findings, zero unclassified;
  four `get_page` identities are new against trusted base `045cfdfbe3ea`.
  Gate explicitly requires a reviewed grant landed first; candidate ledger
  changes cannot authorize them. Log: `/tmp/358-f53a-vulture.log`.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`
  failed without producer inputs. This demonstrates fail-closed behavior, not
  the remote failure cause. Log: `/tmp/358-f53a-integration.log`.
- Focused backend command: `uv run pytest
  packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **76 passed**, 19.60s (`/tmp/358-f53a-backend.log`). Includes the external
  PM assertion run through actual candidate routes/auth for both bindings.
  Million-row legacy SQLite migration 9.352s; first page 0.0007s; scoped page
  0.0004s; maximum query work <2800 VM instructions.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: **8 passed, 4 skipped**, 10.04s (`/tmp/358-f53a-core.log`).
  Million-row canonical SQLite load 8.457s; maximum query work 3400 VM
  instructions. PostgreSQL DSN absent; runtime remains UNVERIFIED.
- Inspected all eight driver logs. check-6 fails because
  `packages/hive-conductor/tests` has no inventory collection recipe, not a
  count mismatch. check-3 fails against the external old response; other
  checks pass. No producer check-run evidence is supplied for integration.
- All four retained `get_page` identities already exist in candidate ledger
  (`quality/vulture-baseline.json:1019,1028,1090,1189`). They are live APIs:
  `backend/services/audit_bridge.py:188` calls the protocol implemented by
  these adapters. Caller is outside the vulture scan roots. Adding duplicates,
  renaming live APIs, or inserting dummy references would not be a repair.
  Existing exact ledger amendment is preserved; trusted-base grant is outside
  this writer's authority. Integration workflow requires nine exact-candidate
  producer conclusions; local tests cannot replace those conclusions.
- Read ADR-068, ADR-073, ADR-081226-a66b. Reconcile personal legacy audit scope
  with admin-only Sentinel decisions (ADR-073); preserve canonical execution
  and authorization authorities. No architectural replacement is warranted.
- `uv run ruff check .` and `uv run ruff format --check .`: passed (2811 files).
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: passed, 3340 tests; same command
  with `--suite packages/maistro-core/tests`: passed, 12249 tests.
- `uv run python scripts/check-api-route-contracts.py`: passed, 281 handlers,
  15 audited routes, zero canned. `node --test tests/ci/integration-scope.test.cjs`:
  8 passed. `git diff --check`: passed.

## Acceptance review

| Criterion | Fresh evidence / limitation |
| --- | --- |
| Backend bounded cursor pagination, stable ordering, max page size | 76 backend + 8 core tests passed; production adapters clamp to 200 and order by timestamp plus immutable row identity. PostgreSQL execution UNVERIFIED (4 skipped). |
| Authorization/scope before database pagination | Production-route tests reject non-admin canonical reads before either query method; SQLite tests execute exact actor/org predicates before LIMIT. |
| Incremental loading and virtualization | `AuditLog.tsx` inspected: 100-row cursor requests, 500 retained rows, viewport slice. Existing Playwright tests inspected but not run; browser runtime UNVERIFIED. |
| Filters, export, retention without whole-corpus browser loading | Scope/filter and capped streaming NDJSON tests pass. Native download link inspected. Retention route declares `corpus_purge: none`; operational retention UNVERIFIED, delegated to #325, not proven by metadata tests. |
| Query/index measurements on large datasets | Real million-row legacy and canonical SQLite queries measured above, including scope/filter shapes and deep timestamp ties. PostgreSQL measurement UNVERIFIED. |
| Concurrent inserts, stability, isolation, maximum limit, empty pages, million-row envelope | Executed backend/core tests cover these on SQLite/memory, including acknowledged threaded writes and repeated request IDs. PG runtime skipped. |
| Initial page cost independent of corpus size | Proven for indexed SQLite request work after startup migration. NOT met across all reachable modes: `audit_query.py:386` copies/sorts the memory corpus; `security/sentinel/audit.py:59` scans its list. |
| Bounded browser memory/DOM rows | Source caps retained entries and mounted slice; runtime/heap UNVERIFIED. Individual detail payload size is not capped by the row-count limit. |

## Disposition / handoff

**BLOCKED**. Only this validation/handoff note changed; no source, tests, ledger,
grants or gates changed. No test additions; inventory delta zero. The failed
external PM assertion is not evidence to weaken the candidate's independently
passing route contract. Integration failure root cause remains UNRESOLVED:
missing producer inputs here cannot establish which remote producer failed.
No ref fetch, remote enumeration, speculative merge or GitHub mutation performed.

Next operator inputs required: exact merge-queue candidate and failed producer
logs; trusted-base authorization for the four already-banked live APIs; candidate
revision evidence for the external PM deployment. Browser/PG execution,
corpus-dependent memory reads, and operational retention remain completion gaps.
Do not repeat this repair with unchanged missing evidence or amend the exact
ledger with duplicate identities. Local commit is a blocked handoff, not a fix
or integration approval.

Progress: checked 1, done 0, skipped 0, errors 2 (named gates); next: provide
trusted-base authorization and exact-candidate producer evidence.
