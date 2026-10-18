# Issue #860 CI repair checkpoint

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `02c33805525dd4f8767d1c8dc8900c40550eb6df`; supplied base `35a72ff54d4f09429cf0b9349ecff7f3e9396f5d`.
- Process only issue #860 and its supplied dispatch/prior-result evidence. No remote mutations or ref changes.
- Candidate repair files: `quality/vulture-baseline.json` (explicitly permitted CI repair), `docs/testing/inventory-notes/issue-860-ci-repair.md` (only if an inventory discrepancy is reproduced), and this report. Read-only inspection of soak runner/tests, inventory/vulture gates, deployment configuration, instructions and relevant ADRs.
- Starting tree clean; no salvage required. Supplied job directory contains no `check-*.log` files. Prior result is BLOCKED, to be independently checked.
- Assumption: this is the writer CI-repair lane, not the read-only verifier role. A real RC deployment/artifact cannot be inferred from historical preflight evidence.

## Progress

The requested vulture command passed: 1322 findings, 1322 reviewed identities,
zero unclassified and zero never-allowlist. No ledger amendment is justified.
The scoped inventory command passed: `tests/` expected/collected 5354, with zero
duplicate evidence. The supplied 5353/5354 discrepancy is not reproducible at
this HEAD; no inventory amendment is justified. No tests were added.

Executed successfully (1200-second command timeout):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
- `uv run python scripts/check-suite-inventory.py --suite tests/`
- `uv run ruff check .` — all checks passed.
- `uv run ruff format --check .` — 3306 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` — 85 passed.

The executed production-middleware test still reproduces independent replica
allowances for authenticated and unauthenticated identities. Passing the tests
therefore does not satisfy replica-selection resistance. The profile explicitly
leaves representative workloads and physical-work fencing unproven. Acceptance
review and historical evidence evaluation are complete; no production code or
gate changes are warranted by these CI results.

## Additional executed validation

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-server/tests`
  — passed, 574 collected, zero duplicate evidence.
- `uv run pytest packages/maistro-server/tests -x -q` — 566 passed, 8 skipped,
  22 deprecation warnings in 41.83 seconds. Skipped cases are not acceptance proof.
- Imported `scripts/soak/run_soak.py` using `importlib.util` under `uv run python`,
  loaded `docs/testing/soak/evidence/m3a-round30-shakedown.json`, and asserted
  `failed_promotion_checks(evidence) == ['sustain_duration', 'exact_rc_artifact']`.
  Assertion passed; observed duration was 420.08 seconds. Also executed
  `preflight_artifact_check()`: `ok=False`, topology `host-uvicorn-preflight`.
  This is reevaluation of historical evidence, not a new soak.

## Architecture reconciliation

Read accepted ADR-081226-69ee (Graph/Node execution), ADR-081426-1f7c
(ExecutionRuntime), ADR-081626-f383 (lease fencing), and ADR-085 (quota/rate
limiting). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; no authority
was added. Lease fencing explicitly does not establish expiry takeover or
recovery-driven supersession. Consequently an admission race cannot be promoted
to evidence of physical-work reclaim. ADR-085 requires per-principal limiting;
the current implementation documents process-local limits. That documentation
is not a waiver of #860's replica-selection acceptance criterion. A distributed
limiter or new reclaim authority is not invented in a ledger-repair round.

## Acceptance review

| #860 criterion | Evidence and disposition |
| --- | --- |
| Representative RC users/Workspaces and request mix, fan-out, schedules, tools/models, Canvas, workers | **UNVERIFIED.** `m3a-load-profile.md:167-183` records absent workloads. The preflight's single key and degraded provider path cannot substitute for them. |
| At least two application replicas | **UNVERIFIED for the RC.** `deploy/docker-compose.prod.yml:23-78` defines two replicas; the executed ASGI tests use production middleware/router but are not deployed replicas. |
| Sustained saturation, queue growth, expiry/reclaim, retries, leaks, restart | **UNVERIFIED.** Historical evidence is 420.08 seconds; executed evaluator fails duration. No new soak was run. |
| No duplicated physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED.** `m3a-load-profile.md:215-217` states the occurrence probe cancels its queued Run without executing it; no physical Attempt/Goal proof follows. |
| Effective security/degraded enforcement without replica-selection bypass | **Counterexample reproduced.** `tests/test_soak_promotion_gates.py:477-526` uses production middleware with the same IP/credential: each replica independently returns `[200, 200, 429]`. Local enforcement works, cluster-wide allowance does not. |
| Complete telemetry with explicit pass/fail thresholds | **UNVERIFIED.** Profile defines partial thresholds, but `m3a-load-profile.md:180-183` distinguishes driver lag from application lag and leaves worker counts and saturation unproven. |
| Kill/restart during work proves drain/fencing/recovery | **UNVERIFIED.** Passing harness accounting/boot tests do not establish recovery of physical work in the RC. |
| Long-running soak of exact promoted RC/config | **Failed historical evidence.** Executed evaluator returns `sustain_duration` and `exact_rc_artifact`; runner's artifact check explicitly returns false (`scripts/soak/run_soak.py:744-755`). No exact promoted RC identity was supplied for a new run. |
| File/reclassify load findings at earliest broken invariant | **UNVERIFIED externally.** Local report retains rate-limit (#842) and physical-fencing (#850) gaps. No GitHub mutations permitted or performed. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for promotion.** Historical JSON and profile exist, but are explicitly preflight evidence; they cannot attest the exact promoted artifact. |

## Outcome and next action

**BLOCKED**, not merge-ready. Changed only this report. No production edits,
test additions, inventory adjustments, or vulture ledger changes were justified.
The requested CI repair checks are green; the previous operational block cannot
be resolved by changing documentation or by another short emulator run.

Next: identify the immutable RC image/configuration and approved representative
workload, resolve the replica-selection enforcement contract through the existing
security authority, then execute and publish the required >=4-hour production
soak with physical-work/recovery and complete telemetry observations. Any runtime
change requires a fresh soak. Do not rerun this CI-only repair expecting it to
supply operational acceptance evidence.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
errors 0 validation commands; next is the operational RC soak work above.
This handoff is committed locally; no push or integration approval.
