---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue 358 repair — ff28f5

Frozen scope: issue #358, assigned worktree `/home/dev/Git/wt/auto-358`, branch
`auto-358`, starting HEAD `f7c928095c307ffee9035cf521698cc75b649858`, supplied
base `b35c76e035b3ee60789f9eac3e82526e23aba2e1`. Working tree initially clean.
Files in scope: existing audit routes/query/bridge, core page adapters, AuditLog
frontend and adjacent tests; named integration-scope/vulture gates and workflows,
ledger (only evidence-supported amendments), relevant ADRs, and this note.
No other issue, remote mutation, grant change, or execution authority change.

Initial evidence: current driver check-3 fails at the audit integration test:
expected canonical 403 but received an unpaginated array with HTTP 200. Previous
result reports a stale external service, missing integration producer conclusions,
and trusted-base authorization failures. Those claims are not assumed verified.
Ambiguity: integration target may not serve this checkout; independently inspect
its advertised contract rather than weaken the test. Missing producer evidence
must not be synthesized.

## Gate checkpoint

- Exact requested Vulture command executed (600s timeout): exit 1, 1349
  findings, zero unclassified. Four `get_page` identities are new against trusted
  base `1e4933e2a1b7`; the gate explicitly requires a separately landed grant.
  Log: `/tmp/358-ff28f5-vulture.log`. The live caller is
  `backend/services/audit_bridge.py:186`; deleting these APIs is not justified.
- `uv run python scripts/check-integration-scope.py --event-name merge_group`:
  exit 1, nine producer conclusions missing. No candidate-specific CI producer
  evidence was supplied. Workflow inspection confirms it requires success for
  the exact candidate SHA, not local fabricated conclusions. Remote failure
  cause is UNRESOLVED; no gate weakening is justified.
- All current driver logs inspected: 0/1/2/4/5/7 pass, 3 fails the external
  audit assertion, 6 fails because `packages/hive-conductor/tests` has no
  inventory collection recipe. This is not evidence of a test-count mismatch.
- Accepted ADR-073 preserves admin-only Sentinel audit reads; the legacy
  fallback remains personal-scoped. No reconciliation permits accepting the
  external service's old array response as the new pagination contract.
- Production/tests inspected: SQL seeks bound candidates before merge; legacy
  memory fallback still copies/sorts the corpus per request; retention explicitly
  declares no purge (#325). Frontend caps retained entries at 500 and mounts a
  viewport slice; browser execution is still unverified in this round.

## Fresh validation checkpoint

Executed with 600s command timeout:

- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **76 passed**, 23.74s. Million-row index migration 11.150s; first page
  0.0007s; scoped page 0.0003s; maximum query VM instructions <2800.
  Log: `/tmp/358-ff28f5-backend.log`.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: **8 passed, 4 skipped**, 12.11s. Canonical SQLite million-row
  load 10.170s; max VM work 3400. PostgreSQL DSN not configured for this run;
  PostgreSQL behavior remains unverified. Log: `/tmp/358-ff28f5-core.log`.
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**.
- Independent HTTPX GET of driver target `/openapi.json`: 200; `/v1/audit`
  advertises only action/severity/actor parameters and an array response.
  This differs from the checkout's bounded limit/cursor + AuditPage contract.
  The target does not serve this implementation; its commit is UNVERIFIED.
  No shared service was replaced and no integration assertion was weakened.

The retained Vulture identities are already banked in the candidate ledger at
`quality/vulture-baseline.json:1005,1014,1076,1175`. The scan reports no
unclassified identities; adding duplicate rows would misrepresent its multiset.
No evidence-supported ledger amendment is needed or sufficient. Trusted-base
authorization remains the blocker, and grant editing is outside this assignment.

## Final validation and acceptance

Fresh checks passed (600s timeout): `uv run ruff check .`,
`uv run ruff format --check .` (2861 files),
`uv run python scripts/check-api-route-contracts.py` (281 handlers),
`uv run python scripts/check-suite-inventory.py --suite
packages/hive-conductor/backend/tests` (3352), the same inventory command with
`--suite packages/maistro-core/tests` (12486), and `git diff --check`.
No tests added; inventory delta is zero.

| Acceptance | Evidence / gap |
| --- | --- |
| Bounded stable cursor pagination and maximum page size | Fresh backend/core suites pass, including route calls and real SQLite adapters; external deployment serves old contract. |
| Authorization/scope before DB pagination | Fresh scope-isolation, canonical admin authorization, and real SQL-filter tests pass. |
| Incremental frontend and virtualization | Source inspection confirms cursor loading and viewport slice; browser runtime UNVERIFIED. |
| Filters, export, retention without browser corpus loading | Fresh filter/export tests pass; native download avoids JS corpus collection. Retention endpoint declares bounds but no purge; operational retention UNVERIFIED, related owner #325. |
| Measured large dataset query/index strategy | Both SQLite million-row tests executed with VM-work measurements above; PostgreSQL runtime UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, max limit, empty pages, million-row envelope | Fresh targeted suites exercise these on SQLite/memory; four PostgreSQL tests skipped. |
| Initial page cost independent of corpus | Durable SQLite page queries proven bounded after startup indexing; NOT MET by legacy memory fallback, `audit_query.py:402` copies/sorts whole corpus. |
| Browser memory/DOM bounded | Source caps retained entries at 500 and mounts viewport slice; browser/heap runtime UNVERIFIED. |

## Handoff

**BLOCKED.** Only this evidence note changed; no speculative production/test/gate
or ledger edits. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt unchanged.
Local commit required; no push or GitHub mutation.

Next: supply exact-candidate integration producer logs/conclusions, rebuild the
validation services from this candidate, and land trusted-base authorization for
the four reviewed APIs through the separate authorized process. Do not repeat
this unchanged repair expecting those external prerequisites to fix themselves.
The memory-mode cost and retention acceptance gaps also remain open.

Progress: {checked: 1, done: 0, skipped: 0, errors: 2,
next: external gate inputs and candidate deployment required}.
