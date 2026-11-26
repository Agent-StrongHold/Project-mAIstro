---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/hive-conductor/tests/e2e: +0
---
# Issue 358 repair — job 668f

## Frozen scope

One item: issue #358, branch `auto-358`, starting HEAD
`eb4a54aa07655ff79ede0d3bf7e13e1a20f49321`, base
`b683268ea2a2baef61ee65bd4be49d4f2e46444a`. Initial worktree clean.
Inspect the existing audit query/routes/UI and adjacent pagination/E2E tests,
repository instructions, ADR-019/062/068, the integration-scope workflow/checker,
the vulture checker/ledger, and this job's seven check logs and prior result.
Potential edits limited to evidence-backed integration-scope repair, retained
vulture identities if the named gate reports them, affected tests and this note.
No new issues, refs, or remote enumeration.

## Initial evidence and assumptions

- Driver checks 0/1/2 pass sync, lint, format; check 4 passes 43 audit tests.
- Driver check 3 fails login against a pre-existing foreign deployment whose
  configured user is `dude`, rather than the fixture's `pmuser`. Do not mutate
  that deployment or weaken authentication; use an isolated test target.
- Driver check 6 requests an unsupported inventory suite
  `packages/hive-conductor/tests`; check 5 passes the backend suite inventory.
- `integration-scope` failure has no detailed log in the supplied artifact;
  reproduce the local gate before deciding a repair.
- Acceptance claims from previous notes are not treated as fresh verification.

## Checkpoint 1

The required Vulture command passed: 1,375 findings, exactly 1,375 reviewed
identities, zero unclassified. No ledger amendment is justified.
`ci_merge_group_scope.py` classified the frozen branch diff as requiring
`docker_build`, `hive_e2e`, and `wheel_imports` only. The integration checker
without supplied results correctly failed closed (all evidence missing).
It is an evidence aggregator, not a locally executable producer; never report
invented success results. Original remote failure attribution remains
UNRESOLVED because no producer log was supplied.

Read ADR-019/062/068 and inspected actual audit query/routes/UI/tests. This
round changes no authorization or execution authority. Existing Conductor
State/JsonStore remains the storage seam. Durable reads use scoped indexed
seeks, max 200 rows, with keyset continuation; browser retains 500 entries.
Two literal acceptance gaps remain: in-memory reads sort the entire corpus,
and retention explicitly advertises no purge (`corpus_purge: none`, #325).
Do not invent a retention policy in a CI repair. Previous repair notes also
record these gaps; they do not constitute executed evidence for this round.

## Checkpoint 2 — executed acceptance validation

- Focused backend audit/foundation/commit-acknowledgement run: **68 passed**
  in 60.68s (`repair-backend.log`). Million-row index migration 29.808s;
  initialized first page 0.0012s, scoped page 0.0014s, maximum query work
  <2,800 SQLite VM instructions across the test's 162 scenarios.
- Built production Conductor and the API runner in isolated Compose project
  `auto358-668f`, removing only published ports via the job's
  `compose-isolated.yml`: **10 passed, 13 existing skips** (`repair-api.log`).
  PM login and live audit route passed. Existing DAG/workspace skips are not
  counted as proof. This reproduces the driver command's intended target
  without changing the unrelated deployment or weakening authentication.
- Built and ran the full Chromium producer against the same isolated target:
  **117 passed in 3.0m**, no retries (`repair-ui.log`). Includes the five audit
  cases: live page envelope, both filter-response races, short-page sentinel
  continuation, eight-page walk with 500-entry cap and at most 30 mounted rows.
- No application/test defect reproduced, so no speculative code or ledger
  changes. The evidence-only note is the sole repository edit this round.

Ruff check and format check passed (2,699 files). Initial inventory validation
caught this note's inline empty mapping: the repository parser requires an
indented suite/count block. Corrected to explicit zero deltas; no tests added.
Final inventory gate passed: backend 3,116 and Python E2E 23. Diff check passed.

## Final disposition and reproduction

Executed the integration aggregator with the frozen branch classification and
only the two actually completed producer results: **exit 1**, missing
`docker-build` and `wheel-imports` (`repair-integration-scope.log`). The
Conductor build alone is not the docker-build producer: CI additionally builds
engine/research/RSI images, boots/restarts PostgreSQL 18, and checks secret
canaries. These remaining producers were not run in this focused validation;
no claim is made that the original remote integration failure is repaired.
The prior validation-budget block remains unresolved, not waived.

All new artifacts are in job directory
`/home/dev/maistro/jobs/668f90bcd9c24e619faa8d2cc48d8bc9`.
Commands run (repository root):

```sh
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_foundation.py packages/hive-conductor/backend/tests/test_state_commit_acknowledgement.py -x -q -s
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e
git diff --check
```

For each of `api-tests`, then `e2e-tests`, executed foreground Compose:

```sh
job=/home/dev/maistro/jobs/668f90bcd9c24e619faa8d2cc48d8bc9
DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose \
  -p auto358-668f -f packages/hive-conductor/docker-compose.test.yml \
  -f "$job/compose-isolated.yml" up --build --abort-on-container-exit \
  --exit-code-from api-tests api-tests
# Repeat with e2e-tests replacing both api-tests arguments.
```

Stopped only this isolated project's containers after validation; data and
containers preserved. No background commands, foreign deployment mutation,
GitHub mutation, ledger change, or discarded work.

## Acceptance matrix

| Criterion | Fresh evidence / remaining limitation |
| --- | --- |
| Bounded stable cursor and maximum page | 68-test backend run: HTTP max 200, floor 1, default 50, timestamp/id ties and cursor continuation. |
| Authorization/scope before database pagination | Real SQLite parity, scoped HTTP probes and exact production SQL VM-work tests passed. Existing middleware/principal authority unchanged. |
| Incremental frontend and virtualization | Full Chromium 117-pass run includes short-page continuation and eight-page audit walk. |
| Filters/export/retention without browser corpus loading | Filter-race tests and filtered download URL passed; backend scoped NDJSON/cap tests passed. Retention only exposes constants, no purge; literal retention-operation criterion NOT MET. |
| Representative large-dataset query/index measurement | One million rows, 162 query scenarios, first page 1.2ms, scoped page 1.4ms, <2,800 VM instructions; startup index migration 29.808s. |
| Concurrent inserts, cursor stability, scope isolation, max, empty, million-row tests | All covered by the executed backend tests, including acknowledged writes concurrent with a durable cursor walk. |
| Initial page cost independent of corpus | Proven only for initialized durable queries. NOT MET unqualified: ephemeral path snapshots/sorts all entries; startup hydration/migration is also corpus-sized. |
| Browser memory/DOM bounded | Chromium test proves 500-entry retained-window display and <=30 mounted rows across eight pages; source inspection confirms entry-array trimming. Byte-level heap profiling, arbitrary detail payload size and very-long-scroll soak UNVERIFIED. |

## Handoff

**NEEDS-REPAIR.** Sole changed file: this zero-delta validation/handoff note.
No production repair was justified by the supplied failure or fresh tests.
Driver needs the isolated Compose target rather than localhost's unrelated
configured instance, and the registered `packages/hive-conductor/tests/e2e`
inventory path rather than its unsupported parent. Remaining work: actual
integration producer evidence, retention policy disposition under #325, and
qualification/repair of the unbounded ephemeral path. No integration approval.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: complete missing
integration producer evidence and resolve the recorded acceptance gaps}.
