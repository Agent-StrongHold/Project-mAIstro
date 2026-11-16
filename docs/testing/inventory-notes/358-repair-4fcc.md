---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/hive-conductor/tests/e2e: +0
---
# Issue 358 repair checkpoint (job 4fcc)

## Frozen scope

Only issue #358, branch `auto-358`, starting HEAD
`496edbd1a033f1fb0479dcb15b124ecc52d2edc2`, supplied base
`4df9dd9bde4c6d03fccd1466cf9d6827a8fd4aa8`. Starting worktree clean.
Inspect the existing audit implementation, adjacent tests, integration-scope
and vulture gates; change only files necessary for evidenced failures plus
this inventory/validation note. No remote mutations or unrelated repairs.

## Initial evidence

Read this job's check-0 through check-6 logs and the supplied prior result.
Check-3 fails against an already configured live deployment (`dude`, not the
fixture's `pmuser`). Check-6 reports no inventory recipe for
`packages/hive-conductor/tests`. Check-4 reports 43 passing audit tests, but
acceptance will be independently checked. Integration-scope's specific failure
is not included in these logs; inspect its local implementation and execute it.
Assumption: this is a writer CI-repair round, not read-only verification.

## Progress

Vulture command requested by the lane passes: 1,372 findings, all 1,372
reviewed identities, zero unclassified. No ledger amendment needed.
Local integration-scope evaluation of the frozen diff fails closed for missing
`docker-build`, `hive-conductor-e2e`, `hive-conductor-e2e-ui`, and
`wheel-imports` evidence. This is an aggregator, not a source scanner; no
producer conclusion is present in the supplied failure. Do not fabricate
success results or weaken its gate. Inspect/run the relevant producers.

## Exact-head CI evidence (read-only snapshot)

Fetched check runs once for the exact assigned starting HEAD using
`gh api repos/Agent-StrongHold/Project-mAIstro/commits/496edbd1a033f1fb0479dcb15b124ecc52d2edc2/check-runs --paginate`.
Contrary to the supplied historical failure label, **integration-scope passes**
(run 36965850008, job 110709315545). Every specialized producer also passes
in run 36965849982: docker-build 110709379796; wheel-imports 110709379768;
hive-conductor-e2e 110709379688; hive-conductor-e2e-ui 110709379733;
postgres pg17 110709379760 / pg18 110709379719; durable-events 110709379741;
strike-ladder 110709379742; object storage 110709379683. Exact-debt-ledger
passes in run 36965850012, job 110709315780. These are actual measured
conclusions, not inferred from local builds. No integration-scope gate repair
is supported by this snapshot. Separate `test` job 110709316039 is failing;
not expanding this frozen assignment to an unrelated producer.

The supplied merge-queue candidate SHA/log was not provided, so its specific
historical failure remains UNRESOLVED; head-check success does not establish
success of an unknown synthetic merge. No test count change.

## Executed validation (current round)

- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass, 2,714 files.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_foundation.py
  packages/hive-conductor/backend/tests/test_state_commit_acknowledgement.py
  -x -q -s`: **68 passed** in 64.31s. Million rows: index startup 29.638s;
  initial page 0.0014s; scoped page 0.0010s; maximum measured query work
  <2,800 VM instructions across the filter/cursor/scope combinations.
- `check-integration-scope.py` now executed with the **observed exact-head
  producer conclusions**: pass for both pull_request and merge_group modes.
  The latter uses only the frozen branch/base diff, not an unknown queue diff.
- Isolated Compose API suite: **10 passed, 13 pre-existing skips**. Production
  image built from this worktree, fresh data, no published host ports. The
  login and audit read pass; no foreign deployment was reconfigured. Log:
  `/tmp/auto358-4fcc-api.log`. Foreground command:

  ```sh
  printf 'services:\n  hive:\n    ports: !reset []\n' | \
    DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose \
    -p auto358-4fcc -f packages/hive-conductor/docker-compose.test.yml -f - \
    up --build --abort-on-container-exit --exit-code-from api-tests api-tests
  ```

- Initial suite-inventory check rejected this new note's inline empty delta
  mapping. Corrected it to the mandated indented +0 block. Rerun passes:
  **3,202 backend / 23 API E2E** node IDs. `git diff --check` passes.
- Full Chromium producer (same Compose command, substituting `e2e-tests` for
  `api-tests`): **exit 1; 111 passed, 6 failed, 8 did not run**, 9.0m.
  Log `/tmp/auto358-4fcc-ui.log`. All five audit tests at
  `tests/e2e/pm-workflow.spec.ts:180-307` passed, including live authenticated
  audit read, stale-filter-response races, short-page continuation, eight-page
  cursor loading, <=500 retained entries and <=30 mounted rows.

## Unresolved browser producer failures

Fresh execution is **not** green despite the earlier GitHub producer success.
All six failures hit the unchanged CI 20-second per-test/hook timeout:

- `tests/e2e/api-error-copy.spec.ts:30`: workspace creation in beforeAll.
- `tests/e2e/api-timeout.spec.ts:30`: setup-status request.
- `tests/e2e/dag-run-button-truthfulness.spec.ts:74`: login in beforeAll.
- `tests/e2e/dashboard-reduced-motion.spec.ts:38`: status dot after reload.
- `tests/e2e/pm-workflow.spec.ts:152`: elevation before optimizer exercise.
- `tests/e2e/pm-workflow.spec.ts:175`: wait after Optimization Inbox navigation.

These logs do not establish a root cause or connect it to the audit changes.
No timeout inflation, skipped assertions, production guesses, or gate weakening.
No retry-until-green. The supplied validation-budget block is not cleared.
Next worker needs the original synthetic merge SHA/failing producer log and
separate diagnosis of these observed timeout boundaries. The driver should use
a disposable Compose target and the registered inventory path rather than the
foreign host service / `packages/hive-conductor/tests` parent path.

## Acceptance / architecture reconciliation

Read AGENTS.md, CLAUDE.md, accepted ADR-065, ADR-068, ADR-081226-7248,
ADR-082226-5104, ADR-082526-547c and ADR-091226-1341. Inspected the production
routes/query seam/store wiring and routed frontend beside their tests. This
round changes **only this note**. No new execution, authorization, event, or
storage authority; no grant or vulture ledger changes. Canonical
Goal -> Graph -> Run -> NodeRun -> Attempt remains untouched. The performance
claim is for the existing Conductor local State store, not a replacement for
canonical PostgreSQL events (ADR-082226-5104 section 9 / ADR-081226-7248).

| Criterion | Current executed evidence / limitation |
| --- | --- |
| Bounded cursor, ordering, max page | 68 backend tests pass, including limit clamp 200, tied timestamps, stable continuation and malformed cursors. |
| Authorization/scope before database pagination | Durable SQL parity, scope isolation, filter-shape seeks and VM-work tests pass. |
| Incremental frontend / virtualization | Five audit browser tests pass in the production build; large responses are mocked, live authenticated read separately passes. |
| Filters/export/retention without browser corpus | Scoped/capped streaming NDJSON and filter races pass. Retention operations **UNVERIFIED / absent**: `backend/services/audit_query.py:79` explicitly reports `corpus_purge: none` and defers policy to #325. Metadata is not a purge implementation. |
| Representative large-dataset measurement | Million-row initialized SQLite query/index measurements above pass. PostgreSQL performance and write/storage amplification are UNVERIFIED. |
| Concurrency/stability/isolation/max/empty/million-row tests | Executed backend suite includes acknowledged concurrent durable inserts, cursor spelling/ties, empty/past-end queries and million-row matrix. |
| Initial page independent of corpus size | Proven for initialized durable reads only. Unqualified criterion is **not met**: `backend/services/audit_query.py:402-403` snapshots/sorts the in-memory corpus every request. Startup index migration/hydration is corpus-sized. |
| Bounded browser memory/DOM | Eight-page test passes <=500 retained entries / <=30 mounted rows. Payload-byte heap limit and arbitrary-length scrolling remain UNVERIFIED. |

## Disposition

**NEEDS-REPAIR**, evidence-only checkpoint, not an implemented repair and not
integration approval. Do not requeue as fixed merely because a commit exists.
Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: browser timeout
root cause and explicit retention/in-memory acceptance reconciliation}`.
Compose containers/data and logs are preserved; stop the job-specific project
without removing it. No other worktree or deployment was changed.
