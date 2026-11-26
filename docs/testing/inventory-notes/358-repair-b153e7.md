---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/hive-conductor/tests/e2e: 0
  packages/maistro-core/tests: 0
---

# Issue 358 repair — b153e7

## Frozen scope

One item: issue #358, branch auto-358, starting HEAD
888ce33dd8b919172476e371ca1f55455f63e8e1, supplied base
29af8200e4a846036fa8357ab67d5bb47f950db9. Starting worktree clean.
Process only the supplied check-0 through check-7 logs, prior result artifact,
issue acceptance criteria, and integration-scope/Vulture failures. Candidate
implementation files are the audit route/query/adapters/UI and adjacent tests;
gate files are inspection-only unless an actual in-scope defect is established.
This note records evidence and any focused repairs; no remote mutations.

## Initial evidence and assumptions

- check-0/1/2 passed; check-4 ran 76 passing backend tests.
- check-3 failed at test_pm_workflow_api.py:271: live service returns a list
  instead of the branch's bounded page and admits a non-admin canonical read.
  Assumption: verify service provenance before changing assertions or routes.
- check-5/7 passed inventory; check-6 names an unregistered suite and exits 2.
- Prior result reports Vulture trusted-base authorization failures and missing
  integration producers. These claims must be rerun, not accepted as current.
- No conflict exists at start; no develop merge is justified by the supplied
  evidence. Canonical execution and authorization authorities remain unchanged.

## Named gate result

The exact requested Vulture command exits 1: 1,346 findings versus 1,342 trusted
base identities. Four retained `get_page` methods (PgAuditLog, SqliteAuditLog,
AuditLog protocol, InMemoryAuditLog) are already banked in the candidate ledger.
The failure explicitly requires a grant in the trusted base. Candidate ledger
amendment cannot resolve it; deleting reachable pagination APIs or adding fake
uses would be incorrect. No ledger change is warranted.

Read ADR-037 and ADR-073: preserve indefinite event retention (#325 owns purge)
and admin-only canonical decision audit. The integration-scope workflow is an
aggregator of remote specialized producer conclusions. Those actual conclusions
are absent from the supplied logs; do not manufacture successful results.
Remote integration failure cause remains UNRESOLVED.

Production review also confirms the known initial-cost limitation remains:
`audit_query.py:402` snapshots and sorts the entire memory fallback corpus per
page. Fixing the CI gates cannot make that unconditional criterion pass. This
round will report BLOCKED rather than relabel that behavior as bounded.

## Executed acceptance checkpoint

- Focused Conductor audit/convergence/routes/noop suite: **76 passed** (21.57s).
  Actual million-row SQLite index migration: 10.312s; initial page 0.0007s;
  scoped page 0.0004s; maximum query work <2,800 VM instructions.
- Core audit pagination suite: **8 passed, 4 skipped** (11.83s). Canonical
  SQLite million-row load: 10.004s; maximum query work 3,400 VM instructions.
  PostgreSQL runtime cases require MAISTRO_TEST_PG_DSN and were skipped.
- Reviewed the actual frontend: 100-row incremental requests, 500-entry
  sliding retained window, viewport slicing, generation guards, and native
  export link. Browser runtime remains UNVERIFIED, not inferred from source.
- Attempted to read `tests/e2e/conftest.py`: not found; skipped. No unresolved
  ref was executed, and no production assertions were weakened.

## Final validation and acceptance

Executed with 1,200-second timeouts unless noted:

```text
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py -x -q -s
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e --suite packages/maistro-core/tests
uv run python scripts/check-integration-scope.py --event-name pull_request
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
git diff --check
```

- Ruff check/format pass (2,886 files formatted); diff whitespace check passes.
- All three registered inventories pass: backend 3,369; e2e 23; core 12,761.
  Driver check-6's `packages/hive-conductor/tests` is not a valid recipe; use
  `packages/hive-conductor/tests/e2e`. No gate changes or test count changes.
- Vulture ran with a 600-second timeout; exits 1 as detailed above.
  Ledger locations: `quality/vulture-baseline.json:1004,1013,1075,1174`.
  Actual production use: `backend/services/audit_bridge.py:186`.
- Integration-scope exits 1 because no producer results are available locally
  (all nine PR-required conclusions missing). This is NOT evidence of the
  specific remote producer that failed the merge queue. Its cause is UNRESOLVED;
  the supplied assignment contains no candidate SHA/check-run ID for that run.
- A read-only `uv run python`/httpx probe (120-second command timeout) resolves
  the same HIVE_BASE_URL/default as the e2e fixture. `/openapi.json` answers 200
  but documents only action/severity/actor and an array response for GET audit.
  This is demonstrably not this checkout's limit/cursor/page route contract.
  No changes to the shared deployment, no login mutations, no relaxed tests.

| Criterion | Executed evidence / residual gap |
| --- | --- |
| Bounded cursor, stable ordering, max page | Route/adapter tests pass; supplied live integration failure persists as a deployment-contract mismatch. |
| Scope before database pagination | SQLite scope isolation/filter tests pass; PostgreSQL runtime UNVERIFIED. |
| Frontend incremental loading/virtualization | Source reviewed; browser runtime UNVERIFIED. |
| Filters/export/retention without browser corpus load | Backend tests pass; native export link reviewed, browser download UNVERIFIED. ADR-037 retention preserved; no purge introduced. |
| Representative query/index measurements | Two real million-row SQLite tests pass with deterministic VM-work bounds above; PostgreSQL UNVERIFIED. |
| Concurrent inserts, cursor stability, scope, max, empty, million-row envelope | 76 Conductor and 8 core tests pass; 4 PostgreSQL cases skipped. |
| Corpus-independent initial page cost | Durable SQLite measured; NOT MET for the reachable memory fallback (`audit_query.py:402`). |
| Bounded browser memory/DOM | 500-entry cap and viewport slicing present; runtime UNVERIFIED. |

Only this evidence note changed. No speculative implementation, duplicate ledger
banking, gate weakening, grants, or remote mutations. Verdict **BLOCKED**.
Next: provide trusted-base authorization for the four already-reviewed APIs and
actual failed integration producer logs; validate an isolated candidate-matching
API/browser deployment and PostgreSQL. The memory fallback performance gap also
needs a focused implementation decision. Repeating this evidence-only repair
cannot authorize the APIs or update an external deployment.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 2 unresolved
named gates. Commit this handoff locally; this is not integration approval.


