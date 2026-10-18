---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
---

# Issue 358 CI repair handoff — f262c0

## Scope and disposition

Only issue #358, assigned worktree `/home/dev/Git/wt/auto-358`, branch
`auto-358`. Starting HEAD `ba099bf89bb290602fabb1911822369bf1601da5` and base
`cd258510bd2475073e5a397e42a5a371f3008a32` resolve; initial tree was clean.
The original 15 changed paths were frozen before validation. No develop-sync
conflict was present. No fetch, GitHub mutation, or unrelated repair performed.

**NEEDS-REPAIR, not integration approval.** Only this evidence note changes.
There is no evidence-backed production or ledger fix for the supplied CI
failure: the named vulture gate passes, and both Conductor E2E producers pass
on an isolated deployment. Missing CI producer evidence and remaining issue
acceptance gaps are not repaired by manufacturing success results.

Read repository instructions, accepted ADR-065, ADR-068, ADR-081226-9944,
ADR-082226-5104, and proposed ADR-055; inspected production audit routes,
query/store wiring, UI, adjacent backend tests and browser tests. No canonical
execution, event, storage, or authorization authority changes. SQLite results
below describe the existing Conductor local-State seam, not PostgreSQL audit
coverage. Proposed ADR-055 is not authority to invent retention policy for #325.

## Supplied failures versus newly executed evidence

Job directory: `/home/dev/maistro/jobs/f262c0c76b214432ad7a5f4cc5d6a477`.
All `repair-*.log` paths below are relative to it.

- Inspected saved check-0 through check-6 and prior job
  `4644700c581f446b90d598ed9c6ed8e0/result.json` and check-3. The driver API
  test targets a deployment seeded as `dude`, not required fixture `pmuser`.
  Do not change that deployment, substitute credentials or suppress assertions.
- Fresh Compose project `auto358-f262c0`, built from this worktree, with only
  published ports reset: API suite **10 passed, 13 existing skips**. Login
  and live audit-route tests pass (`repair-api.log`). DAG/workspace skips are
  not acceptance evidence for those features.
- Same isolated production build, Chromium suite: **109 passed in 3.0m**
  (`repair-ui.log`). This includes live audit reads, late first/continuation
  response races, filtered export URL, and eight-page incremental loading.
- `uv run ruff check .` and `uv run ruff format --check .`: pass (2,682 files).
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_foundation.py
  packages/hive-conductor/backend/tests/test_state_commit_acknowledgement.py
  -x -q -s`: **68 passed in 51.11s** (`repair-backend.log`).
- Million-row index migration **28.211s**, first page **0.0012s**, scoped page
  **0.0008s**, maximum query work **<2,800 SQLite VM instructions** across
  162 filter/scope/cursor combinations. Cold migration is corpus-sized; it is
  not hidden inside the initialized request-cost measurement.
- Required `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: pass, **1,383 reviewed
  identities / 1,383 findings / zero unclassified**. No identity changed or
  requires banking/removal; ledger amendment would be unjustified.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests --suite
  packages/hive-conductor/tests/e2e`: pass, **3,090 / 23**
  (`repair-inventory.log`). Driver check-6 requests the unsupported parent
  path `packages/hive-conductor/tests`; use the registered E2E recipe.

## Integration-scope: precise outstanding evidence

Unlike running the gate without scope (which correctly requires everything),
this round classified the **frozen actual branch diff** with the repository's
`scripts/ci_merge_group_scope.py --json`. Result: `hive_e2e`, `wheel_imports`
and `docker_build` enabled; postgres, object_storage, durable_events and
strike_ladder disabled. This is a local branch/base classification, **not**
evidence of the remote merge-group candidate's possibly different diff.

Executed `uv run python scripts/check-integration-scope.py --event-name
merge_group --scope-json "$scope_json"`: fails for four missing check results
(`repair-integration-initial.log`). Re-executed with only the two locally
proven results, `--result hive-conductor-e2e=success --result
hive-conductor-e2e-ui=success`: **exit 1**, missing **docker-build** and
**wheel-imports** (`repair-integration-final.log`). The Conductor image build
is not the distinct docker-build job. Neither missing producer was executed
or asserted successful here. No remote producer log was supplied, so the
original integration-scope failure cause remains **UNRESOLVED**; the local
missing-evidence result does not diagnose it. The previous validation-budget
block cannot truthfully be declared cleared.

Compose reproduction (run each service in turn):

```sh
job=/home/dev/maistro/jobs/f262c0c76b214432ad7a5f4cc5d6a477
DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose \
  -p auto358-f262c0 -f packages/hive-conductor/docker-compose.test.yml \
  -f "$job/compose-isolated.yml" up --build --abort-on-container-exit \
  --exit-code-from api-tests api-tests
# Repeat with --exit-code-from e2e-tests e2e-tests.
```

The override contains only `services.hive.ports: !reset []`. Project stopped
at completion; containers/data preserved. Host deployment on 8101 untouched.

## Acceptance and remaining risks

| Criterion | Current executed evidence / disposition |
| --- | --- |
| Bounded cursor, stable ordering, max page | Backend tests pass: default 50/max 200, tie handling, malformed cursors, empty pages, continuation. |
| Scope/filter before database pagination | Durable SQL parity, two-alias merge, scope probes and VM-work tests pass; existing authenticated principal remains authority. |
| Incremental loading and virtualization | Chromium tests pass; eight pages, at most 500 retained entries and 30 mounted rows. Volume responses are mocked; live route read is tested separately. |
| Filters/export/retention without whole-corpus browser load | Filter races, scoped/capped NDJSON and download URL pass. Retention **NOT IMPLEMENTED**: `backend/services/audit_query.py:79` reports `corpus_purge: none`. |
| Representative large query/index strategy | Executed million-row benchmark and tie-heavy 25k deterministic VM regression above. No write-throughput, index-disk or PostgreSQL benchmark. |
| Concurrent inserts, stability, isolation, maximum, empty, million rows | All covered in the executed backend suites, including threaded acknowledged durable writes. |
| Initial page independent of corpus | Proven only for initialized durable path. **NOT MET unqualified**: `backend/services/audit_query.py:402-403` snapshots and sorts the in-memory corpus per request. Startup hydration/migration also remains corpus-sized. |
| Browser memory/DOM bounded | Retained-entry/DOM counts pass. Byte-level heap bound and very-long-scroll soak **UNVERIFIED**; payload size is not bounded by the row-count assertion. |

No tests added/removed and no gate weakened. Next: obtain the actual failed
CI producer evidence (or run the missing local producers), resolve retention
acceptance with #325, and address the in-memory page-cost gap. This note is a
committed handoff, not a claim that the assigned repair or issue is complete.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: missing producer
evidence and unresolved retention/in-memory acceptance}.
