---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue 358 — repair 591c

## Frozen scope

Single assigned item: #358 in `/home/dev/Git/wt/auto-358`, branch `auto-358`.
Verified clean starting HEAD `da6b6b93154141803bf8631c21eeb64c4f5f5ab0`;
supplied base `cf4a562b65e0f459eec8e77e8b10ca7aa4f847d0`.
Frozen inputs: supplied job check-0 through check-7 logs, prior f53a result,
repository instructions and relevant audit ADRs, the existing #358 audit
routes/query/bridge/stores, core audit adapters/protocol, frontend AuditLog,
adjacent pagination and PM tests, migration 051, and integration-scope/vulture
gate definitions. Changes restricted to evidence-supported repairs within this
scope and this note. No remote mutations or speculative develop merge.

Initial inspection: check-3 receives an unpaginated list from an external
service reporting MaistroCoreBridge, where candidate audit routes require admin
and return an envelope. Its deployed revision is unknown; do not assume this
is candidate behavior. check-6 names a suite with no inventory collection
recipe. Prior gate failures and acceptance claims will be freshly checked.
No merge conflict or incoming uncommitted work is present.

Ambiguity: exact merge-queue producer conclusions are not supplied. Local gate
invocation without those inputs can demonstrate fail-closed behavior, not
identify the remote failed producer. No guessed run IDs or refs will be used.

## Validation

- `uv sync --locked --extra dev`: passed.
- Exact requested vulture command: failed (exit 1); 1364 findings, zero
  unclassified; four `get_page` APIs already banked in the candidate are new
  against trusted base `045cfdfbe3ea`. Gate explicitly requires a reviewed grant
  landed first. Log: `/tmp/358-591c-vulture.log`. No candidate amendment can
  supply trusted-base authorization; do not duplicate ledger identities.
- `uv run python scripts/check-integration-scope.py --event-name merge_group`:
  failed (exit 1) without producer conclusions, as required. Log:
  `/tmp/358-591c-integration.log`. Remote failure cause remains UNRESOLVED;
  no exact-candidate producer evidence supplied. This is not a gate defect.
- Focused four-file backend audit suite: exit 0, log
  `/tmp/358-591c-backend.log`.
- Core `tests/persistence/test_audit_pages.py -x -q -s`: exit 0, log
  `/tmp/358-591c-core.log`; database leg availability to be recorded below.
- `uv run ruff check .` and `uv run ruff format --check .`: passed (2811 files).
- Read ADR-068, ADR-073, ADR-081226-a66b. Canonical Sentinel decisions remain
  admin-only; scoped personal legacy records are not an alternative decision
  authority. No authorization or Goal -> Graph -> Run -> NodeRun -> Attempt
  lifecycle changes are justified by the supplied failures.
- Backend result: **76 passed**, 23.51s. Legacy SQLite million-row startup
  index migration 10.850s; initial page 0.0007s; scoped page 0.0004s;
  maximum measured query work <2800 VM instructions.
- Core result: **8 passed, 4 skipped**, 10.40s. Canonical SQLite million-row
  load 8.796s; maximum query work 3400 VM instructions. PostgreSQL DSN absent;
  its four runtime legs remain UNVERIFIED.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: passed (3340); same command for
  `packages/maistro-core/tests`: passed (12249). Driver check-6's
  `packages/hive-conductor/tests` has no collection recipe, not a count drift.
- `uv run python scripts/check-api-route-contracts.py`: passed (281 handlers,
  15 audited routes, zero canned).
- `node --test tests/ci/integration-scope.test.cjs`: 8 passed. These unit
  checks do not replace exact-candidate producer conclusions.
- `git diff --check`: passed.

## Acceptance evidence

| Criterion | Fresh evidence and limits |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum page size | Passing backend/core suites execute candidate routes and SQLite/memory adapters; maximum 200, timestamp plus immutable identity ordering. PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before database pagination | Passing route tests reject non-admin canonical reads before query; SQLite tests execute scope and equality filters before LIMIT. `services/audit_bridge.py:188` calls the canonical protocol, with explicit system org scope. |
| Incremental loading and virtualization | `frontend/src/pages/AuditLog.tsx` inspected: cursor fetches of 100, sliding 500-entry window, viewport slice. Browser execution UNVERIFIED this round. |
| Filters, export, retention without loading whole corpus into browser | Passing tests cover database filters and capped NDJSON export. Frontend uses a native download link. Operational retention UNVERIFIED: `audit_query.py:85` declares `corpus_purge: none`; #325 owns the missing purge, not a completion exemption. |
| Representative large query/index measurement | Real million-row SQLite measurements above; tests interrupt excessive VM work rather than relying only on elapsed time. PostgreSQL UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, max limit, empty pages, million-row envelope | 76 backend and 8 core tests passed, including acknowledged concurrent writes, deep timestamp ties and repeated request IDs. Four PostgreSQL legs skipped. |
| Initial page cost independent of total corpus | SQLite request work bounded after startup indexing. Not met for all reachable modes: `audit_query.py:386` copies/sorts the in-memory corpus; `security/sentinel/audit.py:59` scans its list. |
| Browser memory and DOM row count bounded | Source has a 500-entry cap and viewport rendering; runtime/heap UNVERIFIED. Entry payload size is not bounded by row count. |

## Disposition and required next inputs

**BLOCKED**; validation/handoff only, not a repair or integration approval.
Only this note changed; no tests added, inventory delta zero. No production,
ledger, grant or gate changes were made. The existing permitted ledger amendment
is preserved: the four retained APIs already occur at
`quality/vulture-baseline.json:1019,1028,1090,1189`. They are reachable through
`backend/services/audit_bridge.py:188` outside the scanner roots, not genuinely
dead code. Removing them or manufacturing scan-visible references would be
incorrect. Adding duplicate ledger rows cannot authorize them.

The external old-shape response does not justify accepting both authorization
outcomes. The existing candidate-local PM contract test exercises both actual
production authority bindings and passed within the 76-test suite. Its external
service revision remains unknown. The integration aggregator's remote failure
cannot be diagnosed from a bare conclusion without the producer logs.

Required next inputs: trusted-base reviewed authorization for the four retained
APIs, exact merge-queue candidate and failed producer logs, and deployment
revision evidence for the external PM service. Remaining product acceptance
work includes memory-adapter request complexity, browser/PostgreSQL execution,
and operational retention. Do not repeat this unchanged repair round or weaken
checks to conceal missing evidence. No fetch/merge was needed: no sync conflict
was present, and the supplied refs resolved.

Progress: checked 1, done 0, skipped 0, errors 2 (named gates); next: obtain the
missing trusted-base authorization and exact-candidate producer evidence.
