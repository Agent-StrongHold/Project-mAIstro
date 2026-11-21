# Issue #860 bounded repair — d9ace7ba

## Frozen scope

- Issue: #860 only; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `9bb00b0c1a5b655312bcd6ab0a2df2dfb827058d` (verified); supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Working tree was clean. No salvage or merge conflict was present.
- Read-only evidence: supplied dispatch-context.json, prior result 3b9e4b46, prior check-3.log 98a11313, repository instructions, soak runner/profile/tests, relevant ADRs and CI checker.
- Candidate edits: this report and `quality/vulture-baseline.json` only if the explicitly requested exact scan establishes reviewed ledger changes are needed. No new test planned without a demonstrated regression.
- No PR processing, remote mutations, re-enumeration of issues or changes to execution/security authority.

## Initial observations and assumptions

The supplied prior result says BLOCKED on missing exact RC deployment evidence, not a develop merge conflict. Treat all prior success claims as unverified until rerun. No check-*.log files were present in this job directory at inspection. The supplied earlier check log will be read separately. An RC artifact/configuration must be designated rather than invented by this worker.

## Validation

Executed with a 1200-second timeout:

- `uv sync --locked --extra dev`: passed (256 resolved, 214 checked).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, 1323 reviewed identities / findings, zero unclassified. Gate-selected base `4aa68edc0b6b`. No evidence warrants a ledger amendment.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 37 passed, 6 skipped. The supplied prior check-3 failure (24 DDL statements versus 21 expected) does not reproduce.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 66 passed. These are focused regression checks, not a deployed RC soak.

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3270 files already formatted.
- `uv run python scripts/check-suite-inventory.py`: passed, 17 suites match; 31128 unique identities, zero duplicate evidence.

One read-only discovery command included nonexistent README globs; recorded as not found and skipped, with the actual `m3a-load-profile.md` read instead. No refs were fetched or substituted.

## Evidence review and architecture

Read accepted ADR-081226-69ee (Graph/Node execution), ADR-081626-f383
(Attempt fencing), ADR-082526-b36a (lease renewal/reclaim), and ADR-085
(per-principal rate limits). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
The later renewal/reclaim ADR extends the earlier fencing ADR's deferred recovery
boundary; that deferral cannot waive this issue's recovery acceptance. No execution,
scheduler, persistence, event or authorization authority was changed.

The independent expected DDL list already includes all three Gauntlet audit
columns at `packages/maistro-core/tests/persistence/test_pg_learnings.py:173–178`;
these match `_EPISTEMIC_COLUMNS` in the production store. The existing test asserts
transaction boundaries, advisory-lock ordering, and the complete DDL body. Fresh
execution disproves the supplied stale failure; no new test or inventory delta is
needed. Six PostgreSQL-dependent tests skipped, so this is not live database proof.

`packages/maistro-server/src/maistro_server/main.py:648` installs the same
`RateLimitMiddleware` exercised by the executed tests. Its constructor creates an
`InMemoryRateLimiter` (`api/rate_limit.py:93`); its module explicitly documents
N-times aggregate allowance across N replicas. The test at
`tests/test_soak_promotion_gates.py:439` obtains `[200, 200, 429]` independently on
each replica for the same authenticated or unauthenticated identity. ADR-085's
per-principal policy does not make this proof of #860's stronger replica-selection
non-bypass requirement. Resolving the policy/deployment discrepancy remains a
prerequisite, not permission to introduce a new limiter in this repair.

## Acceptance matrix — BLOCKED

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC load profile | UNVERIFIED. Read `m3a-load-profile.md`: it explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal/background-worker traffic. No designated RC configuration establishes which exclusions are valid. |
| At least two deployed application replicas | UNVERIFIED. Executed tests instantiate separate middleware apps; they do not deploy two RC images. |
| Sustained saturation, queue growth, expiry/reclaim, backoff and leaks | UNVERIFIED. Process sampler regression tests pass, but no long-running RC workload was executed. |
| No duplicate physical work across replicas | UNVERIFIED. Receipt-identity checks pass; the schedule probe cancels its unexecuted Run (`scripts/soak/run_soak.py:1044`). Admission uniqueness is not physical-work uniqueness or recovery proof. |
| Rate/security/degraded non-bypass | UNVERIFIED at deployment grade. The executed production middleware test demonstrates independent replica allowances; the server task test proves retryable 429 backpressure and readmission, not cluster-wide limits. |
| Complete telemetry with explicit thresholds | UNVERIFIED. `scripts/soak/run_soak.py:1410` samples driver loop lag, not application loop lag. No fresh RC database/process/queue/error series was collected. |
| Kill/restart during active work; drain/fencing/recovery | UNVERIFIED. Harness cleanup/gating regressions pass, not a deployed active-work recovery experiment. |
| Long soak of exact RC artifact/configuration | BLOCKED / UNVERIFIED. Dispatch does not designate immutable RC images/runtime configuration. `scripts/soak/run_soak.py:730` returns `ok: false` for the host topology, and line 1552 incorporates that gate in emitted evidence. Synthetic four-hour CLI tests prove refusal, not four hours of traffic. |
| Findings filed/reclassified before promotion | Local disposition recorded here. External filing/reclassification UNVERIFIED; GitHub mutations prohibited. |
| Machine/human soak evidence tied to exact hashes | UNVERIFIED. This report identifies the tested source HEAD, but is not a deployed RC evidence pack. |

## Handoff

Changed file: this report only. No code, tests, inventory notes, grants or ledgers
were changed because fresh checks found no actionable regression in the assigned
CI repair. Existing work remains intact. All validation above ran against the
starting source HEAD with only this documentation file uncommitted.

Required next input: designate immutable RC artifacts/configuration and supported
workload applicability; resolve the replica-rate policy discrepancy; run the exact
multi-replica topology for at least four sustained hours with physical-work
witnesses, complete telemetry and active-work restart/recovery. Merely extending
the host preflight cannot satisfy acceptance. Do not redispatch the same stale
schema/scanner failure as evidence of a current regression.

Progress: checked 1 issue; done 0 (release acceptance blocked); skipped 0 issues;
validation errors 0. The missing optional README paths were inspection misses,
not failed validation. Commit this report locally as the required handoff, not
integration approval. No push, merge or GitHub mutation performed.
