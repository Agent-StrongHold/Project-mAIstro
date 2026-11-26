---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/hive-conductor/tests/e2e: 0
  packages/maistro-core/tests: 0
---

# Issue 358 repair — 5dd739

## Frozen scope and initial evidence

Assigned issue #358 only, worktree `/home/dev/Git/wt/auto-358`, branch
`auto-358`. Clean starting HEAD `3a9865527991a56c4ba1487079de3bddb1e9f8fd`;
resolved supplied base `35f2e0158a9138e592b56ed84bd08aa2e04c92a4`.
Process only the supplied issue and its existing audit implementation, adjacent
tests, relevant ADRs, integration-scope and exact Vulture gates. Candidate edits:
this note, existing audit production/test files if evidence supports a repair,
and `quality/vulture-baseline.json` for actual reviewed findings. No grant edits.

Read driver check-0 through check-7 and the supplied prior result. Driver check-3
fails at `test_pm_workflow_api.py:271`: expected canonical admin refusal, received
200 and an unpaginated legacy array. Check-6 requests an unregistered suite parent.
Neither finding justifies weakening assertions. Prior verification claims remain
untrusted until independently checked. Integration-scope producer outcomes were
not supplied; inspect the gate before deciding whether a local repair is possible.

## Named gates: fresh evidence

- Exact requested Vulture command failed: 1343 findings versus 1339 trusted
  identities at the supplied base. Four `get_page` identities are unauthorized
  (PgAuditLog, SqliteAuditLog, AuditLog protocol, InMemoryAuditLog). The live
  production caller is `backend/services/audit_bridge.py:186`. Candidate banking
  cannot supply trusted-base authorization; do not rename/remove live APIs to
  evade the scanner. Log: `/tmp/358-5dd739-vulture.log`.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`
  failed with nine missing outcomes. Aggregator unit checks, `node --test
  tests/ci/integration-scope.test.cjs`, passed all 12. This is not producer proof.
- Read-only check-run snapshot for the resolved starting HEAD retrieved once:
  integration-scope job **111545729802**, run **37239694548**, failed; seven
  specialized producer jobs skipped, PostgreSQL's unexpanded matrix job skipped;
  lint-and-type-check and workflow-lint failed upstream. Fetch only the assigned
  gate logs from this snapshot; do not broaden into unrelated failed checks.
- Remote integration-scope log confirms the actual failure at 22:21:58 UTC:
  `docker-build is required by integration scope but concluded skipped`.
  `.github/workflows/ci.yml:884` makes docker-build depend on workflow-lint.
  The frozen snapshot's workflow-lint job **111545730476** failed during tool
  download: four HTTP **500** responses, then tar extraction exit 2, before
  lint execution. Log: `/tmp/358-5dd739-workflow-lint.log:424-431`. This is an
  upstream download failure, not evidence of a broken audit implementation or
  aggregator. No workflow/gate weakening is justified. No remote rerun requested.
- Remote exact-debt-ledger job **111545729974** matches the local Vulture
  failure, with the same supplied trusted base. Candidate ledger already retains
  all four identities at `quality/vulture-baseline.json:1002,1011,1073,1172`.
  No missing candidate identities or genuinely dead methods were found, so no
  duplicate ledger rows were added. The required trusted-base grant cannot be
  manufactured by an implementation branch or another candidate amendment.
- Read accepted ADR-073 and audit route/bridge. Canonical decision reads remain
  admin-only; personal legacy scope cannot override this accepted ADR. No
  execution, Goal, event or authorization authority is changed.

## Focused acceptance validation

Fresh commands in the assigned checkout (long timeouts):

- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **76 passed**, 26.88s. `/tmp/358-5dd739-backend.log`.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py
  -x -q -s`: **45 passed, 4 skipped**, 15.50s. PostgreSQL DSN absent; its cases
  are not verified. `/tmp/358-5dd739-core.log`.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  2913 files.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e
  --suite packages/maistro-core/tests`: passed, counts 3385 / 23 / 13064.
  The driver's parent suite path has no recipe; the existing registered e2e
  path succeeds. No tests added/removed and no baseline edits needed.
- Read-only HTTP probe of the e2e fixture's resolved target,
  `http://localhost:8101/openapi.json`: HTTP 200, audit GET exposes only
  action/severity/actor parameters and an array response; export and retention
  routes absent. This cannot validate the candidate's bounded API. Shared
  service was not restarted or changed, and legacy responses were not accepted
  as passing candidate assertions.
- Browser config lookup at `packages/hive-conductor/tests/playwright.config.ts`:
  not found; skipped. No browser execution claimed.

Acceptance against reachable production code and tests:

1. **Bounded cursor pagination/stable order/maximum page size:** focused route
   and real-adapter tests passed (200-row ceiling, tie-breaking, continuation,
   malformed cursors, empty pages). Bound canonical authority is read through
   `audit_bridge.py:186`, not an in-memory list-and-slice replacement.
2. **Authorization/scope before DB pagination:** focused SQL and convergence
   tests passed; query predicates precede limits and canonical non-admin reads
   are denied before I/O. ADR-073 reconciliation remains admin-only Sentinel
   reads versus personal scope only in the unbound legacy fallback.
3. **Incremental loading/virtualization:** inspected `frontend/src/pages/AuditLog.tsx`:
   100-row requests, 500-row retained window, viewport slice plus overscan.
   Fresh browser execution **UNVERIFIED**.
4. **Filters/export/retention without browser corpus loading:** backend tests
   pass scoped filtering and capped NDJSON streaming. UI export uses a download
   link, not a whole-corpus JS fetch. Browser download **UNVERIFIED**. Retention
   metadata is constant-sized but `services/audit_query.py:79` explicitly states
   no corpus purge; operational retention is **UNVERIFIED**, owned by #325.
5. **Representative large-dataset query/index measurements:** both real
   million-row SQLite envelopes passed. Legacy index migration 12.195s;
   initial page 0.0008s, scoped page 0.0004s, maximum measured VM work <2800.
   Canonical million-row load 12.198s, maximum VM work 3400 across filter/deep
   cursor shapes. PostgreSQL envelope **UNVERIFIED** (skipped).
6. **Concurrent inserts/cursor stability/scope isolation/maximum/empty/million
   rows:** covered by 121 passing focused tests, including acknowledged
   threaded writes and duplicate request IDs. PostgreSQL variants skipped.
7. **Corpus-independent initial cost:** durable SQLite seeks measured after
   startup indexing. Universal claim fails: `services/audit_query.py:386-403`
   snapshots and sorts the entire in-memory corpus per page; this is explicitly
   documented, not a proven bounded path.
8. **Bounded browser memory/DOM:** row caps inspected; executed browser evidence
   **UNVERIFIED**. A row-count cap also does not bound arbitrary payload bytes.

## Blocked handoff

Only this evidence/inventory note changed; no code repair is claimed. Actual
integration-scope cause is now identified: upstream workflow-lint download HTTP
500, followed by required producer skips. Do not patch the aggregator to accept
skips. Exact Vulture remains blocked on authorization of four retained live APIs
in the trusted base, not on absent candidate ledger rows. No grant, gate, live
API or test assertion was altered to force success.

Next: campaign owner handles the trusted-base grant and CI infrastructure rerun;
provide an isolated candidate-built service for end-to-end/browser validation.
Retention and in-memory initial-cost acceptance gaps remain independently of CI.
No GitHub mutations, pushes, resets, cleanup or destructive operations performed.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; blocked 1. All existing
implementation preserved. This note is committed locally for handoff, not
integration approval.
