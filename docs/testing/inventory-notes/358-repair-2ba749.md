---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/hive-conductor/tests/e2e: +0
---

# Issue 358 repair — 2ba749

## Frozen scope

One item: issue #358, branch `auto-358`, initial HEAD
`0a905e46c28e647ea00f616cd1621e7ef827ca85`, supplied base
`e2b2dfa028220a348e9ac934cb8dab2d1761f1cf`.
Working tree was clean. Process only the supplied issue and its changed audit
backend/frontend/tests, this repair note, integration-scope validation wiring,
and explicitly authorized Vulture ledger repair if the named gate proves debt.
No GitHub mutations, external deployment changes, or execution-authority changes.

## Initial evidence

Read job `2ba749aa79204fc088d1e84d9f457a0e` check logs 0–6 and previous
result `33b53ea6656e42389b8f6a91b1926a0d/result.json`.
- check-3: login expected pmuser but target is already configured for dude.
  Treat as foreign validation target, not evidence for weakening authentication.
- check-4: previous audit tests passed (43); must rerun before claiming acceptance.
- check-6: no collection recipe for `packages/hive-conductor/tests`.
- integration-scope failure lacks details in supplied logs; run actual gate.

Assumption: repair role applies (explicit writer/commit assignment); no develop
sync conflict is evidenced, so do not fetch or merge unrelated changes.

## Results

Checkpoint 1: required Vulture command passed: 1,383 findings / reviewed
identities, zero unclassified. No ledger changes warranted. Read ADR-065,
ADR-068, accepted storage ADR-082226-5104, and proposed ADR-055, plus actual
query/routes/UI and integration producer definitions. Retention purge is still
absent (`corpus_purge: none`); ephemeral queries still sort the full corpus.
These are unresolved acceptance gaps, not authority to invent #325 policy.
The existing Conductor State read seam is not a new canonical datastore.

The integration gate consumes producer results. No remote producer logs were
provided: original failure cause UNRESOLVED. Validate local producers rather
than fabricate results. Scoped producer files for read-only validation are
`.github/workflows/ci.yml`, `scripts/verify-wheel-imports.py`, Conductor Compose
and test Dockerfiles; no CI gate changes planned.

Checkpoint 2: focused audit/foundation/commit-acknowledgement suites: **68
passed in 49.35s** (`repair-backend.log` in this job). Million-row migration
25.665s, first page 0.0011s, scoped page 0.0007s; maximum <2,800 VM instructions
across 162 filter/scope/cursor scenarios. Inspected the actual tests: real
State writer/readers, acknowledged concurrent writes, and HTTP scope probes.

Built every `packages/*/pyproject.toml` wheel with `uv build` into a fresh job
artifact directory (no existing dist removed); ran `uv run python
scripts/verify-wheel-imports.py --dist <job>/wheels --python 3.12`: **pass**,
both bare and widest-extra tiers, all nine checked packages. Existing declared
hive-conductor/meta-package import exclusions remain visible, not changed.
Logs: `repair-wheel-build.log`, `repair-wheel-imports.log`. This supplies the
previously missing local wheel-imports producer evidence.

Checkpoint 3: isolated Compose API producer passed (10 passed / 13 existing
DAG/workspace skips). Full Chromium producer **failed**, 108 passed / 1 failed:
`pm-workflow.spec.ts:266` expected fifth cursor request, received only four
(`repair-ui.log:326`). Failure artifacts preserved under job
`ui-failure-results`; foreign host deployment untouched.

Actual focused repair target: audit IntersectionObserver is only reattached
when callback/sentinel identity changes, not when a continuation completes.
If the next scroll happens before the observer samples the sentinel out of
view, it remains intersecting and delivers no new edge. Re-arm for the new
cursor. Add a deterministic adjacent browser regression using short pages
whose sentinel remains visible, rather than relaxing the failed assertion.
Repair files remain within frozen audit UI/test scope. No backend changes.

Regression executed **red** before production change: short-page test expected
four mounted entries but remained at two (`repair-regression-red.log`). Changed
observer effect dependency to `nextCursor`, retaining the existing overlapping
request guard. Added one Playwright test (110 total); Python inventory delta
remains zero because the registered E2E recipe collects Python, not Chromium.

Checkpoint 4: new regression passed in full run, but original eight-page test
caught extra loading (expected 7 requests, got 8). The sliding window manually
preserves coordinates via its spacer; browser scroll anchoring must not also
move the viewport when rows are evicted. Disable native anchoring in that
viewport. Strengthen existing test to wait for the committed page's scroll
height, not just network request arrival / the now-constant 500-row subtitle.
Exact cursor sequence and per-step request/DOM bounds remain unchanged.
The same run failed unrelated `app-shell-loading.spec.ts:52` (300ms timing
assertion); record it, do not expand repair into app-shell behavior.

