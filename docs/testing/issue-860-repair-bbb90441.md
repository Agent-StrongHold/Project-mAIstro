# Issue #860 repair — bbb90441

## Frozen scope

- Issue: #860 only; branch `auto-860` in the assigned worktree.
- Starting HEAD: `5e814aa8eef825046deff4f647423329e13ddd9a`.
- Develop base: `675db8be6c41b020ffffb224b2748c159c78a122`.
- Inputs: supplied dispatch-context.json, prior result 0997a52d, and prior
  check-3.log from job 98a11313. No check-*.log files were present in this job
  directory at initial inspection.
- Files in scope: this report; scripts/soak/run_soak.py;
  tests/test_soak_promotion_gates.py; docs/testing/soak/m3a-load-profile.md;
  docs/testing/soak/m3a-soak-evidence.md; existing round30 evidence;
  packages/maistro-server/src/maistro_server middleware and adjacent tests;
  packages/maistro-core/src/maistro/persistence/pg_learnings.py and its tests;
  quality/vulture-baseline.json only if the requested exact scan finds debt.
- Existing worktree was clean; no uncommitted work required salvage.

## Initial assessment

The prior result reports BLOCKED on deployment/promotion evidence, not an
unresolved merge. Assumption: validate the supplied gate failure before any
code or ledger repair. No fetching, integration, GitHub mutations, or changes
to execution authority are in scope. Validation and acceptance results follow.

## Reproduced repair targets

- Read the supplied historical check-3.log: its schema test expected 21 DDL
  statements but observed 24. At this HEAD, the independent expected-DDL list
  already includes the three Gauntlet columns (test_pg_learnings.py:174–178).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: **37 passed, 6 skipped**. The dispatched failure is not reproducible.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1326 findings /
  1326 reviewed identities, zero unclassified and never_allowlist. The gate
  selected trusted base e46ad6708fda. No debt warrants a ledger amendment.
- `uv run ruff check .`: **passed**.
- `uv run ruff format --check .`: **passed**, 3195 files already formatted.

Both dispatched repair targets are completed without speculative code changes.
Live PostgreSQL behavior is not established by skipped integration tests.

## Architecture and additional validation

Read the accepted schema evolution (ADR-087), Attempt lease fencing
(ADR-081626-f383), occurrence-claim (ADR-082426-82c7), principal-rate-limit
(ADR-085), and unmeasured-metric (ADR-083026-a91e) decisions. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. Admission uniqueness is not
physical execution uniqueness; process rejoin is not Attempt recovery. ADR-085
provides no waiver of #860's replica-selection requirement. No architecture
change or competing authority is introduced.

- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -x -q`: **74 passed**. Includes actual production limiter instances and
  real child-process resource sampling, alongside mocked HTTP probe regressions.
- `uv run python scripts/check-shipped-surface-truth.py`: **passed**.
- `git diff --check`: **passed**.

The limiter regression at tests/test_soak_promotion_gates.py:439 reproduces
independent allowances for the same identity on both instances: each returns
`[200, 200, 429]`. This matches production rate_limit.py:32 and is not a
cluster-wide-budget proof. The profile explicitly admits workload gaps and
run_soak.py:730 rejects host-process preflight as exact-RC evidence.

- Imported the current driver with `uv run python` and evaluated frozen
  `docs/testing/soak/evidence/m3a-round30-shakedown.json`. Asserted the exact
  failures `['sustain_duration', 'exact_rc_artifact']`: **420.08 seconds** versus
  **14400 minimum**, topology `host-uvicorn-preflight`, not the production
  Compose image/configuration. Also asserted `preflight_artifact_check()['ok']`
  is false. This is reevaluation of historical evidence, not a new soak.
- `uv run pytest packages/maistro-core/tests/persistence -x -q`:
  **604 passed, 290 skipped**, 27 SQLite datetime-adapter deprecation warnings.
  Skipped database tests are not claimed as live PostgreSQL validation.

## Acceptance disposition

| # | Criterion | Executed evidence / remaining gap |
| --- | --- | --- |
| 1 | Representative release-candidate load profile | **UNVERIFIED complete.** Inspected m3a-load-profile.md:152: one key, no concurrent user/Workspace population, Graph fan-out, successful tool/model or Design/Canvas workload. Inclusion/exclusion against an immutable RC remains necessary. |
| 2 | At least two deployed application replicas | **UNVERIFIED for RC.** Two production-middleware instances tested; host-process preflight is not the promoted multi-service deployment. |
| 3 | Sustained saturation, reclaim, retries, memory and descriptor/process leaks | **UNVERIFIED.** Historical duration fails the current evaluator. Passing process-sampler tests do not establish long-window runtime behavior. |
| 4 | No duplicate physical work across schedules/tasks/Runs/Attempts; Goal reconciliation | **UNVERIFIED.** Admission probe regressions pass; profile records its raced schedule Run is cancelled without execution. No physical Attempt or Goal soak executed. |
| 5 | Replica-selection-resistant rate/security/degraded behavior | **UNVERIFIED as a whole; contrary rate evidence reproduced.** Same identity gets a fresh allowance on replica 2. Local overload rejection cannot demonstrate a shared budget. |
| 6 | Complete PostgreSQL/loop/worker/RSS/descriptor/queue/error telemetry with thresholds | **UNVERIFIED.** Profile has thresholds, but explicitly lacks application-loop, detached-worker and long-window measurements. Driver-loop observations are not application-loop observations. |
| 7 | Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED.** Boot cleanup tests pass; no fresh in-flight physical-work recovery drill. Process exit/rejoin alone is insufficient. |
| 8 | Long soak of exact RC artifact/configuration; rerun after changes | **UNVERIFIED / BLOCKED.** Executed evaluator rejects artifact and duration; extending the current host-process run cannot establish image/config equivalence. |
| 9 | Findings filed/reclassified to earliest broken milestone invariant | **UNVERIFIED complete.** Human evidence contains classifications and outstanding filing instructions; no external filing authorized or performed. |
| 10 | Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for RC.** Both historical formats inspected; machine evidence is explicitly preflight and fails promotion evaluation. |

## Final handoff

**BLOCKED** for issue #860 acceptance. No new failing CI check was found, so no
source, test, ledger, grant or gate was edited. Only this report changed; no
inventory note is required because no test count changed. No merge, push,
GitHub mutation, service startup, background command or full-tree pytest run.
The branch's existing work is preserved.

Next prerequisite: provide the selected immutable RC artifact/configuration and
complete a production-path workload/telemetry runner; resolve replica-selection
protection; then execute the minimum four-hour profile and correlate physical
Attempt fencing/recovery. Do not redispatch the historical schema or vulture
failure as though it remains reproducible. Repeating short preflight runs or
passing CI cannot meet the missing deployment acceptance criteria.

Progress: `{checked: 3, done: 2, skipped: 1, errors: 0, next: exact-RC acceptance}`.
The skipped item is a fresh exact-RC soak; its prerequisites remain unresolved.
This locally committed handoff is not integration or promotion approval.
