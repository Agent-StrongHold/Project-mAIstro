---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue 358 — repair d50a

## Frozen scope

One item: #358, assigned worktree `/home/dev/Git/wt/auto-358`, branch
`auto-358`, clean starting HEAD `01c3494629d1e98363ecb6828b9284549c72fa1d`,
base `cf4a562b65e0f459eec8e77e8b10ca7aa4f847d0` (both resolved).
Inputs: supplied check-0 through check-7 logs, prior 591c result/note,
repository instructions, ADR-068/073/081226-a66b, existing audit routes,
query/bridge/stores, core pagination adapters/protocol, migration 051,
AuditLog frontend, adjacent audit/PM tests, integration-scope and vulture
scripts/workflows and their tests. Only evidence-supported changes within this
snapshot, plus this note. No uncommitted incoming work or sync conflict.

Initial result: supplied check-3 received an unpaginated list from an external
service reporting MaistroCoreBridge, inconsistent with candidate contract.
Deployment revision is unknown; do not relax the assertion. Check-6 names a
suite without an inventory recipe. Named integration-scope failure lacks
producer conclusions; assumption: inspect gate and record missing evidence,
never fabricate successful inputs. Prior validation claims are not proof.

## Fresh validation

- Requested exact vulture gate: **failed**, 1364 findings, zero unclassified;
  four retained `get_page` identities are already banked but unauthorized against
  trusted base `045cfdfbe3ea`. `/tmp/358-d50a-vulture.log` explicitly requires a
  reviewed grant landed first. No duplicate ledger rows or scanner workarounds.
- Four-file backend audit suite (`test_audit_convergence`, `test_audit_pagination`,
  `test_audit_routes`, `test_noop_route_contracts`, `uv run pytest ... -q -x -s`):
  **76 passed** in 20.12s. Million-row SQLite index startup 9.634s, first page
  0.0007s, scoped page 0.0004s, maximum query work <2800 VM instructions.
  Log: `/tmp/358-d50a-backend.log`.
- Read repository instructions and ADR-068, ADR-073, ADR-081226-a66b. Admin-only
  Sentinel decisions take precedence over any interpretation of personal audit
  access. No alternate authority or lifecycle is introduced.
- `uv run python scripts/check-integration-scope.py --event-name merge_group`:
  **failed**, nine missing producer conclusions. `/tmp/358-d50a-integration.log`.
  This proves fail-closed behavior, not the cause of the remote failure.
  `node --test tests/ci/integration-scope.test.cjs`: **8 passed**. Exact-candidate
  remote producer evidence is UNRESOLVED; no guessed refs or forged results.
- Core `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: **8 passed, 4 skipped**, 9.90s; million-row SQLite load 8.221s,
  maximum query work 3400 VM instructions. `/tmp/358-d50a-core.log`.
  PostgreSQL DSN absent. Existing Docker services belong to other lanes;
  the fixture truncates tables, so they were not reused.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  2811 files.

## Reviewed gate disposition

The permitted candidate ledger amendment is already present at
`quality/vulture-baseline.json:1019,1028,1090,1189`. The four APIs are called
through the canonical `AuditLog` protocol by
`packages/hive-conductor/backend/services/audit_bridge.py:188`, outside the
scanner roots; they are not dead code. The current scan has zero unclassified
identities, so no additional amendment is justified. A local ledger edit cannot
supply the trusted-base authorization the gate demands. No grant/gate edits,
removal of live methods, or artificial scan-visible calls were made.

No develop-sync conflict exists. The driver check-3 response is not accepted as
candidate behavior: candidate routes enforce admin-only canonical reads before
I/O and return an envelope, exercised in the passing convergence suite. Its
external service revision remains unknown. Do not accept either status code
opportunistically or update expected data to the old unpaginated shape.

## Remaining validation and acceptance

- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: passed, 3340 tests. Same command for
  `packages/maistro-core/tests`: passed, 12249 tests. No tests added; delta zero.
  Driver check-6's `packages/hive-conductor/tests` is not a registered recipe.
- `uv run python scripts/check-api-route-contracts.py`: passed, 281 handlers,
  15 audited routes, zero canned.
- In `packages/hive-conductor/frontend`, `node_modules/.bin/tsc -p
  tsconfig.json --noEmit` and `node_modules/.bin/tsc -p tsconfig.node.json
  --noEmit`: passed. Browser execution remains UNVERIFIED; this is not a
  substitute for Playwright.
- `git diff --check`: passed.

| Criterion | Executed evidence / limitation |
| --- | --- |
| Bounded cursor pagination, stable order, maximum page size | 76 backend and 8 core tests passed on candidate source; maximum 200, stable timestamp plus row identity. PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before database pagination | Candidate route/convergence tests and real SQLite adapter tests passed; canonical access refused before I/O, SQL scope/filter predicates before LIMIT. |
| Incremental loading and virtualization | Production component and existing Playwright tests inspected; typecheck passed. Browser runtime UNVERIFIED. |
| Filters, export, retention without browser corpus loading | Backend tests prove scoped filtered pages and capped streaming NDJSON export. Native browser download link inspected. Operational retention UNVERIFIED: `audit_query.py:85` declares no purge, owned by #325. |
| Representative large dataset query/index measurement | Two real million-row SQLite suites passed, <2800 legacy / 3400 canonical VM instructions. PostgreSQL million-row leg skipped, UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, maximum limit, empty pages, million-row envelope tests | Executed backend and core suites cover these cases, including acknowledged concurrent writes and timestamp ties; four PostgreSQL cases skipped. |
| Initial page cost independent of corpus size | SQLite request work proven after startup index construction. Not met in all reachable modes: `audit_query.py:386` copies/sorts the in-memory corpus; `security/sentinel/audit.py:59` scans entries. |
| Bounded browser memory and DOM rows | Source caps retained rows at 500 and virtualizes viewport; runtime/heap UNVERIFIED. Row counts alone do not bound arbitrarily large entry payloads. |

## Handoff

**BLOCKED**, not a completed repair or integration approval. Only this evidence
note changed. Preserve the existing production changes and candidate ledger;
there is no evidence-supported CI repair available from the supplied inputs.
Required next inputs: reviewed trusted-base authorization for four retained
pagination APIs, exact-candidate integration producer conclusions/logs, and
revision evidence for the externally tested service. No remote mutations,
conflict resolution, or changes to gates/authorization were performed.

Progress: checked 1, done 0, skipped 0, errors 2 (named gates); next: supply the
missing authorization and producer evidence, then address the documented
product acceptance gaps rather than repeat an identical blocked round.
