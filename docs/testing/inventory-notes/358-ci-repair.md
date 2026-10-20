---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

# Issue #358 CI repair

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-358`, branch `auto-358`.
- Starting head `e72521eb26d91f6e28ca5903a292dec1920ebd5d`; supplied base
  `4e7ef1ab1ceb41edb175baa06557ab18f4657162`. Both resolve; initial tree clean.
- Process only issue #358: existing audit pagination implementation/tests,
  integration-scope gate evidence, required exact-debt-ledger check, and this note.
- No GitHub mutations or unrelated deployment changes.

## Initial evidence / assumptions

Current job check-3.log reproduces the earlier E2E login failure: the target
already has user `dude`, whereas the suite expects `pmuser`. This is evidence of
an incompatible live test target, not evidence that pagination is broken.
Do not change credentials, skip assertions, or mutate that deployment.
Check-6.log reports no inventory collection recipe for
`packages/hive-conductor/tests`; check-5.log covers the registered backend suite.
The supplied integration-scope failure has no detailed log in the job; inspect
and execute the local gate against the supplied resolved base/head.

## Checkpoint 1

- Required vulture command passed: 1,383 reviewed identities, zero unbanked.
  No eliminated/retained identities changed; no ledger amendment warranted.
- `check-integration-scope.py --event-name merge_group` fails closed for nine
  missing check results. The gate consumes CI job results, not Git refs. No
  producer failure log was supplied; the aggregate cannot honestly be marked
  successful locally. Ambiguity UNRESOLVED; do not invent successful results.
- Read root/package instructions, ADR-068, ADR-055 (Proposed), production audit
  query/routes/UI, adjacent tests, and previous inventory evidence.
- Existing inventory documents corpus-linear scoped and deep-cursor scans.
  Production `_page_sql` confirms only an ordering index, with scope as residual
  predicate and cursor as OR. Focus repair on this actual #358 evidence, keeping
  the existing store/authorization authority. Retention policy remains #325;
  no claim of implemented purge is justified.

## Repair files and architecture reconciliation

Frozen repair files: `backend/services/audit_query.py`, `backend/stores.py`
(startup migration wiring only), `backend/tests/test_audit_pagination.py`, and
this note, all under `packages/hive-conductor/` except this note.
Three new regressions are collected (+3): deterministic VM work, startup upgrade
and idempotence, and threaded durable writes during a cursor walk. Existing
envelope and parity cases are strengthened in place.
ADR-081226-a66b execution hierarchy is unchanged. ADR-082226-5104 names PostgreSQL
as canonical durable storage but explicitly retains `state.py` local state;
this repairs the already-reachable Conductor State/kv_store read seam, not a
new canonical audit/event store or a claim of PostgreSQL coverage. Authorization
continues using the middleware principal and existing scope intersection.

## Checkpoint 2

- New regression failed before production changes: absent two-alias actor scope
  executed >=200,000 SQLite VM instructions over 25,000 rows (budget <50,000).
- Repair: eight audit-only filter-shape indexes, disjoint bounded cursor seeks
  (timestamp tie/id seek + older timestamp seek), per-alias SQL merge of bounded
  results, and migration wired into existing store initialization.
- Focused backend validation after repair: 41 passed in 47.27s, including the
  million-row fixture and the new work-count regression.
- Explicit trade-off: index build/startup and audit writes/storage cost more;
  indexes exclude unrelated namespaces. Cold migration cost is measured
  separately, not hidden inside or excused from an HTTP latency bound.

The million-row test now measures 162 filter/scope/cursor combinations using
SQLite VM work plus production `page_entries` results. Existing parity adds
two-alias scope merging and denied scopes. Startup upgrade runs the real
`initialize_stores` seam against a pre-existing ordering-only index. Durable
concurrency uses acknowledged JsonStore writes in a separate thread.

## Checkpoint 3

- Focused backend + adjacent foundation/commit-acknowledgement suites: 68 passed
  in 47.54s. Million-row migration 25.361s, first page 0.0013s, scoped page
  0.0009s; initial 81-case VM maximum <2,800 instructions. Expanded to 162
  cases to exercise two-alias merges without narrowing to one actor filter.
- Fresh isolated Compose project `auto358-dae449`, production Dockerfile build,
  API E2E: 10 passed, 13 existing DAG/workspace-dependent skips. Audit trail and
  login pass. No interaction with the foreign deployment on host port 8101.
- Inventory gate: backend 3,048 / API E2E 23; both match. Vulture remains 1,383
  reviewed / zero unbanked. Ruff reported one C408 in the new test; corrected.

## Final validation

Executed from the assigned worktree:

- `uv run ruff check .`: pass after correcting the C408 test literal.
- `uv run ruff format --check .`: pass, 2,676 files.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_foundation.py
  packages/hive-conductor/backend/tests/test_state_commit_acknowledgement.py
  -x -q -s`: **68 passed**, 47.65s. Final million-row migration 23.454s,
  first page 0.0017s, scoped page 0.0007s, maximum <2,800 VM instructions
  across 162 filter/scope/cursor combinations. Log `/tmp/358-backend-final.log`.
