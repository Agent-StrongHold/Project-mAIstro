# Issue 358 repair checkpoint (60d5)

Frozen scope: issue #358, PR #1712 evidence in the supplied dispatch snapshot;
worktree `/home/dev/Git/wt/auto-358`, starting head
`37723b88534a36c44446f78df0a97ba3ccd4b041`, supplied base
`94781cf6b708a385f33a9aafcbe9f83a481b6858`.
No remote mutation or re-enumeration. Starting worktree was clean.

Process only the named integration-scope/vulture failures and the observed audit
workflow test failure, plus focused acceptance validation. Candidate files are
existing audit pagination implementation/tests, workflow fixture, vulture ledger
(only if the executed gate identifies actual retained debt), and this report / a
matching inventory note if tests change. No scheduler or authority changes.

Initial evidence: driver check-3 fails in TestAuditTrail.test_audit_log_has_entries
(expected 403, actual 200); check-4 passes 76 audit backend tests; check-6 uses an
unsupported suite-inventory recipe. These claims will be rechecked locally.
The first dispatch summary script could not parse list-shaped check data; source
snapshot remains available for a bounded second inspection. Integration-scope
cause is not yet established; no develop sync is assumed necessary.

Exact Vulture scan executed: exit 1, 1,342 findings / 1,338 trusted-base
identities. The four `get_page` definitions have a real production caller in
`backend/services/audit_bridge.py:185`, outside the scanned src roots. Candidate
ledger already includes these reviewed retained APIs; failure explicitly says a
candidate amendment cannot authorize them. Do not duplicate rows or change grants.

Read ADR-062, ADR-068 and ADR-073: retain canonical execution and admin-only
Sentinel decision audit; the legacy personal trail is not permission to expose
canonical decisions. Reviewed route, query, bridge, frontend, convergence tests,
and million-row adapter tests. Memory fallbacks still scan/sort the corpus;
retention explicitly declares no purge (#325). These remain acceptance gaps,
not reasons to weaken CI or silently claim completion.

Validation checkpoint:
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2,922 files).
- Focused Hive audit convergence/pagination/routes/noop suite: 76 passed (25.11s).
  Million-row legacy index migration 11.967s; first page 0.0008s; scoped page
  0.0004s; maximum query work <2,800 VM instructions.
- Core audit pages + scope-conformance suite: 45 passed, 4 PostgreSQL cases
  skipped (no DSN); SQLite million-row load 10.699s; maximum query work 3,400 VM
  instructions.
- Correct inventory recipe `--suite packages/hive-conductor/tests/e2e`: passed,
  23 identities (driver check-6 named the unsupported parent directory).
- Integration required-check discovery: passed. Evaluation without producer
  arguments correctly fails closed; this is NOT evidence of a code defect.
- Crucially, the frozen dispatch check-runs have SUCCESS for integration-scope
  and all nine required producers on exact starting HEAD 37723b88534a. The lane's
  earlier integration failure is superseded in the supplied snapshot. Re-evaluate
  those captured same-head results through the local gate, without fetching or
  fabricating evidence. New report commit will still require its own CI verdict.
- Guessed root Playwright configuration was not found; skipped. Browser acceptance
  will not be claimed from a stale external service or merely from source.

## Final evidence and handoff

Replayed the frozen snapshot's latest same-head producer results through
`uv run python scripts/check-integration-scope.py --event-name pull_request`
with nine `--result` arguments derived from those check records: **passed**.
Producer check IDs: docker-build 111655608869, durable-events 111655608773,
hive-conductor-e2e 111655608876, hive-conductor-e2e-ui 111655608917, MinIO
111655608838, pg17 111655608871, pg18 111655608905, strike-ladder 111655608894,
wheel-imports 111655608851. No live GitHub requests or mutations were made.
The reported earlier integration-scope failure is resolved by existing same-head
captured evidence, not by modifying the aggregator.

Read-only HTTP probe via `uv run python` / httpx against
`http://localhost:8101/openapi.json`: GET audit declares an **array** response,
only action/severity/actor query parameters, and no export route. This is not
this branch's paginated contract (`backend/routes/audit.py:110-139`). Thus the
external check-3 result cannot justify weakening the PM assertion. The executed
convergence suite invokes that exact assertion against branch-local real routes,
auth and each production authority (`test_audit_convergence.py:400-445`).

Exact focused test commands:

```sh
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s
uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/tests/e2e
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
```

### Acceptance mapping

1. Bounded cursor pagination / stable ordering / max size: **executed**, passing
   legacy and canonical adapter/HTTP tests including tied timestamps, duplicate
   request IDs, malformed cursors, limit clamping, and empty continuation pages.
2. Authorization/scope filters before database pagination: **executed**, passing
   org/actor isolation and denial-before-query tests; inspected predicates before
   LIMIT in both query builders. ADR-073 admin-only canonical audit retained.
3. Incremental frontend loading and virtualization: source reviewed (100-row
   requests, 500-row retained window, visible slice). Browser execution and actual
   retained-memory/DOM bounds **UNVERIFIED this round**; captured CI success alone
   is not a new behavioral proof.
4. Filters/export/retention without browser corpus loading: filter, NDJSON stream,
   export-cap and retention-metadata tests pass. Download link avoids JS corpus
   accumulation. Actual purge/retention behavior **UNVERIFIED / not implemented**:
   `backend/services/audit_query.py:79` declares `corpus_purge=none`; #325 ownership
   is not a waiver of this issue's literal acceptance criterion.
5. Representative large-data query/index measurement: two real million-row SQLite
   datasets measured above. PostgreSQL execution **UNVERIFIED this round** (four
   skipped tests); SQL-shape test passes.
6. Tests for concurrent inserts, cursor stability, isolation, max limit, empty
   pages and million-row envelope: **executed**, 121 passed across focused suites;
   PostgreSQL-specific cases skipped as stated, not counted as passes.
7. Initial page cost independent of total size: demonstrated for durable SQLite,
   **NOT MET unconditionally**. Reachable legacy no-backend path invokes the
   full snapshot/sort at `backend/services/audit_query.py:386-403`; canonical
   memory `security/sentinel/audit.py:53-67` scans all rows.
8. Browser memory/DOM remains bounded: **UNVERIFIED by execution this round**;
   source cap is not substituted for a browser test result.

### Remaining blocker and change scope

Vulture candidate ledger already lists each retained API exactly once at
`quality/vulture-baseline.json:1001,1010,1072,1171`. The failure is authorization
against the trusted base, not a missing candidate ledger entry. No additional
amendment is justified: adding duplicate identities would be incorrect, removing
live APIs or hiding them from scanning would be cosmetic gate avoidance. A
separate trusted-base authorization is required; grant edits are prohibited here.

Only changed file this round: `docs/testing/358-60d5-repair.md`. No production,
test, ledger, or gate edits; no test inventory delta required. Preserve all prior
work. Final `git diff --check` is required before the local report commit.

Verdict: **BLOCKED**, not integration approval. Progress: checked 1 issue, done 0,
skipped 0, errors 1 (trusted-base Vulture authorization remains unresolved).
Next: obtain the separately authorized grant, target external API checks at a
branch-built deployment, and resolve/execute remaining product acceptance before
claiming MERGE-READY. Do not repeat the already-successful integration-scope
repair or duplicate the candidate ledger entries.
