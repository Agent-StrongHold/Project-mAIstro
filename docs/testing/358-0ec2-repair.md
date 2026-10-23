# Issue #358 repair checkpoint — job 0ec2a334

## Frozen scope

Only issue #358, branch `auto-358`, starting HEAD
`620de43cb2dcafca81f32f66bf317fb2282b2137`, supplied base
`2a11c1cc006a977ee76281307767319773d4fb62`. No GitHub mutations,
new issue enumeration, gate weakening, or unrelated repairs.
The worktree was clean at entry; no incoming diff required salvage.

Read the supplied dispatch snapshot, prior result, and check-0 through check-7
logs. Initial evidence: check-3 fails against an external HTTP service (canonical
health but legacy list-shaped audit response); check-6 names an unregistered
inventory suite. Other supplied checks pass, but are not treated as fresh proof.
The requested integration-scope failure has no exact failed merge-group producer
artifacts in those logs. Assumption: inspect its actual local contract rather than
fabricate producer successes or modify policy. Vulture changes only if the
requested scanner supplies an actual identity finding.

## First executed results

- Exact requested vulture command passed: 1,328 findings / reviewed identities,
  zero unclassified. No ledger change is warranted.
- `uv run python scripts/check-integration-scope.py --event-name merge_group`
  failed closed with nine missing producer results. This proves local evidence
  is absent, not the cause of the reported remote failure.
- Snapshot extraction initially assumed check-run data was an object; it is a
  list. Extraction failed with AttributeError. Corrected inspection found a
  successful integration-scope check for
  `bc293cd790b6852da71b3e251dcecdda84bbde9b`, not the assigned HEAD or a failed
  merge-group candidate. No failure log is attached to that check.

## Architecture and focused validation

Read repository instructions, documentation authority map, accepted ADR-073 and
ADR-081226-9944, audit route/query implementation, frontend pagination/window
implementation, and adjacent pagination/performance tests. The canonical
admin-only decision audit takes precedence over legacy personal-trail semantics
(ADR-073); pagination is only a read projection. No change to
`Goal -> Graph -> Run -> NodeRun -> Attempt` or execution/event authority.

Fresh `uv run ruff check .` and `uv run ruff format --check .` passed (3,168
files). Focused backend selection (`test_audit_convergence`,
`test_audit_pagination`, `test_audit_routes`, `test_degraded_mode_surface`,
`test_noop_route_contracts`, all under `packages/hive-conductor/backend/tests`)
via `uv run pytest ... -x -q -s`: **91 passed** in 23.98s.
`worker-backend.log` in the job directory records the million-row measurements:
12.051s startup index migration; 0.0008s first page; 0.0005s scoped page;
maximum query work below 2,800 SQLite VM instructions. This separates startup
index cost from bounded request work.

Fresh core/migration selection:

```sh
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py \
  packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py \
  tests/migrations/test_audit_cursor_indexes.py \
  tests/migrations/test_migration_chain.py -x -q -s
```

**52 passed, 22 skipped** (live database environments not configured).
`worker-core.log` records canonical SQLite million-row load 9.002s and maximum
query work 3,400 VM instructions. Live PostgreSQL acceptance is not claimed.

Additional executed gates:

- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/tests/e2e`:
  passed, 23 tests. This is the registered path; the driver used an unregistered
  parent path in check-6. No inventory/test changes are needed.
- `uv run python scripts/check-api-route-contracts.py`: passed, 284 handlers,
  15 registered audited routes, zero canned responses.
- `uv run pytest tests/test_check_integration_scope.py -x -q`: 18 passed.
- `node --test tests/ci/integration-scope.test.cjs`: 12 passed.
- `git diff --check`: passed.

## Acceptance evidence and explicit limits

| Criterion | Fresh evidence / limit |
| --- | --- |
| Bounded cursor, stable ordering, max size | 91 backend tests plus core selection passed; real SQLite and memory adapters exercise ties, invalid cursors, floors and ceilings. |
| Authorization/scope before database pagination | Route denial-before-query and SQLite isolation/filter tests passed; core bridge supplies explicit system org scope and requires admin before I/O. |
| Incremental loading and virtualization | Production `AuditLog.tsx` and routed Playwright tests inspected: cursor requests, five-page retained window, row slicing, stale-response guards. Browser execution **UNVERIFIED this round**; no inherited pass claim. |
| Filters/export/retention without browser corpus loading | Backend filtered/scoped lazy capped NDJSON export and retention endpoint tests passed. Frontend uses a native download link, not a Blob; native browser download **UNVERIFIED this round**. Corpus purging remains explicitly absent (`corpus_purge=none`), owned by #325. |
| Representative large-dataset query/index strategy | Both real SQLite million-row tests passed with deterministic VM-work measurements above. PostgreSQL live envelope **UNVERIFIED this round**. |
| Concurrent inserts, cursor stability, isolation, max limit, empty pages, million-row envelope | Backend and core selections passed for SQLite and memory; PostgreSQL cases skipped. |
| Initial-page cost independent of corpus size | Startup migration measured separately; SQL seeks bounded by page limit; production memory tests prohibit corpus enumeration and bound index probes. |
| Browser memory/DOM stays bounded | Implementation and eight-page DOM/retained-count test inspected; browser execution and heap profiling **UNVERIFIED this round**. |

## Disposition / required next evidence

**BLOCKED.** The named integration-scope failure cannot be repaired honestly
without its failed candidate SHA and producer conclusions/logs. Local gate
failure with no `--result` arguments is an evidence-gap diagnostic, not a
reproduction of the remote failure. Passing aggregator unit tests do not
substitute for producer runs. Do not fabricate successes or weaken the gate.

Provide the failed merge-group SHA and logs for integration-scope and its
required producers: pg17, pg18, MinIO, durable-events, strike-ladder,
Hive API/UI E2E, wheel-imports, docker-build. The supplied snapshot's success
on a different SHA cannot establish readiness.

Driver check-3's canonical health plus legacy list-shaped export contradicts
this checkout's `routes/audit.py` canonical denial/NDJSON contract. Focused ASGI
production-route tests pass unchanged. Candidate ownership of the external
HTTP service is **UNVERIFIED**; configure `HIVE_BASE_URL` to a known deployment
of the candidate rather than relaxing the assertion. No external service was
modified during this round.

Only this handoff document changed. No tests added, so no inventory-delta note
is required. No code/ledger/gate edits are supported by the executed findings.
No merge conflicts or dirty incoming work existed. No push, GitHub mutation,
ref deletion, work discard, or integration approval.

Progress: checked 1 issue; done 0 repairs (validation handoff completed);
skipped 0 issues; errors 1 unresolved integration-evidence blocker;
next: obtain exact failed-candidate producer logs before another repair round.

