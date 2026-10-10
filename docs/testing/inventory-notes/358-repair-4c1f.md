---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue #358 repair — job 4c1f

## Frozen scope

- Issue: #358 only; branch `auto-358`, starting HEAD
  `a0845cd434e7bc4409e75e8415396316c5960fc5`, supplied base
  `cf4a562b65e0f459eec8e77e8b10ca7aa4f847d0` (both resolved).
- Candidate implementation/test files: existing #358 diff (audit route, query,
  bridge, stores, core audit pagination adapters, frontend audit page, related
  tests and migration); permitted vulture ledger repair if evidenced by scan.
- Gate definitions and accepted ADRs are inspection-only. No changes to grants,
  authorization, execution authority, or integration gate semantics.
- Starting tree clean; no incoming uncommitted work to salvage.

## Initial evidence and assumptions

Read this job's check-0 through check-7 logs and the supplied previous result.
Driver lint/format and 76 backend tests pass; check-3 fails because the service
returns a legacy array where the test expects the canonical admin-only endpoint.
This is evidence of a service/code mismatch or implementation failure, not
permission to relax the assertion. Investigate against this checkout.
Check-6 uses an unsupported inventory suite (`packages/hive-conductor/tests`).
The previous result reports missing integration producer evidence and trusted-base
vulture authorization. Re-run the actual gates before drawing conclusions.

This is a writer repair lane. Missing remote CI conclusions cannot be fabricated;
any remaining evidence gaps must be reported rather than changing gate logic.

## Named gate results

- Exact requested vulture command ran (exit 1), log
  `/tmp/358-4c1f-vulture.log`: 1364 findings, zero unclassified identities.
  The four retained `get_page` methods already have ledger rows at
  `quality/vulture-baseline.json:1019,1028,1090,1189` and are actually invoked
  by `backend/services/audit_bridge.py:186`. The scanner's trusted base is
  `045cfdfbe3ea`; it requires a reviewed grant landed first. No justified
  additional ledger amendment exists: duplicating these rows cannot authorize
  debt. Do not remove live methods or manufacture scanner-visible usage.
- `uv run python scripts/check-integration-scope.py --event-name merge_group`
  exits 1 with all nine producer conclusions missing, log
  `/tmp/358-4c1f-integration.log`. No exact-candidate remote producer log was
  supplied. This is a fail-closed local evidence check, **not** proof of the
  remote failure's cause. Actual remote cause remains UNRESOLVED.
- `node --test tests/ci/integration-scope.test.cjs`: 8 passed. Gate behavior
  is not an evidenced defect and will not be changed.
- An initial ADR path lookup was not found; the actual ADR filenames were
  resolved from repository paths before further inspection. No Git refs were
  guessed or changed.

Both gate blockers recur from the prior round; no further investigation of
these ambiguities is planned without new producer evidence or a trusted grant.

## Fresh candidate validation

Read AGENTS.md, documentation authority hierarchy, ADR-068, ADR-073 and
ADR-081226-a66b, the route/query/bridge, core query and memory adapter,
frontend component, and adjacent pagination/convergence tests. ADR-073's
admin-only decision audit takes precedence over personal audit access when
Sentinel is bound. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and
existing authorities; this round changes none of them.

Commands executed (from the assigned worktree, with long timeouts):

- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: **8 passed, 4 skipped** (10.55s), log
  `/tmp/358-4c1f-core.log`. Million-row SQLite load 8.964s, maximum request
  work 3400 VM instructions. PostgreSQL DSN absent; skipped tests are not proof.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **76 passed** (22.39s), log `/tmp/358-4c1f-backend.log`. Million-row SQLite
  index migration 10.966s; initial page 0.0007s, scoped page 0.0004s;
  maximum query work <2800 VM instructions.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 2811 files.
- `uv run python scripts/check-api-route-contracts.py`: passed, 281 handlers,
  15 audited routes, zero canned handlers.
- Initial inventory checks rejected this new note's inline empty delta syntax;
  corrected it to the required indented suite block, both deltas zero.
  Re-ran `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: **passed, 3340**; same command for
  `packages/maistro-core/tests`: **passed, 12249**.
- `git diff --check`: passed.

## Acceptance evidence and residual gaps

| Criterion | Evidence / limitation |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum page size | Fresh backend/core suites pass, including tied timestamps, repeated request IDs and limit clamping (200 maximum). Candidate production route selects the core adapter when bound. PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before database pagination | Fresh convergence tests refuse non-admin canonical reads; adapter tests exercise actual SQL with org/user/filter constraints before LIMIT. Legacy scope isolation and scoped export pass. |
| Incremental loading and virtualization | `frontend/src/pages/AuditLog.tsx:45,263,354,446` contains the sliding 500-entry window, cursor loading and virtual row slice. Browser execution and heap/DOM measurements UNVERIFIED this round. |
| Filters, export, retention without browser corpus loading | Fresh backend tests pass filtered pages and capped NDJSON streaming; frontend uses a native download link. Operational retention UNVERIFIED: `backend/services/audit_query.py:85` explicitly declares no purge (#325). The metadata endpoint is not a retention implementation. |
| Representative large-dataset query/index strategy | Two real million-row SQLite suites pass the deterministic work envelopes above, including sparse filters and deep timestamp ties. PostgreSQL million-row envelope UNVERIFIED (skipped). |
| Concurrent inserts, cursor stability, scope isolation, maximum limit, empty pages, million-row tests | Fresh suites pass these named cases; concurrent acknowledged durable inserts are exercised, not merely query string assertions. PostgreSQL parameterizations skipped. |
| Initial page cost independent of total corpus | Proven for tested indexed SQLite requests after startup migration. **Not met in all reachable modes**: `backend/services/audit_query.py:386` snapshots/sorts the memory corpus; `maistro/security/sentinel/audit.py:59` scans its entries. |
| Bounded browser memory/DOM | Source retains at most 500 rows and mounts a viewport slice, but runtime UNVERIFIED. A row-count cap alone also does not bound arbitrary payload sizes. |

The driver's live-service check-3 is still a genuine failed check, not repaired:
`tests/e2e/test_pm_workflow_api.py:271` received HTTP 200 with a legacy array
from a service reporting MaistroCoreBridge. Fresh candidate convergence tests
return 403 for that role and a bounded envelope for an admin. The externally
served revision is unknown; do not infer its provenance or weaken the assertion.

## Disposition

**BLOCKED.** Only this evidence note is changed; no new tests or ledger changes
are justified by the supplied gate evidence. The four live API ledger rows are
already present. A reviewed trusted-base grant and exact-candidate integration
producer conclusions/logs are required before the named gate repair can proceed.
A candidate service deployment, browser/PG execution and resolution of the
memory-mode/retention acceptance gaps are also needed for a completion claim.
No remote mutations, integration approval, or issue closure performed.

Progress: checked 1, done 0, skipped 0, errors 2 (named gates still blocked).
Next: obtain new authorization/producer evidence; do not repeat this same
blocked round or fabricate a ledger-only fix.
