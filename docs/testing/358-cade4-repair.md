# Issue 358 repair checkpoint (cade4)

## Frozen scope

Only issue #358; assigned worktree `/home/dev/Git/wt/auto-358`, starting
HEAD `f88cb83ddc8f3497236b05c889da585aa38e9da7`, supplied base
`e46ad6708fda20f76b8915679ef701f3ddb6b7e2`. Initial tree clean.
Snapshot: the supplied dispatch-context.json and check-0 through check-7 logs;
prior result 84a5a232097d427f961100d08bb301ce. No GitHub mutation or refresh.
Repair targets: integration-scope evidence, audit route/store/UI and their
existing tests, exact vulture ledger gate if actual findings require amendment.
This note is the only planned documentation addition; tests/production edits
only if reproduced evidence identifies a candidate defect.

## Initial evidence and assumptions

Driver check-3 fails at test_pm_workflow_api.py:271: remote MaistroCoreBridge
reports legacy array with many entries despite limit=1, rather than expected
canonical admin authorization. This is evidence of remote/candidate mismatch,
not justification for accepting the old response. check-6 uses an unsupported
suite inventory recipe. Prior result reports missing integration producers and
unavailable Docker; neither claim is assumed current. Integration-scope is the
assigned blocker; preserve gates and investigate its actual invocation.

## Checkpoint 1

Exact requested Vulture scan passed: 1,326 findings, 1,326 reviewed identities,
zero unclassified. No ledger edits warranted. Fresh `docker info` failed to
connect to unix:///var/run/docker.sock, confirming the environment blocker.
The integration workflow requires producer checks for the exact candidate SHA;
local successes cannot be substituted for absent remote producer results.
Candidate audit.py returns AuditPage and denies non-admin canonical readers
before I/O, unlike the driver's external response. Frontend inspection confirms
100-row requests, 500 retained entries, fixed-height visible row slicing and a
native export download; runtime evidence still required.

Instruction discovery accidentally enumerated sibling AGENTS.md paths; no
sibling files were read or changed. Further commands stay in assigned scope.
## Checkpoint 2

Read accepted ADR-073 and ADR-081226-9944. Canonical decision audit remains
admin-only; pagination is a projection, not a new event/execution authority.
No reconciliation changes to Goal -> Graph -> Run -> NodeRun -> Attempt.

Executed `uv run pytest` with `-x -q -s` on backend tests
`test_audit_convergence.py`, `test_audit_pagination.py`, `test_audit_routes.py`,
`test_degraded_mode_surface.py`, `test_noop_route_contracts.py`: **91 passed**
(`/tmp/358-cade4-backend.log`). Actual million-row SQLite index migration:
8.933s; first page 0.0008s, scoped page 0.0004s; maximum VM work <2,800.

Executed core `tests/persistence/test_audit_pages.py` plus
`tests/workspaces/test_store_boundary_scope_conformance.py` with the same
pytest arguments: **50 passed, 4 skipped** (`/tmp/358-cade4-core.log`).
Canonical million-row SQLite load 8.059s; maximum query VM work 3,400.
PostgreSQL cases skipped; these are not PostgreSQL acceptance evidence.

## Final validation

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3,196 files.
- `uv run python scripts/check-api-route-contracts.py`: passed, 284 handlers,
  15 audited routes, zero canned.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/tests/e2e`: passed, 23 tests. This is the registered
  recipe; the driver's parent path is not a valid recipe.
- `node --test tests/ci/integration-scope.test.cjs`: 12 passed.
- `cd packages/hive-conductor/frontend && npm run build`: passed
  (`/tmp/358-cade4-build.log`); not browser-runtime evidence.
- Validated supplied base ref, classified the full existing candidate diff
  using `scripts/ci_merge_group_scope.py --json`, then ran
  `uv run python scripts/check-integration-scope.py --event-name merge_group
  --scope-json <classifier output>`: **exit 1**, missing docker-build,
  hive-conductor-e2e, hive-conductor-e2e-ui, postgres (pg17), postgres (pg18),
  wheel-imports (`/tmp/358-cade4-integration.log`). No fabricated results supplied.

### Integration failure ambiguity: UNRESOLVED

The supplied check-run snapshot is for
`bc293cd790b6852da71b3e251dcecdda84bbde9b`, where integration-scope is **success**,
not this assigned HEAD or an identified failed merge-group SHA. The local gate
failure establishes missing producer evidence, not the cause of the reported
remote failure. Two inspections (workflow and supplied check snapshot) provide
no actual failed producer log to repair. Stop here rather than speculate or
re-fetch. Docker is unavailable and a candidate deployment is not established.

## Acceptance matrix

| Criterion | Executed evidence / limit |
| --- | --- |
| Bounded cursor pagination, stable order, maximum size | 91 backend and 50 core/scope tests pass; production SQL clamps at 200 and orders timestamp + unique row ID. |
| Authorization/scope before DB pagination | Route denial tests and real SQLite adapter scope/filter tests pass; production predicates precede LIMIT. Canonical decisions remain admin-only per ADR-073. |
| Incremental loading and virtualization | Component inspected, build passes; browser runtime **UNVERIFIED**. |
| Filters, export, retention without browser corpus load | Backend scoped filtered streaming export/cap and constant retention metadata tests pass. Native browser download **UNVERIFIED**. Actual corpus purge is absent, explicitly reported as none, related owner #325; not proven retention enforcement. |
| Representative large-dataset query/index measurements | Both million-row SQLite checks pass with timings/work bounds above. PostgreSQL **UNVERIFIED**, four skipped cases. |
| Concurrent inserts, cursor stability, scope isolation, max limit, empty pages, million-row envelope | Executed SQLite/memory cases pass; PostgreSQL **UNVERIFIED**. |
| Initial page cost independent of corpus size | Production-query million-row work bounds and memory no-enumeration tests pass; PostgreSQL **UNVERIFIED**. |
| Browser memory/DOM bounded | 500-entry window and visible-row slicing inspected; runtime **UNVERIFIED**. |

## Disposition

**BLOCKED**, no justified code/gate/ledger repair. Only this report changed;
no test additions, hence no inventory delta. Preserve strict E2E expectations.
Writer handoff is not integration approval. Commit locally; no GitHub mutations.

Next inputs: exact failed merge-group SHA and producer failure logs, working
Docker/PostgreSQL, and a known candidate deployment for API/browser checks.
Do not repeatedly dispatch the unchanged missing-evidence blocker as a code
repair without those inputs.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: supply exact-candidate
integration evidence and service prerequisites}. All existing work preserved.
