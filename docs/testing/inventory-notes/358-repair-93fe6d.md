---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue 358 repair — job 93fe6d

Frozen scope: issue #358 only; worktree `/home/dev/Git/wt/auto-358`, starting
HEAD `04c6bafdb4f5f623e4cfb96dcdbf81c4e6ceda66`, supplied develop base
`1e4933e2a1b7a0bc1bdecfdbafca846c7cb458f4`. Clean starting tree.
Process integration-scope and exact-debt-ledger evidence, existing audit
implementation, adjacent tests and applicable CI configuration. No unrelated
issues, grant changes, or remote mutations. This note records the frozen file
scope: audit routes/services/stores; core audit persistence/protocol/adapters;
AuditLog.tsx; their existing tests; quality/vulture-baseline.json if warranted;
CI integration-scope checker/workflow for diagnosis only.

Driver logs 0–7 inspected. Lint/format and backend tests pass. check-3 fails
because a server returns the legacy array contract; check-6 asks for an
unregistered suite. Prior result inspected, not accepted as fresh proof.
Ambiguity: driver services may not run this checkout. Validate independently;
do not weaken assertions to accommodate an incompatible deployment.

## Fresh gate evidence and architecture review

Exact requested vulture gate executed: exit 1, 1349 findings, zero unclassified.
Four retained `get_page` methods are already banked but lack trusted-base
approval (`/tmp/358-93fe-vulture.log`). The gate explicitly requires a separately
landed grant; candidate ledger edits cannot authorize them. Reviewed live call
in services/audit_bridge.py:186 and protocol/SQLite/Postgres/memory adapters.
These are not dead code. No duplicate ledger entries, method renaming to hide
findings, or speculative scanner repair is justified.

Read docs/README.md, accepted ADR-073, integration-scope workflow/checker,
production audit routes, bridge and query implementations, and adjacent core
tests. ADR-073 canonical decisions remain admin-only. No execution authority or
scope bypass introduced. Integration-scope is an aggregator of nine CI producer
results, not a standalone integration test; exact candidate results are absent
from the supplied job. Do not fabricate success inputs.

Two guessed glob/path lookups found no engine_bridge.py or root playwright
config; not found, skipped. Remaining inspection uses repository-resolved paths.

## Fresh validation results

- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **76 passed** (19.88s), `/tmp/358-93fe-backend.log`.
  Million-row legacy index migration 10.044s, first page 0.0008s, scoped page
  0.0004s, maximum query VM instructions <2800.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: **8 passed, 4 skipped** (12.93s), `/tmp/358-93fe-core.log`.
  Canonical SQLite million-row load 10.969s, maximum query VM work 3400.
  PostgreSQL variants skipped because no test DSN is configured. Existing
  containers belong to other lanes; no shared database was truncated or reused.
- `uv run python scripts/check-integration-scope.py --event-name merge_group`:
  **exit 1**, nine missing producer conclusions. This demonstrates absent local
  evidence, not the cause of the remote failure. Exact candidate producer logs
  remain required. No scope or result values fabricated.
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**.

Reviewed production AuditLog.tsx and adjacent Playwright cases. Incremental
cursor reads, stale-generation rejection, 500 retained records and viewport
slicing are present. Browser execution remains UNVERIFIED, not implied by
source inspection or prior notes.

## Driver target and final hygiene

Independent `uv run python`/httpx GET `http://localhost:8101/openapi.json`:
200; `/v1/audit` declares only action/severity/actor and an **array** response.
This checkout's routes/audit.py:110 instead declares limit/cursor and AuditPage.
The driver therefore tested an incompatible server contract; its served commit
is UNVERIFIED. No live deployment takeover or assertion relaxation performed.

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2861 files).
- `uv run python scripts/check-api-route-contracts.py`: passed (281 handlers,
  15 audited routes, zero canned).
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: passed (3352).
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed (12486).
- `git diff --check`: passed.

## Acceptance evidence

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Bounded stable backend cursor pages and maximum size | 76 backend + 8 core tests passed; real SQLite queries and ASGI requests enforce limits, ties and cursor validation. External driver targets another contract. |
| Database authorization/scope filters before pagination | Passing canonical authorization-before-query and adapter filter/scope tests; SQL predicates precede LIMIT. |
| Frontend incremental loading and virtualization | Source has cursor append and viewport slicing; browser runtime UNVERIFIED. |
| Filters, export, retention without browser corpus loading | Backend filter/scoped capped export tests pass; native download avoids JS corpus accumulation. Retention metadata tests pass, but operational purge is absent (audit_query.py:79); #325 owns policy. Operational retention UNVERIFIED. |
| Representative query/index measurement | Both SQLite million-row envelopes executed, metrics above; PostgreSQL UNVERIFIED (4 skipped cases). |
| Concurrent inserts, stability, isolation, max limit, empty pages, million-row envelope | Passing backend/core suites cover each listed case on SQLite/memory. PostgreSQL tests exist but were skipped. |
| Initial page cost independent of corpus | SQLite request work bounded after startup indexing. NOT MET universally: audit_query.py:402 snapshots/sorts the memory corpus; core ephemeral adapter scans it. |
| Bounded browser memory/DOM rows | Source retains 500 entries and renders a viewport slice; browser execution and byte-level heap bounds UNVERIFIED. |

## Disposition / handoff

**BLOCKED, not merge-ready.** Only this evidence note changed; no new tests or
production edits. The four ledger identities already exist at
quality/vulture-baseline.json:1005,1014,1076,1175 and have a production caller at
services/audit_bridge.py:186. Amending the candidate ledger cannot cure missing
trusted-base authorization; duplicating those identities would corrupt the
multiset. No evidence justifies removing these retained implementations.

Required next inputs: independently landed authorization for the four retained
APIs, exact-candidate integration producer conclusions/logs, and driver services
built from this checkout. Do not schedule another identical repair without
these inputs. Memory-mode initial cost and retention remain acceptance gaps;
browser and PostgreSQL runtime acceptance remain unverified. No grant edits,
gate weakening, GitHub mutation, or competing execution authority introduced.

Progress: {checked: 1, done: 0, skipped: 0, errors: 2, next: supplied gate
blockers require external evidence/authorization}. Local commit preserves this
handoff. Worktree should be clean after committing this note.
