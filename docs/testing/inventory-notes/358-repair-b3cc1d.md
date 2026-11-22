---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue #358 repair — b3cc1d

## Frozen scope

One issue: #358. Assigned worktree `/home/dev/Git/wt/auto-358`, branch
`auto-358`, clean starting HEAD `f0c00a54f35dba719b36e8420dabc741b2a4d1d9`,
develop base `15157c6f2bc57d5f7dc7d9e212adb323864d32ef` (both resolve).
Candidate repair files: existing audit query/routes/bridge, core audit page
adapters, AuditLog frontend, adjacent pagination/convergence/PM tests, the
explicitly permitted vulture ledger, and this validation note. No other issue
or authority is in scope.

## Initial evidence

Read all eight supplied check logs and prior result artifact. Driver check-3
fails at `test_pm_workflow_api.py:271`: configured engine expected 403 but
localhost service returns 200 and an obsolete bare-array response. Check-6
uses an unsupported inventory suite (`packages/hive-conductor/tests`). The
other supplied checks pass; these claims will not substitute for fresh runs.
No merge conflict or incoming uncommitted work exists. Integration-scope
producer evidence is not supplied: assume local missing evidence cannot be
repaired by fabricating CI conclusions. Prior note says vulture identities
are already banked; run the exact gate before deciding whether a ledger edit
is warranted. No test-count change yet.

## Fresh results

- Read repository CLAUDE.md and accepted ADR-068, ADR-073, and
  ADR-081226-69ee. Canonical decision audit remains admin-only; legacy
  own-actor scope is not a replacement authorization path. No execution
  spine or authority changes are warranted by the supplied gate evidence.
- Exact requested vulture command exits 1: 1363 findings versus 1359
  trusted identities. All four `get_page` identities are already present
  in the candidate ledger. The actual failure is missing authorization
  from trusted base `5765efce8c1f`, not an unbanked candidate identity.
  Retained methods are used by the production audit bridge outside the
  scanner roots; deleting them would break canonical pages/export. No
  duplicate ledger rows or grants will be added to disguise this failure.
- `uv run ruff check .`: pass. `uv run ruff format --check .`: pass,
  2775 files.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py -x -q`:
  **58 passed** in 17.43s, including the real PM assertion in both authority
  modes and authorization-before-query checks.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: **8 passed, 4 skipped** in 10.67s. Actual million-row SQLite
  canonical query maximum: **3400 VM instructions**, load 9.044s. Skipped
  PostgreSQL cases require MAISTRO_TEST_PG_DSN.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  fails, nine producer results missing (docker-build, durable-events,
  hive-conductor-e2e, hive-conductor-e2e-ui, MinIO, pg17, pg18, strike-ladder,
  wheel-imports). This is an evidence aggregator; no producer conclusion
  is available in the supplied logs. Do not fabricate success inputs.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format
  '{{.ServerVersion}}'`: fails, cannot connect to daemon. No shared service
  was reconfigured or replaced. PostgreSQL execution remains UNVERIFIED.
- Fresh exact driver pytest command (PM agent, PM workflow API, core audit
  pages, `-q -x`) reproduces `test_pm_workflow_api.py:271`: **1 failed,
  7 passed, 13 skipped**. External localhost:8101 returns a bare array of
  four entries for limit=1, while health selects canonical authority and
  the expected response is 403. This is not the response of this worktree's
  passing real-route regressions. External service provenance remains
  UNRESOLVED; no assertion was loosened to accommodate it. The test performs
  its usual login operations; it does not rebuild or replace the service.
- Initial inventory runs exposed an invalid empty inline front-matter map
  in this new note. Corrected it to explicit zero deltas. Fresh reruns of
  `check-suite-inventory.py --suite packages/hive-conductor/backend/tests`
  and `--suite packages/maistro-core/tests` both pass: 3303 and 12141 tests,
  respectively. `git diff --check` passes.

## Acceptance review

| Criterion | Fresh evidence / limits |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum size | Backend 58/core 8 passed; route delegates to bound core `get_page`, clamps to 200, uses timestamp/row-ID keysets; legacy durable query uses individually bounded seeks. External service does not expose this contract. |
| Authorization/scope before database pagination | Real canonical 403-before-query regressions and durable scoped SQL tests pass. ADR-073 admin-only decision audit preserved; legacy own-actor scope not widened. |
| Incremental frontend loading and virtualization | `AuditLog.tsx` inspected: 100-row requests, 500 retained entries, 44px windowed rows. Actual browser execution **UNVERIFIED** this round. |
| Filters/export/retention without browser corpus loading | Passing tests cover filters and bounded streamed export. Native download link inspected. Retention endpoint explicitly reports `corpus_purge: none`; actual retention/purge absent (#325), so broad retention acceptance is **UNVERIFIED**, not silently counted complete. |
| Representative query/index measurements | Both SQLite million-row tests pass; canonical maximum 3400 VM instructions across 16 filter/cursor combinations. PostgreSQL **UNVERIFIED** (no available daemon/DSN). |
| Concurrent inserts, cursor stability, isolation, limits, empty pages, million-row envelope | Executed focused backend/core suites cover these on SQLite and memory; four PostgreSQL cases skipped. |
| Initial-page cost independent of corpus size | Durable SQLite actual-query bounds pass; in-memory path still snapshots/sorts the corpus (`audit_query.py`), so universal acceptance is not proven. |
| Bounded browser memory/DOM | Source caps row state and rendered window; runtime verification **UNVERIFIED**. |

## Handoff

No evidence supports a production or test-assertion change for the named gate
failures. Candidate ledger already contains exactly the four retained adapter
identities: further amendment cannot provide trusted-base authorization. No
grant, duplicate ledger entry, fake producer conclusion, or gate weakening was
introduced. Only this validation note changed; zero test additions.

Blocked next steps: provide the authorized trusted-base prerequisite, producer
failure logs/results for integration-scope, and a reachable candidate-built
service plus browser/PostgreSQL environment. Reconcile retention and ephemeral
performance acceptance with the issue owner before any completion claim.

Progress: checked 1, done 0, skipped 0, errors 3 (vulture authorization,
integration evidence, incompatible external E2E service). No GitHub mutations.
