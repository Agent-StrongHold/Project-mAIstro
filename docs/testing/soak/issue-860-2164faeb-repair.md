# Issue #860 — 2164faeb repair validation

## Scope and checkpoint

Single assigned issue #860; branch `auto-860`; initial clean HEAD
`21a7a966c85689cdb9bc34414d7f6e5b7a3732d9`; supplied base
`435dc1937e0407ab4de198ffcced49860bb14ad2` resolves locally.
Frozen scope and command logs are in job directory
`/home/dev/maistro/jobs/2164faebfad6477a98531328149ed6e5`.
No current driver `check-*.log` was present at the initial directory snapshot.
The supplied historical `98a11313.../check-3.log` fails a schema assertion
(24 statements observed versus 21 expected), not a vulture identity check.

Fresh mandatory vulture scan passed: 1323 findings / 1323 reviewed identities,
zero unclassified or forbidden findings; gate-selected base `4aa68edc0b6b`.
No unbanked retained identity exists to amend. No ledger or source change is
justified by that scan. Fresh combined schema/soak/backpressure tests exited 0;
detailed results and acceptance review follow below.

Fresh regression result: **103 passed, 6 skipped in 2.67s**. Both global Ruff
checks passed. Historical schema mismatch is absent: the independent expected
DDL list includes the three validation audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:173–175`.
No tests changed, so inventory delta is zero and no inventory note is required.

Assumption: this is a writer repair round, not authority to designate a release
candidate or waive release acceptance. The prior BLOCKED result is not taken
as proof. Exact RC/configuration designation remains an input to establish,
not something to infer from a host-process preflight.

## Executed validation

All commands ran in the assigned worktree; scan timeout 600 seconds, remaining
validation timeouts 1200 seconds. Logs named `worker-*.log` are in the job
directory above.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1323/1323, same arguments as `.github/workflows/vulture-ratchet.yml:82–85` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | PASS; 103 passed, 6 skipped |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3270 files already formatted |
| `uv run python scripts/check-deployment-claims.py` | PASS; named components exist, not a live deployment certification |
| `uv run python scripts/check-merge-markers.py` | PASS |
| `uv run python scripts/check-backlog-consistency.py` | PASS; 168 items |
| `git diff --check` | PASS |

Read accepted ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a and ADR-085.
The later b36a contract extends lease fencing with canonical renewal/reclaim;
restarting a replica does not authorize cancelling another replica's live work.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`, existing execution and
principal authorities. No alternate scheduler, recovery worker or auth resolver
was introduced. ADR-085 principal identity does not establish a shared replica
budget; the documented per-process scope cannot waive #860's non-bypass claim.

## Acceptance review

All ten issue criteria are checked below. Passing harness regressions are not
substituted for production load observations.

| Criterion | Evidence / disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED.** `m3a-load-profile.md:151–170` lists missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and background reconciliation. Applicability must be established for the selected RC. |
| At least two deployed application replicas | **UNVERIFIED.** `deploy/docker-compose.prod.yml:26–78` defines two services, but this round did not boot an RC deployment. The middleware regressions use ASGI instances, not deployed replicas. |
| Sustained saturation, growth, reclaim, backoff and leak observations | **UNVERIFIED.** Fresh tests completed in 2.67 seconds; no sustained production time series was collected. |
| No duplicate physical work for schedules/tasks/Runs/Attempts/Goals | **UNVERIFIED.** `m3a-load-profile.md:193–203` limits the schedule probe to one occurrence followed by cancellation without execution. Mocked receipt regression tests prove admission evaluator behavior, not physical-work uniqueness. |
| Rate/security/degraded non-bypass across replicas | **UNVERIFIED at release scope; independent allowances reproduced.** Passing `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` on each real middleware instance for the same identity. `api/rate_limit.py:93` creates local state; `maistro_server/main.py:648` installs it in production. The real task router/spine backpressure test passes, but is not a distributed security soak. |
| Complete telemetry and explicit pass/fail thresholds | **UNVERIFIED for RC.** Profile provides thresholds but explicitly lacks application-loop/worker and long-window evidence. Driver loop latency cannot establish application loop latency. |
| Active-work kill/restart, graceful drain, fencing and recovery | **UNVERIFIED.** No fault injection against a deployed RC in this round. Process rejoin or terminal rows alone cannot prove recovery without physical duplication/loss. |
| Long-running exact RC/config soak; rerun after runtime changes | **UNVERIFIED / BLOCKED.** No selected immutable RC/config supplied by the assignment. `scripts/soak/run_soak.py:730–741` returns `exact_rc_artifact.ok=false` for its host topology. The fresh CLI regression at `tests/test_soak_promotion_gates.py:106` rejects synthetic four-hour records with absent/null/preflight identity; it is not a four-hour execution. |
| Findings filed/reclassified before promotion | Limitations recorded locally in this report; external filing/reclassification **UNVERIFIED**. No GitHub mutations are authorized and no fresh sustained-load finding was generated. |
| Machine/human soak evidence bound to exact image/package/commit/config hashes | **UNVERIFIED for RC.** Fresh test logs are tied to the starting source HEAD above, but no corresponding RC image/config or long-run machine evidence was produced. Historical artifacts were not recertified. |

The historical schema failure is resolved in the existing tree: the current test
asserts all 24 statements inside a transaction and advisory fence, matching
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–216`.
Its six skipped tests do not establish live PostgreSQL concurrency safety.

## Handoff

**BLOCKED**, not integration/promotion approval. Only this report changed;
source, tests, inventory, and quality ledgers are unchanged. The reported CI
symptoms are absent on fresh execution, so speculative edits would not repair
actual evidence. No merge conflict or incoming uncommitted work existed.

Next required input: release owner designates the immutable RC/config and
supported workload applicability. Then complete representative production-path
traffic, physical-work/recovery observations and telemetry, resolve the
replica-selection acceptance gap through canonical security, and execute the
long-running exact-artifact soak with hash-bound evidence. Do not repeat a
four-hour host emulator run as a substitute or silently relax the gates.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`.
Local report commit is the checkpoint; inherited branch-wide changes are not
certified by these focused checks.