Checkpoint 5: final production build passed **25/25** audit browser executions
(five tests repeated five times, `repair-audit-repeat.log`), then **110/110**
full Chromium suite (`repair-ui-complete.log`, 3.4m). No retries or assertion
relaxation. The intermediate unrelated app-shell timing failure did not recur;
its initial failure remains preserved, not relabeled a success.
Ruff check and format-check passed (2,682 files); registered suite inventory
passed (backend 3,090, Python E2E 23). `git diff --check` passed.

## Final gate disposition

Classified the frozen supplied-base diff plus this note using
`uv run python scripts/ci_merge_group_scope.py --json <frozen paths>`:
`hive_e2e`, `wheel_imports`, `docker_build` required; remaining legs false.
Paths saved in job `frozen-paths.txt`, classification in `repair-scope.json`.
This is a local branch classification, not evidence of the remote merge-group
candidate's possibly different diff.

Executed `uv run python scripts/check-integration-scope.py --event-name
merge_group --scope-json <classification> --result hive-conductor-e2e=success
--result hive-conductor-e2e-ui=success --result wheel-imports=success`:
**exit 1**, `docker-build: required but result was <missing>`
(`repair-integration-scope.log`). The Docker producer includes engine/PG18
boot/restart and RSI canary checks beyond the Conductor image built here;
do not manufacture that evidence or weaken the aggregate. Original remote
failure attribution and previous validation-budget block remain UNRESOLVED.

## Reproduction and changed files

- `packages/hive-conductor/frontend/src/pages/AuditLog.tsx`: re-arm observer
  per cursor; disable native scroll anchoring for the manually windowed list.
- `packages/hive-conductor/tests/e2e/pm-workflow.spec.ts`: deterministic
  short-page regression; synchronize existing cap test on committed height.
- This inventory/evidence note. No ledger edits (named Vulture gate passed),
  authorization changes, execution/store authorities, or new retention policy.

Executed backend command:

```sh
uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py \
  packages/hive-conductor/backend/tests/test_audit_routes.py \
  packages/hive-conductor/backend/tests/test_foundation.py \
  packages/hive-conductor/backend/tests/test_state_commit_acknowledgement.py -x -q -s
```

Isolated production builds and E2E runs:

```sh
job=/home/dev/maistro/jobs/2ba749aa79204fc088d1e84d9f457a0e
DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose \
  -p auto358-2ba749 -f packages/hive-conductor/docker-compose.test.yml \
  -f "$job/compose-isolated.yml" up --build --abort-on-container-exit \
  --exit-code-from api-tests api-tests
# Same command with e2e-tests for full Chromium validation.
# For regression red, add -f "$job/compose-regression.yml" before up.
# For five audit repeats, add -f "$job/compose-audit-repeat.yml" before up.
```

Only published ports are reset by the isolation override; no authentication
or assertions bypassed. Project stopped, containers/data preserved. No changes
to the foreign service on host port 8101. Driver must use the isolated Compose
harness and registered `packages/hive-conductor/tests/e2e` inventory recipe,
not a preconfigured host deployment or unsupported parent inventory path.

## Acceptance / remaining risks

| Criterion | Executed evidence / disposition |
| --- | --- |
| Bounded cursor, stable ordering, max page | Backend 68-pass run includes limit 200, default 50, timestamp ties, malformed/empty pages. |
| Scope before DB pagination | Real durable SQL parity/VM tests and HTTP principal-scope probes passed. |
| Incremental loading and virtualization | Full Chromium 110 passed; audit 25/25 repeats; short-page regression failed before fix. |
| Filters/export/retention without browser corpus load | Filter races, scoped capped NDJSON and filtered attachment URL passed. Retention purge **NOT IMPLEMENTED**, `audit_query.py:79` declares `none`; #325 policy must be resolved separately. |
| Query/index strategy measured at scale | Million-row initialized durable first page 0.0011s, scope 0.0007s, max <2,800 VM instructions across 162 cases; cold migration 25.665s. |
| Concurrent inserts/cursor stability/isolation/max/empty/million-row tests | Executed backend cases passed, including concurrent acknowledged durable writes. |
| Initial page cost independent of total size | Proven for initialized durable query path only. **NOT MET unqualified**: `audit_query.py:402-403` snapshots/sorts the ephemeral corpus. Startup hydration/index migration also corpus-sized. |
| Browser memory/DOM bounded | Eight-page test retains at most 500 entries, mounts at most 30 rows. Byte-level heap limit, unbounded detail sizes and very-long-scroll soak remain **UNVERIFIED**. |

No PostgreSQL audit-query, index disk/write-throughput, or full Docker producer
benchmark was run. One intermediate unrelated app-shell timing failure passed
in final full run without changes; retain its log for CI flake follow-up.

Handoff: **NEEDS-REPAIR**, not integration approval. Local audit loading defect
fixed and regression-proven; overall closeout still lacks retention, ephemeral
cost qualification/repair, and complete integration producer evidence.
Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: docker-build
producer evidence and remaining #358 acceptance gaps}. Commit this focused
repair locally; no push, merge, issue closure or GitHub mutation.

