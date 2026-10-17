# Issue #860 — exact-debt-ledger repair recheck (6eb9c316)

## Frozen scope and disposition

One assigned item: #860 on `auto-860`, worktree `/home/dev/Git/wt/auto-860`.
Starting HEAD: `b05bb725e5044364aafea234a1fc8f17ac82363a` (clean).
Supplied develop base: `291bdd187a512a9cda5a33cb98cff655564d7f4d` (resolved).
The supplied dispatch snapshot and prior result were treated as evidence, not
acceptance authority. No remote lists were refreshed or GitHub objects mutated.
The job directory initially contained no driver `check-*.log` files.

**BLOCKED for #860 acceptance. No reproducible vulture repair is needed.**
The exact CI scan passes with 1,342 findings matching 1,342 reviewed identities,
zero unclassified findings and zero never-allowlist findings. A second scan
using the supplied base explicitly also passes. No source or ledger amendment
is justified by this evidence. This round changes only this validation report;
no test additions or inventory delta are needed.

## Independently executed validation

Logs are local artifacts in
`/home/dev/maistro/jobs/6eb9c31681e843b891dd42f040a95fee/`.
Commands ran in the assigned worktree with 1,200-second timeouts.

| Command | Outcome / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0; 1,342 matched identities. `check-vulture-local.log`. Arguments match `.github/workflows/quality.yml:982-985` and `vulture-ratchet.yml:82-85`. Default resolver reports merge base `c560d4ccad82`, not the supplied develop tip. |
| Same scan with `RATCHET_BASE_REV=291bdd187a512a9cda5a33cb98cff655564d7f4d` | Exit 0; `check-vulture-explicit-base.log`. Explicit base selection follows `scripts/ratchet_provenance.py`; no gate modification. |
| `uv run ruff check .` | Exit 0, all checks passed; `check-ruff-local.log`. |
| `uv run ruff format --check .` | Exit 0, 2,985 files formatted; `check-format-local.log`. |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 75 passed in 2.79 seconds; `check-pytest-local.log`. Not a deployed soak. |
| `git diff --check 291bdd187a512a9cda5a33cb98cff655564d7f4d...HEAD` | Exit 0; historical whitespace finding does not reproduce against assigned base. `check-diff-local.log`. |
| `uv run python scripts/check-ratchet-provenance.py` | Exit 0; 49 consumers have explicit provenance and delegated gates pass. Existing syntax/CORS warnings; `check-provenance-local.log`. |
| `uv run python scripts/check-shipped-surface-truth.py` | Exit 0; matrix complete. `check-shipped-local.log`. |
| `uv run python -` importing current `run_soak.py` and evaluating retained round-6 JSON | Assertions pass: failed promotion checks are exactly `sustain_duration` and `exact_rc_artifact`; 90.43 seconds versus 14,400 required. `check-evidence-local.log`. Passing rejection assertions are **not** a passing soak. |

The existing tests exercise the real production middleware, HTTP probe error
paths, CLI artifact rejection, admission backpressure and a real uv child-process
sampler. `maistro_server/main.py:627` installs the middleware in the production
app. The replica-selection test (`tests/test_soak_promotion_gates.py:439-488`)
observes `[200, 200, 429]` independently on two instances for the same identity,
both authenticated and pre-auth. This is meaningful evidence of process-local
budgets, but not an execution of the production deployment.

## Acceptance matrix

| Issue criterion | Executed evidence or remaining gap |
| --- | --- |
| Representative release-candidate profile | **UNVERIFIED.** Existing profile omits concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Canvas and Goal/background-worker workloads (`m3a-load-profile.md:152-164`). No complete representative workload executed. |
| At least two deployed application replicas | **UNVERIFIED for RC.** `deploy/docker-compose.prod.yml:26-77` declares two servers, but is a reference build configuration, not an identified immutable RC. Tests instantiate two middleware apps, not deployed replicas. |
| Sustained saturation, queue growth, reclaim, retry and leaks | **UNVERIFIED.** Current evaluator rejects retained 90.43-second shakedown. No fresh long-running load executed. |
| Exactly-once/fenced physical work and Goal reconciliation | **UNVERIFIED.** Retained schedule probe admits then cancels a Run; admission uniqueness does not prove physical Attempt uniqueness. Profile lines 197-200 explicitly preserve this gap. |
| Security/degraded behavior cannot be bypassed by replica selection | **NOT MET for a cluster-wide allowance.** Executed production middleware counterexample demonstrates a fresh allowance on replica two. `rate_limit.py:25-30,72-76` deliberately specifies process-local state. Local rate-limit/backpressure tests pass; sustained production security/degraded behavior remains unverified. |
| Required telemetry with explicit thresholds | **UNVERIFIED.** Driver-loop lag is not application-loop lag; process-group sampler tests are not deployed worker-count or leak observations. Profile lines 157-164 state these limits. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED.** Historical process exit/rejoin and terminal Run counts do not demonstrate absence of lost/duplicated physical work. No new production fault injection. |
| Long-running exact RC artifact/configuration | **NOT MET.** `run_soak.py:635-646` rejects host-uvicorn preflight unconditionally. CLI regression tests pass for rejection even with synthetic four-hour evidence. Extending this emulator cannot satisfy exact-artifact acceptance. |
| Findings classified to earliest broken milestone invariant | **UNVERIFIED completeness.** Existing finding records preserved. No fresh production run or GitHub mutation; no claim that all findings are dispositioned. |
| Published machine/human evidence bound to exact current hashes | **UNVERIFIED for RC.** Retained JSON names `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned head, and lacks promoted application-image identity. This report is validation evidence, not a replacement soak. |

## Architecture and next action

Read accepted ADR-081226-69ee (Graph/Node execution), ADR-081426-1f7c
(ExecutionRuntime mechanics), ADR-081626-f383 (Attempt lease/fencing), and
ADR-085 (principal rate limiting). Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`; no new scheduler, store, authorization path or execution authority.
Physical execution evidence must observe canonical Attempts, not substitute
admission identity counts. ADR-085's principal keying is not evidence of shared
replica state. ADR-081 (deployment) is **Proposed**, not an accepted waiver of
exact-artifact or recovery requirements.

Before another acceptance attempt, identify the immutable RC/configuration and
provide a runner that actually exercises it with representative workloads,
application telemetry, physical-work recovery observations and at least four
hours of fresh load. Resolve the process-local versus replica-non-bypass scope
explicitly; do not silently weaken the criterion or add an alternative authority.
Re-running the existing host emulator or editing a matching vulture ledger
cannot remove these blockers.

Checkpoint: checked 1, acceptance-complete 0, skipped 0, validation errors 0.
Next: exact-RC production-soak prerequisites and rate-budget scope reconciliation.
Commit this report locally; no promotion, merge or integration approval implied.
