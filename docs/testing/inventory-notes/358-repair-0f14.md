---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue 358 — repair 0f14

## Frozen scope

One item: issue #358 in `/home/dev/Git/wt/auto-358`, branch `auto-358`.
Starting HEAD `f6ac58d848cb439bf6e0ec22b67b8a6b34cee031` and supplied develop
base `4fd7801fb333611955dda962d11845aaf065277c` both resolve. Incoming tree clean.
Inputs frozen: this job's check-0 through check-7 logs, supplied prior result,
existing audit routes/query adapters/UI/tests, relevant ADRs, and the named
integration-scope and exact-debt-ledger gates. No other issue or grant changes.

Initial evidence: driver check-3 failed against an external service returning
an unpaginated list and HTTP 200 where the candidate's canonical audit route
requires HTTP 403 for a non-admin. Deployed revision is unknown; do not weaken
that assertion. Driver check-6 uses an inventory suite without a collection
recipe. Prior claims are not treated as fresh validation.

The supplied base is not the current merge base (actual merge base resolves to
`045cfdfbe3eaa0c84493eb02754d7410b0c69378`); no conflict exists in the worktree.
Assumption: do not perform a speculative develop merge or alter unrelated
features to repair missing exact-candidate CI evidence.

## Validation

- Exact CI vulture command `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **FAIL**,
  1364 findings, zero unclassified; four `get_page` identities require
  trusted-base authorization. Log: `/tmp/358-0f14-vulture.log`.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  **FAIL**, nine missing producer conclusions. Log:
  `/tmp/358-0f14-integration.log`. This invocation has no producer inputs and
  therefore proves fail-closed behavior, not the remote failure's root cause.
  `.github/workflows/integration-scope.yml` requires exact-candidate check-run
  results; none are supplied in the job artifacts. Do not fabricate successes.
- Read ADR-068, ADR-073 and ADR-081226-a66b. Preserve existing authorization,
  Sentinel audit authority and `Goal -> Graph -> Run -> NodeRun -> Attempt`.
  Reconciliation: canonical Sentinel decisions remain admin-only per ADR-073;
  personal actor filtering is only for the unbound legacy corpus.
- Production `audit_bridge.py:188` calls `AuditLog.get_page`; it lives outside
  the vulture scan roots. These are live protocol/adapter APIs, not dead code.
  Renaming/removing live APIs solely to avoid a scanner finding would not be
  an evidence-based repair.
- Candidate ledger already contains all four retained identities at
  `quality/vulture-baseline.json:1019,1028,1090,1189`. There are no unbanked
  candidate identities to add and no genuinely dead API to eliminate. The
  permitted ledger amendment is already present; adding duplicate rows would
  corrupt the exact multiset, not repair trusted-base authorization.
- Focused backend validation: `uv run pytest
  packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **76 passed** (18.51s). Log: `/tmp/358-0f14-backend.log`. Includes the
  driver's PM audit assertion against both real candidate authority bindings,
  authentication and production routes (ASGI transport, not deployed service).
  Legacy SQLite million-row index migration 8.658s, first page 0.0008s,
  scoped page 0.0004s, maximum VM work <2800 instructions.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: **8 passed, 4 skipped** (9.88s); PostgreSQL DSN absent. Log:
  `/tmp/358-0f14-core.log`. Canonical SQLite million-row load 8.383s,
  maximum measured query VM work 3400 instructions.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  2811 files. `node --test tests/ci/integration-scope.test.cjs`: 8 passed.
  Aggregator tests do not substitute for exact-candidate producer conclusions.
- Read-only check-run lookup for the exact starting HEAD returned HTTP 422:
  `No commit found for SHA: f6ac58d848cb439bf6e0ec22b67b8a6b34cee031`.
  Log: `/tmp/358-0f14-check-runs.log`. Remote ref **not found; skipped**.
  Integration failure root cause remains **UNRESOLVED**; no further remote
  enumeration, speculative merge or GitHub mutation.
- Suite inventory gates passed: backend 3340; core 12249. Used the registered
  suite paths, not the driver's invalid `packages/hive-conductor/tests` path.
- `uv run python scripts/check-api-route-contracts.py`: passed (281 handlers,
  15 audited routes, zero canned). `git diff --check`: passed.

## Acceptance accounting

| Criterion | Fresh evidence or limitation |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum page size | Backend/core tests passed; real SQLite and memory adapters enforce the 200-row ceiling and timestamp/row-ID keysets. PostgreSQL runtime **UNVERIFIED** this round (four skipped tests). |
| Authorization/scope before database pagination | Production-route tests pass authorization-before-I/O and canonical admin-only checks; SQLite tests execute exact scope/filter predicates before LIMIT. |
| Incremental frontend loading and virtualization | `AuditLog.tsx` source inspected: 100-row cursor requests, 500 retained rows, viewport slice. Browser runtime **UNVERIFIED**; existing Playwright tests were read, not run. |
| Filters, export and retention without browser corpus loading | Filter/scoped export and capped NDJSON tests pass; UI native-download link inspected. Retention only declares constants and `corpus_purge: none`; operational purge **UNVERIFIED** (#325). |
| Representative query/index measurements | Actual million-row SQLite legacy and canonical queries executed: <2800 / 3400 VM instructions. PostgreSQL **UNVERIFIED** this round. |
| Concurrent inserts, cursor stability, isolation, maximum limit, empty pages, million-row envelope | Executed on SQLite/memory in 76 backend + 8 core passing tests, including threaded writes, timestamp ties and deep cursors. PostgreSQL cases skipped. |
| Corpus-independent initial page cost | Indexed SQLite request work bounded after migration. **Not met in all reachable modes**: `audit_query.py:386` snapshots/sorts the whole memory corpus; `security/sentinel/audit.py:59` scans its list. |
| Bounded browser memory/DOM | Source retains at most 500 entries and a viewport slice; browser runtime/heap **UNVERIFIED**. Entry count does not bound individual detail payload size. |

## Disposition

**BLOCKED**, not integration approval. Only this validation/handoff note changed;
no source, tests, ledger, grant or gate changes. Existing reviewed ledger entries
are preserved. No new tests; inventory delta zero. The candidate's local route
contract passes where the driver observed an external deployment failure, so
changing assertions or production authorization to match that service would be
unsupported by evidence.

Required handoff: provide the actual merge-queue candidate SHA and failed
producer logs; use the trusted-base authorization process for the four retained
APIs. Identify/rebuild the external PM service before retrying its contract
check. Browser/PG runtime, memory-mode cost and operational retention still
prevent an all-criteria completion claim. Do not re-run this same repair solely
with the same absent producer evidence and grant.

Progress: checked 1, done 0, skipped 0, errors 2 (named gates); next: trusted-base
authorization and exact-candidate producer evidence. Remote lookup skipped after
one not-found result. Local commit records the blocked handoff, not a fix.

