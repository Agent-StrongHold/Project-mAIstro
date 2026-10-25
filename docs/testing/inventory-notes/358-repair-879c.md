# Issue #358 repair — job 879ceec6

## Frozen scope and initial evidence

- Only issue #358; assigned worktree `/home/dev/Git/wt/auto-358`, branch
  `auto-358`, verified starting HEAD `6dfecc38368a607160ed7f1af36535ba0b1213a6`.
- Supplied base `8c8fc8d6706a0837bd991c4e92138bf4d776ac9e` resolves in the
  initial diff. Worktree clean; no incoming edits to salvage.
- Snapshot: driver checks 0–7 in job 879ceec6, prior result 663e73fd,
  existing #358 audit route/query/bridge, canonical audit page adapters,
  AuditLog frontend and adjacent audit tests. Named gates: integration-scope
  and exact vulture ledger scan. No other issues/PRs will be processed.
- Candidate edit files: this note, `quality/vulture-baseline.json` only if the
  actual scan demonstrates a bookkeeping correction, and existing audit files
  only if an actual, locally repairable regression is demonstrated. No grants,
  unrelated workflow changes, or speculative scanner workarounds.
- Driver check-3 fails at `test_pm_workflow_api.py:271`: a live service returns
  an unpaginated JSON array and 200 instead of canonical admin-only 403.
  Check-6 supplies an unsupported inventory suite (`hive-conductor/tests`).
  Other supplied logs pass. Prior claims are not considered fresh validation.
- Ambiguity: integration-scope failure supplied without specialized producer
  logs/results. Run the real gate with available evidence, never synthesize
  successful producer statuses. Do not weaken API assertions for an unidentified
  external service.

## Fresh validation

- `uv sync --locked --extra dev`: passed.
- Exact requested vulture scan: exit 1, 1365 findings, zero unclassified;
  four retained `get_page` methods lack trusted-base authorization.
  Candidate ledger already includes all four at lines 1020, 1029, 1091, 1190.
  Production caller: `backend/services/audit_bridge.py:186`, outside the scan's
  `packages/*/src` roots. These are not dead methods. No candidate ledger
  correction is indicated; duplicating entries or adding fake uses would not
  be a repair. Grant edits remain prohibited.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  exit 1, all nine specialized producer results missing. This proves local
  evidence is absent, not which remote producer caused the reported failure.
- `node --test tests/ci/integration-scope.test.cjs`: 8 passed.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format '{{.Names}}'`:
  cannot connect to daemon. Do not use an unidentified shared database.
- Guessed ADR-073 filename not found; skipped. Resolved actual path from the
  directory: `docs/adr/ADR-073-warden-sentinel.md`. ADR-062 read, including
  canonical durable-execution clarification. No execution authority changes.

Scope checkpoint: named gates cannot be repaired by ledger bookkeeping or
local producer-status fabrication. Finish focused acceptance validation and
commit this evidence; do not start unrelated repairs.

## Acceptance validation (fresh execution, 1200-second timeouts)

Read the production route, bridge, query builder, canonical SQL page builder,
frontend component, and adjacent convergence/pagination/adapter tests. ADR-073
requires canonical decision audit to remain admin-scoped: the live-test 403
assertion is correct and must not be weakened. ADR-062's canonical durable
execution clarification is preserved; this round changes no authority.

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 2804 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: 8 passed, 4 PostgreSQL cases skipped (no test DSN).
  Canonical SQLite million-row load: 8.485s; maximum query work: 3400 VM
  instructions, including deep timestamp ties and equality-filter shapes.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py -x -q -s`:
  58 passed. Legacy million-row startup index migration: 9.101s; first/scoped
  page: 0.0010s/0.0004s; maximum query work below 2800 VM instructions.
  This also executes the driver's external PM audit assertion in-process against
  both real production authority bindings (legacy and canonical), without
  mocking audit responses. The supplied live response is not this route's
  paginated contract; live deployment provenance remains UNVERIFIED.

| Criterion | Evidence and limits |
| --- | --- |
| Backend bounded cursors, stable ordering, max page size | Passing real-route and adapter tests: max 200, timestamp/id ties, malformed/past-end cursors. PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before database pagination | Passing canonical denial-before-query and exact-org/actor SQL tests; legacy SQLite scope/filter parity. No new authorization path. |
| Frontend incremental loading and virtualization | `AuditLog.tsx` inspected: cursor requests, virtual row slice, retained window cap 500. Browser runtime UNVERIFIED; existing UI harness targets an external service, not a verified build of this checkout. |
| Filters/export/retention without browser corpus | Filter/export parity and cap tests pass; frontend native download link inspected. Retention is metadata only (`audit_query.py:79` declares `corpus_purge: none`), so actual retention operation is NOT proven. Related policy remains #325; do not invent purge policy here. |
| Query/index measurement on large datasets | Both production SQLite paths measured at one million rows, with deterministic VM-work budgets above. PostgreSQL measurement UNVERIFIED (skipped). |
| Concurrent inserts, stability, isolation, maximum, empty pages, million-row envelope tests | Passing focused suites exercise these for SQLite/memory; PostgreSQL coverage skipped. |
| Corpus-independent initial page cost | Durable SQLite indexed query work is bounded after startup migration. Memory fallback snapshots/sorts the corpus (`audit_query.py:386`); unqualified definition of done NOT met. |
| Bounded browser memory/DOM rows | Source caps entries and renders a window; runtime heap/DOM verification UNVERIFIED. |

## Disposition and handoff

BLOCKED, not integration approval. No evidence-backed local production repair
can supply trusted-base authorization or missing specialized producer results.
All four retained methods are already banked correctly; no identity was
eliminated, and no candidate ledger amendment is warranted by the actual scan.
No new tests or inventory counts changed; no inventory-delta block required.
Only this evidence note changes in this round.

Final checks passed: `uv run python scripts/check-suite-inventory.py --suite
packages/hive-conductor/backend/tests` (3318), the same command with
`--suite packages/maistro-core/tests` (12244), and `git diff --check`.
The driver's unsupported `packages/hive-conductor/tests` inventory recipe was
not added or misrepresented as a successful gate.

Next: supply candidate-specific specialized producer logs/results and a reviewed
trusted-base grant for the four retained methods. Remaining acceptance work
needs verified candidate browser execution, isolated PostgreSQL validation, and
resolution of retention/non-durable initial-cost requirements. No GitHub
mutations, fetch/merge (no sync conflict), grant edits, fabricated scanner uses,
or background commands were performed.

Progress: checked 1 issue, done 0, skipped 0, errors 1 (blocked). Commit this
handoff locally, preserving the implementation and all prior notes.
