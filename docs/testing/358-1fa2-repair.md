# Issue #358 CI repair checkpoint

Frozen scope: issue #358 only; assigned worktree `/home/dev/Git/wt/auto-358`,
starting HEAD `16fd3c2da0e3b71d42f04486b0834af9b871c276`, supplied base
`534d475e6360985a2c95d6c82869d07001e82cda`. Clean at entry; no salvage needed.
Files in scope: existing #358 audit routes/bridge/query, canonical persistence
paging, AuditLog frontend and adjacent tests, corresponding inventory notes,
CI integration-scope evidence, and (only if warranted by exact scan) Vulture
ledger. No other issues or PRs will be processed or refetched.

Supplied driver results: check-3 fails at PM workflow API assertion (200 rather
than canonical admin-only 403); check-6 uses an unregistered inventory recipe.
Prior result claims retained get_page ledger entries require trusted-base grants;
that is evidence to recheck, not permission to change grants or gates.
Assumption: external API may be stale; use branch-local tests for source behavior.
No integration conflict reported or present, so no develop merge is justified.

Exact Vulture command rerun: exit 1, 1,342 findings versus 1,338 trusted-base
identities. Four retained `get_page` methods lack trusted-base authorization.
The production caller is `backend/services/audit_bridge.py:185`, outside the
scanner's packages/*/src roots. This is not genuinely dead code. No scanner
suppression or API rename is justified. The guessed ADR filename was not found;
skipped and resolved as `ADR-073-warden-sentinel.md`. Read ADR-062, ADR-068,
and ADR-073. ADR-073's admin-only decision audit overrides a personal canonical
trail interpretation; retain the existing authorization and execution authorities.

## Executed validation

- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass, 2,919 files.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`: 76 passed (26.87s).
  Legacy SQLite million-row index migration 12.761s; first page 0.0012s;
  scoped page 0.0007s; maximum query work below 2,800 VM instructions.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s`: 45 passed, 4 PostgreSQL cases skipped (13.86s).
  Canonical SQLite million-row load 10.723s; maximum query work 3,400 VM instructions.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/tests/e2e`:
  pass, 23 identities. This is the valid recipe for the driver's failed parent path.
- `uv run python scripts/check-integration-scope.py --event-name pull_request --required-json`:
  pass; nine required specialized producers.
- Same integration-scope command without `--required-json`: exit 1, all nine
  producer outcomes missing locally. No results fabricated. Captured dispatch CI
  evidence belongs to prior head `16d4ef27d542`, not this candidate; it includes
  failed docker-build, pg17, and pg18 producers. Current-head producer validation
  remains UNVERIFIED; earlier successes are not integration approval.

The candidate Vulture ledger already contains each retained API exactly once
(lines 1001, 1010, 1072, 1171). The failing command reports trusted-base debt,
not unbanked candidate debt. Amending it again would introduce duplicate debt;
a separately authorized trusted-base grant is needed, outside this worker's
permissions. No ledger or grant changes made.

Read-only HTTP validation (`uv run python`, httpx GET
`http://localhost:8101/openapi.json`): the live route declares an array response,
only action/severity/actor parameters, and no export route. This is independently
incompatible with this branch's `routes/audit.py:110-139` page envelope and
`/export` route. Do not change the PM assertion to accommodate that foreign
build. The passing convergence suite executes the same PM assertion through real
branch routes/auth against both legacy and canonical authorities.

## Acceptance and residual risks

- Backend bounded cursor pagination, stable ordering, maximum size: executed
  adapter and HTTP tests pass (121 focused tests total).
- Authorization/scope before database pagination: canonical denial-before-query,
  explicit organization scope, and legacy actor-scope tests pass; source confirms
  query predicates precede LIMIT. ADR-073 admin restriction is preserved.
- Incremental frontend loading and virtualization: inspected `AuditLog.tsx`,
  including 500-entry retained window and visible-row slicing. Browser execution
  and DOM/heap bounds are UNVERIFIED in this attempt, not inferred from source.
- Filters/export/retention without browser corpus loading: backend filter,
  streaming, cap, and retention-metadata tests pass. Operational retention is
  absent (`audit_query.py:79` says corpus_purge=none), delegated to #325; this
  issue's full retention criterion remains UNVERIFIED, not silently waived.
- Representative large-data query/index strategy: two million-row SQLite
  envelopes executed with deterministic work bounds above. PostgreSQL remains
  UNVERIFIED in this round (four skipped cases, no DSN configured).
- Concurrent inserts, cursor stability, scope isolation, maximum limit, empty
  pages: exercised by the passing canonical memory/SQLite and legacy tests.
- Initial page cost independent of total size: durable SQLite demonstrated;
  unconditional criterion NOT MET. The reachable no-backend fallback invokes
  `audit_query.py:386-403` (full snapshot/sort); canonical memory paging at
  `security/sentinel/audit.py:53-67` scans every entry. This is not repaired by
  changing a scanner ledger or the integration aggregator.
- Browser memory/DOM bound: UNVERIFIED by execution this round.

Changed file this round: only this evidence/handoff document. No production or
test changes justified by the named gate evidence; no added tests, so no
inventory delta. `git diff --check` passed. No GitHub mutations, gate weakening,
ref deletions, or discarded work.

Outcome: BLOCKED. Progress: checked 1, done 0, skipped 0, errors 1 (unresolved
external gate prerequisites). Next: obtain authorized trusted-base grants for
retained APIs and same-candidate specialized producer results; target the API
checks at a branch-built service. Resolve the explicitly outstanding product
acceptance before declaring merge readiness. This handoff is committed locally.
