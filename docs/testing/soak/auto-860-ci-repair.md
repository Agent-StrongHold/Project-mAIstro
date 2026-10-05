# Issue 860 CI repair checkpoint

## Frozen scope

- Assigned issue: #860 only; starting HEAD `f01554433a5c40bdf20c3ae71ef1aa276d0c5177`.
- Incoming merge parent: `8a4bc239fe9af429be9faa087916f965e9fb20f7`.
- Preserve all incoming staged changes. Backups: `../incoming-860.patch` and
  `../incoming-860-index.patch`; incoming file snapshot: `/tmp/auto-860-incoming-files.txt`.
- Repair files: conflicted `packages/maistro-server/src/maistro_server/api/tasks.py`,
  `quality/vulture-baseline.json` (explicit CI-repair exception), and this report.
- Read-only validation scope: repository instructions, relevant ADRs, issue dispatch,
  soak harness/profile/evidence/tests, adjacent task admission tests, vulture scan
  identities and their production consumers.

## Initial evidence / ambiguity

The worktree arrived in a merge with one unresolved file and staged changes from
other issues. Assumption: finish that existing merge in place, preserving both
sides' semantics, rather than fetching/restarting a resolved merge target. The
assigned starting HEAD matches. No `check-*.log` files were present in the job
directory's initial listing; prior verification is not assumed valid.

## Status

Initial exact vulture scan exited 1 (log `/tmp/auto-860-vulture.log`). Its
missing task routes and new task response/list identities are consistent with
conflict markers making the route module unparsable; resolve syntax before
classifying these as debt. A trusted-base `POLICY` deletion also appears. No
ledger amendment will be guessed from this invalid intermediate scan.

Adjacent tests inspected: `test_tasks_concurrency_backpressure.py` requires a
ceiling refusal with Retry-After; merged `test_tasks_run_identity.py` also checks
no receipt/Run/claim is retained, replay is preserved, and retry succeeds after
cancellation. Resolve with a scope-only ceiling message and shared chat retry
interval, preserving these two contracts. No new test count is needed: both
regressions already exist, including the incoming inventory note for #1828.

The first guessed ADR filename was not found; skipped in favor of the indexed
`ADR-081-deployment-backup-dr.md`. Prior job result confirms BLOCKED, but current
acceptance will be validated independently.

## Repair validation checkpoint

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2917 files.
- `git diff --check HEAD`: PASS.
- Exact vulture command after resolution: PASS, 1338 findings, zero unclassified
  or never-allowlisted findings. Log `/tmp/auto-860-vulture-resolved.log`.
- Preserved incoming ledger amendment: remove the no-longer-reported `POLICY`
  identity (one row). This is scanner bookkeeping, not proof that
  `ResourceKind.POLICY` acquired a consumer: the incoming promotion module uses
  `PromotionScope.POLICY` at line 90, which satisfies Vulture's name-based use
  tracking. No rules, grants or unrelated ledgers edited by this worker.
  `git diff --numstat MERGE_HEAD -- quality/` is empty: incoming ledgers preserved.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_tasks_run_identity.py
  packages/maistro-server/tests/api/test_tasks_idempotency.py
  tests/test_soak_promotion_gates.py -x -q`: PASS, 67 tests, two deprecation warnings.
  Log `/tmp/auto-860-focused-tests.log`. Includes live ASGI canonical ceiling,
  claim cleanup/replay/retry, real middleware independent allowances, and a real
  uv-child process-group sampler. These are not a two-replica production soak.

## Architecture reconciliation

Accepted ADR-081226-a66b reserves lifecycle ownership for Run/NodeRun/Attempt;
ADR-081626-f383 reserves fencing identity for the canonical store. This repair
only translates canonical admission refusal, adding no authority or scheduler.
ADR-081 is **Proposed**, not an accepted waiver of issue acceptance. The merged
retry convention uses `CHAT_TURN_RETRY_AFTER_S` (5 seconds instead of the lane's
prior 1 second), with a scope-only message retaining the word `ceiling`. This
runtime change itself invalidates older soak evidence.

- Full server suite: `uv run pytest packages/maistro-server/tests -x -q`: PASS,
  495 passed, 8 skipped, 22 deprecation warnings (45.65 seconds). Skips are not
  production acceptance evidence. Log `/tmp/auto-860-server-tests.log`.
- `check-backlog-consistency.py`, `check-adr-index.py`, and
  `check-convergence-matrix.py` (all via `uv run python scripts/...`): PASS.
- Local `origin/develop` resolves to the assigned base
  `d7aa2714519a2c7fa122e3abe6096870e55d2869`; quality-ledger diff against it is
  empty as well. No rows were lost by this resolution.

- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-server/tests`: PASS, 503 collected, expected 503, no duplicate
  evidence. Existing incoming inventory notes cover the merge's added tests;
  this repair adds no tests or count delta.
