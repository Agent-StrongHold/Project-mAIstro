---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/hive-conductor/tests/e2e: 0
  packages/maistro-core/tests: 0
---

# Issue 358 repair — bdf373

## Frozen scope

Only issue #358, assigned branch `auto-358`, starting HEAD
`52cbc360712344a9417530e304cec137c5f1c11a`, supplied base
`2ef76025e50b226a109d06bca0ae67fa14689afe`. Initial worktree clean.
Inspection scope: supplied check-0..7 logs and prior result; audit routes,
query service, stores, frontend and their existing tests; applicable ADRs;
integration-scope and vulture CI gates. No unrelated repairs or remote mutations.

## Initial evidence

Driver check-3 failed at test_pm_workflow_api.py:271: expected canonical audit
403, got a legacy unbounded array with unrelated system actors. This may be a
stale external server; do not weaken assertions. Driver check-6 reports no
inventory collection recipe for packages/hive-conductor/tests. Other supplied
checks report passing, not independently verified yet.

Ambiguity: integration-scope failure has no specialized job evidence attached.
Inspect the aggregate's actual contract and execute locally available gates;
do not guess new scanner findings or edit ledgers without scan evidence.

## Fresh gate evidence

`uv sync --locked --extra dev` passed. Exact requested vulture command exits 1:
1346 findings versus 1342 in trusted base `91996e19223d`. Four `get_page`
identities (PgAuditLog, SqliteAuditLog, AuditLog protocol, InMemoryAuditLog)
require trusted-base authorization. The live caller is
`backend/services/audit_bridge.py:186`; these are not dead methods. Candidate
ledger already contains all four identities, so no further ledger amendment
is justified. The scanner explicitly says candidate updates cannot authorize
new debt. No grant edits permitted in this lane.

Read ADR-073: canonical decision audit remains admin-only, overriding any
interpretation of personal scope for Sentinel data. The list/export routes
preserve this distinction. Read integration-scope workflow and checker: all
nine producer results are required for pull requests; focused tests are not
substitutes for full producer evidence. Guessed workflow path
`.github/workflows/hive-conductor-e2e.yml` was not found; skipped.

`uv run ruff check .` and `uv run ruff format --check .` pass.
Focused backend audit/convergence/pagination/noop suites: **76 passed** in
23.98s (`/tmp/358-bdf373-backend.log`). Million-row legacy SQLite: index
migration 11.647s, first page 0.0010s, scoped page 0.0012s, <2800 VM instructions.

Fresh images built from this worktree with CI's compose harness; isolated
project `audit358-bdf373`, unused subnet 10.234.59.0/24 and no published ports
(`/tmp/358-bdf373-compose.yml`). These are environment-only overrides; test
commands/application code unchanged. API producer **10 passed, 13 skipped**,
including the exact audit test failing against the driver's external service
(`/tmp/358-bdf373-api.log`). UI producer (`CI=true`) **125 passed** in 2.6m
(`/tmp/358-bdf373-ui.log`). Prior RSI failure did not recur on this single
fresh run. No retries, skip additions or assertion relaxations. Driver should
use fresh branch images, not the unrelated service on shared port 8101.

Core audit-pages and workspace store-boundary conformance tests: **45 passed,
4 skipped** in 12.38s (`/tmp/358-bdf373-core.log`). No PostgreSQL DSN configured;
all four skips explicitly require PostgreSQL. Canonical SQLite million-row
load 10.260s; maximum work 3400 VM instructions over filter shapes/deep ties.
PostgreSQL execution in this round is UNVERIFIED; prior claims not promoted.

Inventory checker with actual suite keys backend/tests, tests/e2e, and
maistro-core/tests passes: 16219 unique test identities, all three inventories
match (`/tmp/358-bdf373-inventory.log`). No test additions or count changes.
Driver's unsupported tests-parent suite argument must be corrected externally.

`node --test tests/ci/integration-scope.test.cjs`: **12 passed**.
`uv run python scripts/check-integration-scope.py --event-name pull_request
--result hive-conductor-e2e=success --result hive-conductor-e2e-ui=success`:
**exit 1**, correctly missing seven producers: docker-build, durable-events,
object storage (MinIO), postgres (pg17), postgres (pg18), strike-ladder,
wheel-imports. Neither focused tests nor a compose image build justify claiming
these complete CI jobs succeeded. Full integration-scope remains UNVERIFIED.

## Acceptance evidence and limits

- Bounded cursor pagination, stable ordering, maximum page size: executed
  backend/core suites and fresh API producer pass. Both query seams clamp to
  200 entries and order by timestamp plus unique row identity.
- Authorization/scope before database pagination: real SQLite tests and core
  route convergence tests pass. SQL scope predicates precede LIMIT; canonical
  decisions require admin before reading, per accepted ADR-073. PostgreSQL
  execution is UNVERIFIED this round (query-composition test passed).
- Incremental loading and virtualization: fresh UI producer passes all audit
  cases, including short pages, late filter responses and eight cursor pages.
  pm-workflow.spec.ts:311 tests <=500 retained entries and <=30 mounted rows.
- Filters/export/retention without browser-wide corpus loading: filter races,
  scoped/capped streaming export, and constant retention metadata tests pass.
  Actual retention deletion remains UNVERIFIED/unimplemented: audit_query.py:79
  explicitly reports `corpus_purge: none`; #325 owns purge policy.
- Representative query/index strategy: two real million-row SQLite datasets
  measured above, with deterministic VM-work bounds. PostgreSQL million-row
  envelope was skipped; cannot claim fresh PostgreSQL performance evidence.
- Concurrent inserts, cursor stability, isolation, maximum limit, empty pages,
  million-row tests: executed backend/core coverage passes (four PG skips).
- Initial cost independent of corpus: proven for indexed durable SQLite reads,
  NOT unconditional: audit_query.py:386-403 copies/sorts the whole in-memory
  store per request. No cosmetic rewrite to hide this known limitation.
- Browser memory/DOM: bounded retained-entry and mounted-row tests pass.
  Byte-level heap profiling and arbitrarily large individual entry payloads
  remain UNVERIFIED; do not equate a row-count bound with a byte-size bound.

## Handoff

**BLOCKED**, not integration approval. Only this note changed. No production,
test, ledger, grant, authorization, or execution-authority changes. A repair
must not remove live adapter methods or weaken assertions to evade the gate.
The four retained identities are already banked at vulture-baseline.json:1004,
1013,1075,1174; maintainer must land trusted-base authorization separately.
Fresh compose results supersede the previous local RSI failure for this run,
but do not prove missing CI producers. No develop-sync conflict was observed;
no remote fetch/merge/mutation needed.

Progress: checked 1 assigned item, done 0 repairs, skipped 0 items, blocked 1.
Next: resolve trusted-base grant, collect missing producer evidence, fix the
driver's stale service target and inventory suite key; resolve the stated
retention/in-memory acceptance limits before claiming full #358 completion.

Final ruff lint/format and `git diff --check` pass. This job's three compose
containers are stopped; logs and stopped containers retained. Other services
untouched. Evidence note committed locally; no pushes or GitHub mutations.