- `DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose -p
  auto358-dae449 -f packages/hive-conductor/docker-compose.test.yml -f
  /tmp/358-compose-ports.yml up --build --abort-on-container-exit
  --exit-code-from api-tests api-tests`: **10 passed, 13 skipped**.
  `/tmp/358-api-compose.log`. Override resets published ports only.
- Same Compose command with `--exit-code-from e2e-tests e2e-tests`:
  **109 passed**, 2.6m; includes late-response filter races and bounded
  incremental row-window tests. `/tmp/358-ui-compose.log`.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e`:
  pass, **3,048 / 23**. Driver's parent-path recipe is unsupported; no gate changed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: pass, **1,383** reviewed,
  zero unbanked. No ledger edits needed.
- `uv run python scripts/check-integration-scope.py --event-name merge_group
  --result hive-conductor-e2e=success --result hive-conductor-e2e-ui=success`:
  **fails closed** for missing docker-build, durable-events, MinIO, pg17, pg18,
  strike-ladder, wheel-imports results. `/tmp/358-integration-scope.log`.
  Local Conductor image construction is not evidence for the distinct Docker
  job. No supplied scope JSON means the gate correctly requires all legs.
- `git diff --check`: pass.

## Acceptance disposition / residual risks

- Bounded cursor pagination, stable timestamp/id ordering, max 200 entries:
  route and backend tests pass, including timestamp ties and empty pages.
- Scope/filter-before-limit: real SQLite tests, parity with memory backend,
  two-alias merges and route-level cross-user probes pass. No authorization
  authority changed.
- Incremental virtualized UI: real Chromium tests pass through eight pages;
  at most 500 retained entries and 30 mounted rows. Tests mock paginated data
  for volume/races; the separate live audit route E2E passes. No byte-level
  heap profile or million-page browser soak was performed.
- Filters/export: backend scoped NDJSON/cap tests and browser filter-specific
  attachment URL pass; no full-corpus browser fetch is introduced.
- Retention: **UNVERIFIED / not implemented**; the existing `/retention` endpoint
  truthfully declares `corpus_purge: none`. Policy/purge remains #325, not a
  silently fabricated acceptance claim or a new scheduler in this repair.
- Query/index measurement: deterministic 25k tie-heavy regression failed before
  and passes after; million-row production query measurements above pass.
  Cold index migration is corpus-sized and costs 23.454s in this run. Eight
  indexes increase audit write/storage cost; write-throughput/disk envelopes
  are not benchmarked here. Existing JsonStore startup hydration still loads
  server-side records; no claim of bounded total server memory is made.
- Concurrent acknowledged durable inserts and in-memory threaded inserts,
  cursor stability, isolation, maximum size and empty pages: executed tests pass.
- Initial request work is bounded on the initialized durable path. Ephemeral
  in-memory mode still sorts the corpus per request: **not corpus-independent**.
- Complete integration-scope aggregate: **UNVERIFIED** without missing producer
  logs/results. Do not weaken it or manufacture successful results.

Handoff verdict: **NEEDS-REPAIR** (local query repair complete, not integration
approval). Next: supply missing CI producer evidence; resolve retention policy
acceptance with #325 and the ephemeral-mode performance limitation. No merge,
issue closure, GitHub mutation, ledger/grant edit, or competing execution/store
path was introduced. Previous inventory notes are historical; the new VM-work
measurements supersede their scoped/deep-query scan finding for this head.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: remaining #358
acceptance and missing integration-scope producer evidence}. Focused repair is
committed locally; issue closeout remains unfinished.

