---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — c2f4f395

## Frozen scope and initial evidence

Only issue #358 in assigned worktree `/home/dev/Git/wt/auto-358`, branch
`auto-358`. Starting HEAD `6d1cb82c61509ce0ac87f6fb7df5bfdaa7d7c761`;
supplied base `00aafef9b75a1057edc2b03f2d6a71732ec9d880` resolves.
Initial worktree clean; no salvage required.

Frozen inspection/repair surface: repository instructions; ADR-037/073;
`.github/workflows/ci.yml`, integration scope and Vulture gate scripts;
`quality/vulture-baseline.json` (explicit repair exception only);
audit route/query/bridge, audit persistence/protocol implementations,
AuditLog frontend, adjacent audit backend/core/browser/live API tests;
and this evidence note. No other issues or unrelated branch changes will be
processed. No changes to execution, audit, or authorization authority.

Read supplied prior result and current job check-0 through check-7 logs.
Driver lint/format and 76 focused backend tests passed; check-3 failed at
`test_pm_workflow_api.py:271` (expected canonical 403, got unpaginated 200).
Check-6 requests a suite without an inventory collection recipe. Earlier
verification claims are not fresh acceptance evidence.

Ambiguity: logs do not identify the live server revision or the failing
integration producer. Treat these as unresolved environment/provenance
questions, not permission to relax contracts or invent passing CI results.
Reproduce the named gates and focused production-path tests before repair.

## Named gate checkpoint

Exact Vulture scan executed with 1,200s timeout: **exit 1**. Trusted base
`e067b7b0aca0` has 1,342 reviewed identities; candidate has 1,346 findings.
The four retained `get_page` methods require trusted-base authorization.
The gate explicitly says a candidate ledger update cannot authorize them.
This is not evidence of missing candidate rows or genuinely dead APIs.
No grant edit or manufactured caller will be used to bypass that restriction.

Read accepted ADR-037 and ADR-073. Indefinite audit event retention and
admin-only canonical decision audit override any conflicting interpretation
of the issue. No purge policy or alternative authorization path will be added.
Production `audit_query.py:402` still copies/sorts the memory corpus per page;
therefore corpus-independent initial cost is not met for that fallback.

## Fresh validation and repair decision

All validation commands used 1,200s timeouts.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: exit 1 as above. Candidate ledger already banks all four identities at lines 1004, 1013, 1075, 1174. Production caller `backend/services/audit_bridge.py:186` uses `audit_log.get_page`. These are retained APIs, not dead code. No justified ledger amendment remains; duplicating rows would corrupt the multiset rather than authorize it.
- `uv run python scripts/ci_merge_group_scope.py --json <frozen manifest surfaces>`: exit 0; requires PostgreSQL, Hive E2E, wheel imports, Docker build.
- `uv run python scripts/check-integration-scope.py --event-name merge_group --scope-json <classifier output>`: exit 1; six missing producer conclusions (pg17, pg18, Hive API/UI, wheel imports, Docker build). No invented `--result` values supplied. This establishes missing local evidence, NOT the cause of the unspecified remote integration failure. That cause remains UNRESOLVED.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`: **76 passed**, 19.27s.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py -x -q -s`: **8 passed, 4 skipped**, 9.93s. PostgreSQL tests skipped without `MAISTRO_TEST_PG_DSN`.

Measured legacy SQLite million-row index migration: 8.967s; first page:
0.0007s; scoped page: 0.0004s; maximum query VM instructions <2,800.
Canonical SQLite million-row load: 8.534s; maximum query VM work: 3,400.
Tests execute the production queries across scopes, filters, and deep cursors;
these deterministic work bounds do not depend on runner speed.

## Acceptance evidence and residual risks

| Criterion | Evidence this round |
| --- | --- |
| Bounded cursor pagination, stable order, maximum page | Executed route and adapter tests pass: max 200, timestamp/ID tie-breaking, continuation and malformed cursors. Driver live target returns incompatible unpaginated 200; its revision is UNVERIFIED. |
| Authorization/scope before database pagination | Executed denial-before-query and SQL scope/filter tests pass on SQLite. PostgreSQL runtime UNVERIFIED. Canonical decision audit remains admin-scoped per ADR-073. |
| Incremental loading and virtualization | `AuditLog.tsx` requests cursor pages and renders a viewport slice. Browser execution UNVERIFIED this round. |
| Filters/export/retention without browser corpus load | Executed server tests cover filters, scoped/capped NDJSON streaming, retention metadata. Frontend source uses native download, not corpus accumulation. Browser download UNVERIFIED. No purge is implemented; indefinite event retention follows ADR-037, policy lane #325. |
| Representative large-dataset query/index strategy | Both SQLite million-row tests executed; measurements above. PostgreSQL million-row envelope UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, maximum limit, empty pages, million-row tests | Executed backend/core tests pass, including acknowledged concurrent durable inserts. Four PostgreSQL cases skipped. |
| Initial page cost independent of corpus size | Measured SQLite indexed seeks after startup migration. NOT MET for memory fallback: per-page corpus copy/sort remains. |
| Bounded browser memory/DOM rows | Source caps retained entries at 500 and mounts viewport slice. Browser runtime UNVERIFIED. |

## Handoff

BLOCKED. Changed file: this evidence note only; no test inventory delta.
Required external inputs: trusted-base authorization for the four already
banked retained APIs; actual failed integration producer logs for this candidate;
and revision identity for the incompatible live API target. No local merge
conflict exists. Repeating an evidence-only repair or candidate ledger amendment
will not remove the trusted-base blocker. Do not relax tests or gates.

No unrelated branch diff was changed; no GitHub mutation, grant edit, or
alternative scheduler, audit authority, or authorization path was introduced.
Progress: checked 1 issue, done 0 repairs, skipped 0 issues, errors 2 named gate
validations; next: resolve the external authorization/evidence blockers.

Final validation: `uv run ruff check .` passed; `uv run ruff format --check .`
passed (2,878 files). Both `uv run python scripts/check-suite-inventory.py
--suite <suite>` checks passed: Hive backend 3,369; core 12,714.
`git diff --check` passed. Evidence note committed locally for handoff.