- Executed the current `failed_promotion_checks` against
  `docs/testing/soak/evidence/m3a-round6-shakedown.json`: exactly
  `sustain_duration` and `exact_rc_artifact` fail. The historical evidence is
  tied to `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this code, and records
  90.43 seconds versus the required 14400. `preflight_artifact_check()` also
  returns `ok=false` on current code. Assertions confirming both passed.
- Read the frozen issue comments and linked PR descriptions/reviews from
  dispatch-context.json, not from a new GitHub fetch. They provide no exact-RC
  soak or waiver of the missing acceptance criteria.

## Acceptance review (all ten criteria)

| Criterion | Current evidence and outcome |
| --- | --- |
| Representative RC workload | PARTIAL: `m3a-load-profile.md:46-69` defines a mix, but `:152-166` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tools/models, Canvas and background Goal reconciliation. Production representativeness UNVERIFIED. |
| At least two application replicas | Production Compose defines two services (`deploy/docker-compose.prod.yml:24-79`); this round ran ASGI fixtures, not those services. Production run UNVERIFIED. |
| Sustained saturation, reclaim, retry, leaks and restart | Historical duration is 90.43 seconds (`evidence/m3a-round6-shakedown.json:163-165`); current evaluator rejects it. Long-window behavior UNVERIFIED. |
| Admission, reconciliation and physical-work fencing | Canonical task admission/claim cleanup/replay/retry tests pass. No live cross-replica physical-work or Goal reconciliation validation in this round: UNVERIFIED. Admission uniqueness is not physical-work uniqueness (ADR-081626-f383). |
| Rate/security/degraded behavior cannot be bypassed by replica choice | NOT PROVEN: `tests/test_soak_promotion_gates.py:439-488` executes real middleware and reproduces fresh allowance on replica 2 for both authenticated and unauthenticated identities. `api/rate_limit.py:25-30` deliberately promises only process-local enforcement. Do not silently replace this policy or waive #860. |
| Required telemetry with thresholds | PARTIAL: profile thresholds and sampler tests exist; real uv-child RSS/FD test passes. App-loop latency, worker counts, PG contention and full long-window telemetry on the RC remain UNVERIFIED. |
| Kill/restart with drain/fencing/recovery | Historical exit/rejoin counters cannot prove physical work fencing. Production recovery on current code UNVERIFIED. |
| Long exact-RC soak | NOT MET: `scripts/soak/run_soak.py:635-668` correctly rejects the host preflight artifact. No exact artifact/config manifest or four-hour run was produced. |
| Findings classified to earliest broken milestone | Existing backlog consistency gate passes; complete classification of all load findings UNVERIFIED. No GitHub mutations performed. |
| Machine/human evidence bound to exact hashes | Historical JSON/docs exist, but code hash differs and no current RC image/config soak exists. Current promotion evidence UNVERIFIED. |

## Handoff and residual risk

**BLOCKED for #860 acceptance; merge-conflict / vulture repair complete.** This
worker changed the task route resolution and this report, and preserved the
incoming vulture prune plus every other staged merge change. No soak gates were
weakened and no new execution or authorization path was introduced.

The production Compose is explicitly a reference artifact, requires real gateway
configuration, and builds rather than identifying an immutable RC image. Running
the host emulator for longer would not fix those evidence gaps. Next owner must
select and freeze the exact RC deployment, complete the representative workloads
and physical-effect probes, reconcile the rate-limit requirement with the declared
per-process policy, and run a new >=4-hour instrumented soak after code/config freeze.

Focused validation does not certify unrelated incoming core/Hive behavior; those
changes are preserved from the merge, not reimplemented or broadly tested here.
No driver `check-*.log` files were supplied in this job directory.

Progress: checked 1 assigned issue; CI repair done 1; skipped 0 issues; acceptance
blocked 1. Preserve the local salvage patches for provenance. No push, PR update,
issue comment or closure is authorized or performed.
