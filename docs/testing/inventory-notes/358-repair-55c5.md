---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue 358 — repair 55c5

## Frozen scope and initial evidence

Only issue #358, assigned worktree `/home/dev/Git/wt/auto-358`, starting head
`dd412635b06b49ce410ee2e3436e17959995e0d7`, supplied base
`4fd7801fb333611955dda962d11845aaf065277c` (both resolved). Incoming tree clean.
Process the supplied check-0 through check-7 logs, prior result artifact, named
vulture/integration-scope gates, and existing audit implementation/tests; no
other issues, grants, scheduler or authorization paths. Read repository
instructions and ADR-068/073; Sentinel decision audit remains admin-only.

Fresh named-gate execution:

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: FAIL. 1364 findings,
  zero unclassified, four new `get_page` identities against trusted baseline
  `045cfdfbe3ea` (PG/SQLite/protocol/memory). The candidate already banks these
  retained APIs. The gate requires trusted-base authorization, not another
  candidate ledger append. No grant edits or duplicate ledger rows.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  FAIL, nine required producer results missing. This command cannot manufacture
  exact-candidate CI producer conclusions; remote failure cause unresolved.
- Driver check-3: external service returns an unpaginated array/200 for a
  non-admin with MaistroCoreBridge health. Candidate contract requires 403.
  Assumption: deployed revision is unproven; do not weaken the security test.
- Driver check-6: `packages/hive-conductor/tests` has no collection recipe;
  invalid inventory command, not evidence of an inventory delta error.

## Validation checkpoint

- Exact-head GitHub check lookup (read-only) returned HTTP 422: no commit found
  for `dd412635b06b49ce410ee2e3436e17959995e0d7`. Remote checks not found;
  skipped further remote investigation. Integration failure cause UNRESOLVED.
- Focused backend suite (`test_audit_convergence.py`, `test_audit_pagination.py`,
  `test_audit_routes.py`, `test_noop_route_contracts.py`, `uv run pytest -x -q -s`):
  **76 passed** in 20.30s. Real legacy SQLite million-row startup index migration
  9.735s; first page 0.0007s; scoped page 0.0004s; maximum query VM work <2800.
  Includes external PM assertion against candidate production authority bindings.
  Output: `/tmp/358-55c5-backend.log`.
- UI source inspected: 100-row pages, at most 500 retained entries, virtualized
  row slice, server filters and native streaming download. No browser run yet;
  source is not runtime evidence. Package-root Playwright config not found;
  actual configs reside in `frontend/` and `tests/e2e/`.
- Core PostgreSQL tests truncate many scratch tables. Existing unrelated Docker
  services must not be reused for that validation. A dedicated scratch service
  is required; no changes to other workers' databases.

- Dedicated PG18 compose service `audit35855c5-postgres-1`: first startup failed
  because Docker's default address pools were exhausted. Retried with the
  existing default bridge (no new network), healthy. Used dynamically allocated
  loopback port, not another worker's database. `uv run alembic upgrade head`
  passed with dedicated DB_* variables (`/tmp/358-55c5-migrate.log`).
- `MAISTRO_TEST_PG_DSN=<dedicated scratch DB> uv run pytest
  packages/maistro-core/tests/persistence/test_audit_pages.py -x -q -s`:
  **12 passed, no skips**, 43.77s (`/tmp/358-55c5-core.log`). Canonical SQLite
  million-row load 8.690s, maximum VM work 3400. Canonical PostgreSQL million-row
  maximum query blocks **54** across all tested filter/cursor shapes, below 500.
  Concurrent inserts, tied timestamps/row IDs, exact scope before limit, maximum
  and minimum limits, empty pages, malformed cursors all executed on PG/SQLite/memory.

## Final checks

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2811 files).
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: passed (3340).
- Same inventory command for `packages/maistro-core/tests`: passed (12249).
- `uv run python scripts/check-api-route-contracts.py`: passed (281 handlers,
  15 audited routes, zero canned).
- `node --test tests/ci/integration-scope.test.cjs`: 8 passed. These prove
  aggregator behavior, not the missing CI producer conclusions.
- `git diff --check`: passed.
- Stopped the dedicated PostgreSQL container after validation; its scratch data
  is preserved. No existing service or database was modified.
- Ledger review confirmed existing retained entries at
  `quality/vulture-baseline.json:1019,1028,1090,1189`. The live call is
  `packages/hive-conductor/backend/services/audit_bridge.py:188`, outside the
  scanner's `packages/*/src` roots. No dead identity was found to remove, and
  no missing candidate identity was found to bank. Duplicating these rows does
  not repair trusted-base authorization.

## Acceptance accounting

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Bounded cursor pagination, stable ordering, max page size | 76 backend + 12 core tests pass, including 200-row ceiling and timestamp/row-ID ties. Production routes call bounded query adapters, not get_entries-and-slice. |
| Authorization/scope before DB pagination | Backend authorization-before-I/O tests pass for bound core audit (ADR-073 admin-only); real SQLite/PG tests verify exact scope/filter predicates before LIMIT. |
| Frontend incremental loading and virtualization | Source inspected, cursor loading and viewport slicing present. Browser runtime **UNVERIFIED** this round. |
| Filters, export and retention without browser corpus loading | Backend scoped filters and capped streaming export tests pass. UI native download inspected. Retention endpoint declares `corpus_purge: none`; operational retention purge **UNVERIFIED**, #325 coordination remains. |
| Query/index strategy measured on large datasets | Actual million-row legacy/canonical SQLite and PG18 queries executed; <2800 / 3400 VM instructions and 54 PG blocks respectively. Index construction occurs at startup/migration; its cost is not corpus-independent. PG17 **UNVERIFIED** this round. |
| Concurrent inserts, cursor stability, scope isolation, maximum limit, empty pages, million-row envelope | All executed and passing in focused suites; no PG18 skips. |
| Initial page cost independent of corpus size | Proven for tested indexed SQL paths after migration, **not met in all reachable modes**: `audit_query.py:386` sorts a full memory snapshot; canonical `security/sentinel/audit.py:59` scans its list. |
| Bounded browser memory/DOM | Source caps retained entries at 500 and mounts a viewport slice. Browser runtime/heap **UNVERIFIED**; entry count does not bound arbitrarily large individual detail payloads. |

## Disposition and handoff

**BLOCKED**, not merge-ready. This round closes the PostgreSQL evidence gap,
not the trusted-base grant or exact-candidate integration evidence gaps. No
source, tests, ledgers, grants, or workflow gates were changed. Only this note
is committed; inventory delta zero. Preserve canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` (ADR-081226-a66b read) and the
existing authorization/audit authorities. No GitHub mutations or speculative
sync were performed; no incoming conflict existed.

Next: provide the actual merge-queue candidate SHA and failing producer logs;
resolve retained-API authorization through the trusted-base process. Rebuild
and identify the external PM service before attributing its stale contract to
this candidate. Browser runtime, memory-mode cost, and operational retention
still prevent an all-criteria completion claim. Do not repeat this repair with
only the same missing-evidence inputs.

Progress: checked 1, done 0, skipped 0, errors 2 (named gates), next: trusted-base
and exact-candidate producer evidence. Local commit is a validation handoff,
not integration approval.
