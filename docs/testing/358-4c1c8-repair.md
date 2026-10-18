# Issue #358 repair — job 4c1c8

## Frozen scope

- Issue: #358 only; branch `auto-358`, assigned worktree `/home/dev/Git/wt/auto-358`.
- Starting head: `9d645420ee10f45ccadd58e2418a0d808480d842` (verified); base: `cd5618223cbdd9ac55d40695987e09fd8b4ef184` (diff resolved).
- Worktree initially clean. Preserve all prior implementation and notes.
- Evidence snapshot: supplied `dispatch-context.json`, `check-0.log` through `check-7.log`, and prior result `5b9153165de24bf5a13dd613830a6d2c/result.json`; no GitHub mutation or refresh.
- Files under review: existing audit routes/query/bridge/stores, core audit persistence/protocols, AuditLog frontend and adjacent audit/e2e tests; integration-scope workflow/checker and vulture checker/ledger; relevant ADRs and inventory instructions. Change only evidence-backed issue repair files plus this report/inventory note if needed.

## Initial evidence and assumptions

- Driver check-3 reports `test_pm_workflow_api.py:271`: expected 403 but got 200. Reproduce and inspect auth fixture before deciding whether production or test is wrong.
- Driver check-4: 76 focused backend tests passed; inventory checks for backend/core pass. `packages/hive-conductor/tests` has no suite recipe (check-6), not evidence of failing product behavior.
- Prior result reports missing integration evidence, unauthorized retained vulture identities, retention gap, unbounded memory fallback, and unverified browser runtime. These are claims to revalidate, not permission to weaken gates or create grants.
- Ambiguity: integration-scope is an evidence aggregator, not necessarily a source defect. Inspect its actual required evidence and reproduce locally; never fabricate successful producer evidence.

## Progress

Snapshot recorded. Exact vulture scan failed (job `repair-vulture.log`); integration-scope failed closed without producer results (`repair-integration-scope.log`); its 12 local contract tests passed (`repair-integration-tests.log`). No gate changes justified. ADR-068/073 require existing Sentinel authority and admin-only canonical decision audit; pagination must not introduce a personal-read exception for that authority. ADR-062's retired graph entrypoint is not an execution authority; this repair does not touch execution.

Source inspection found a reachable scope discrepancy worth testing: `routes/audit.py:get_entry` reads the legacy replica directly after `_actor_scope`, whereas list/export call `_authorized_core_audit` before I/O. A non-admin denied canonical list/export can still read the mirrored legacy detail by known ID. Confirmed with the existing real Container/convergence fixture: new `test_core_detail_cannot_bypass_admin_scope_via_legacy_replica` fails at its 403 assertion with actual HTTP 200 (`repair-detail-before.log`, 1 failed). It first verifies the marker was written into both stores. Repair applies the existing `_authorized_core_audit` guard before legacy lookup; no new authorization path. The regression additionally forbids all legacy lookups for denied known/missing IDs. One-test inventory delta recorded.

## Validation checkpoint

- After the guard: 77 focused Hive audit tests passed, including the new regression and the PM audit assertion against both real in-process production authority bindings. This does not prove the driver's external `localhost:8101` target is this branch; no shared service was changed and its failing result was not excused by changing expectations.
- Core audit/scope suite: 45 passed, 4 skipped (PostgreSQL audit cases have no test DSN). Current PostgreSQL execution remains UNVERIFIED, not inherited from prior reports.
- Real million-row SQLite datasets: legacy index build 12.433s, first page 0.0009s, scoped page 0.0005s, maximum query work <2,800 VM instructions; canonical load 12.540s, maximum query work 3,400 VM instructions. These tests query real adapters with bounded-work assertions rather than machine-speed pass criteria.
- `uv run ruff check .` and `uv run ruff format --check .`: passed.
- Backend inventory passed with +1 test; e2e inventory passed using its actual recipe `packages/hive-conductor/tests/e2e`.
- Captured remote producer checks are for SHA `37723b88534a`, not the assigned head. Their successes cannot satisfy current-head integration-scope. No current-head producer evidence is supplied. UNRESOLVED external prerequisite; no further remote investigation.
- Exact Vulture scan sees 1,342 identities versus 1,338 trusted-base entries. The four live `get_page` definitions are already present in the candidate ledger at lines 1001/1010/1072/1171; `audit_bridge.py:185` calls them. Deleting them breaks production pagination, adding duplicate identities corrupts the multiset, and changing a grant is prohibited. No ledger amendment is warranted: the gate explicitly requires a separately approved trusted-base grant.

## Acceptance disposition (this run only)

1. **Bounded cursor pagination, stable ordering, maximum page size:** executed Hive/core tests pass for legacy memory/SQLite and canonical memory/SQLite. PostgreSQL runtime is UNVERIFIED (4 skipped audit cases); its query-shape test passed.
2. **Authorization/scope before database pagination:** real SQLite scope/filter tests pass; the new detail bypass regression failed before repair and passes after using the existing admin guard. No competing authorization authority was introduced. Canonical decision audit remains admin-only, reconciling personal legacy reads with ADR-073.
3. **Incremental loading and virtualization:** source reviewed (`AuditLog.tsx`, 100-row requests, visible-row slicing, stale-generation guards). Browser runtime UNVERIFIED in this run; no historical browser success is adopted.
4. **Filters, export, retention without browser corpus loading:** filtered/capped streaming export tests pass; UI uses a download link rather than storing export rows. Actual retention remains NOT MET: `audit_query.py:79` declares `corpus_purge=none`; no purge mechanism was added, and related issue #325 is not acceptance evidence.
5. **Measured representative large datasets:** executed million-row SQLite tests on both durable schemas, with <2,800 / 3,400 VM-instruction bounds. PostgreSQL large-data measurement UNVERIFIED this run.
6. **Concurrent inserts, cursor stability, scope isolation, maximum limit, empty pages, million-row envelope:** 122 focused audit/scope tests passed (77 Hive + 45 core); 4 PostgreSQL cases skipped, so all-backend coverage is not claimed.
7. **Corpus-independent initial page cost:** met by the measured indexed SQLite queries, NOT MET for the reachable memory fallback. Fresh production `page_entries` probe with `limit=1` visits 100/100 and 10,000/10,000 entries (`repair-memory-envelope.log`). `InMemoryAuditLog.get_page` also enumerates all entries. This run does not disguise a result-size bound as a work bound.
8. **Bounded browser memory/DOM:** source caps retained rows at 500 and windows mounted rows; browser runtime UNVERIFIED. Record-count bounds also are not proof of an absolute byte bound for arbitrary entry payloads.

The detail authorization repair does not implement canonical `core-*` detail lookup: the existing admin detail route still reads legacy IDs, while the frontend modal uses the already-paged payload. That limitation and the broader retention/memory issues are preserved, not silently claimed fixed.

## Commands and outcomes

Logs live in `/home/dev/maistro/jobs/4c1c8d52664746ef8a1ded2548d9ff03/`.

```sh
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
# exit 1: four retained/live identities need trusted-base authorization.
uv run python scripts/check-integration-scope.py --event-name pull_request
# exit 1: missing nine current-head producer results; no fabricated --result inputs.
node --test tests/ci/integration-scope.test.cjs
# exit 0: 12 tests, validates aggregator contracts, not producer execution.
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py::test_core_detail_cannot_bypass_admin_scope_via_legacy_replica -x -q
# BEFORE fix: 1 failed, observed 200 instead of 403.
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s
# AFTER fix: 77 passed, including regression and both PM authority contracts.
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s
# 45 passed, 4 skipped (PostgreSQL audit DSN absent).
uv run ruff check .
uv run ruff format --check .
# both exit 0.
uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests
# exit 0: 3,393 tests (one-test delta).
uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/tests/e2e
# exit 0: 23 tests; corrects the driver's unsupported suite path, not its product failure.
git diff --check
# exit 0.
```

Also executed a foreground `uv run python` probe importing production
`services.audit_query.page_entries` with a counting dict; one returned row
required a full scan at both corpus sizes. Retention metadata still reports
`corpus_purge=none`. A JSON evidence extraction initially encountered a nullable
GitHub check summary (`TypeError`); null-safe extraction succeeded, revealing
only old-head producer evidence. No GitHub requests or mutations were made.

## Handoff

Changed files: `packages/hive-conductor/backend/routes/audit.py`,
`packages/hive-conductor/backend/tests/test_audit_convergence.py`,
`docs/testing/inventory-notes/358-4c1c8-detail-scope.md`, and this report.

**BLOCKED**, not merge-ready. The reproduced detail-read authorization bypass
is repaired and validated, but current-head integration evidence and trusted-base
Vulture authorization cannot be manufactured in this lane. Acceptance also has
real retention/memory gaps and browser/PostgreSQL validation gaps. No grant,
ledger, workflow, scheduler, event authority, Goal store, or gate changes made.

Progress: checked 1 issue, completed 1 focused repair, skipped 0 issues,
2 unresolved gate failures. Next: obtain reviewed trusted-base authorization,
run producers on this exact branch-built candidate (not a shared foreign service),
and resolve the explicitly unmet acceptance before another readiness claim.
No background services or subagents were started. All changes committed locally
for handoff; no push or integration approval.

