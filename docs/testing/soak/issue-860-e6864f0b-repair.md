# Issue #860 repair checkpoint (e6864f0b)

## Frozen scope

- Assigned issue: #860 only; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Verified starting HEAD: `eac0ae7b3d4fe05c2d84675c7d9a3bfb857cd4d8`; initial worktree clean.
- Base supplied: `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`.
- Input: job `e6864f0bae804b308b7d7fb3db9ff287/dispatch-context.json` (frozen snapshot; no GitHub refresh).
- Files in scope: existing #860 soak implementation/tests/docs and, only if the prescribed scanner supplies actual evidence, `quality/vulture-baseline.json` and implicated retained/dead identities. No other issues or grants.
- Prior result `e0f401c16052413aaeff197cf135fb59/result.json` reports BLOCKED. This is not acceptance proof.
- No `check-*.log` files exist in this job directory at initial inspection. Inspect supplied earlier failing log and rerun validation.

## Assumptions

This is a writer CI-repair round, not authorization to invent a release candidate or to promote preflight evidence. Run the exact vulture gate before deciding whether a ledger repair is needed. Missing exact RC deployment inputs must remain explicitly unverified.

## Architecture reconciliation

Read repository instructions and `docs/README.md`, the load profile, and accepted ADRs 081426-1f7c, 081626-f383, 082526-b36a, and 073126-c4e1. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; runtime mechanics do not mint execution authority. The later lease-renewal/reclaim decision extends the earlier fence contract: the earlier recovery deferral does not waive soak acceptance. Immutable RC provenance prevents substituting a host preflight for the selected release artifact.

## Progress

Exact prescribed Vulture scan executed with a 1,200-second timeout: PASS, 1,326 reviewed identities and findings, zero unclassified and never-allowlist findings (`worker-vulture.log` in the job directory). No evidence supports a ledger amendment. Historical `check-3.log` failed on 24 versus 21 DDL statements; fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` PASS: 37 passed, 6 skipped. The supplied historical failure does not reproduce. Fresh focused soak/boot/backpressure/rate-limit test command PASS: 100 passed (`worker-focused.log`). Initial discovery included nonexistent README globs (no files read or changed); actual load-profile documentation is used instead.

## Executed validation

Commands executed in the assigned worktree with 600–1,200-second timeouts.
Logs are under `/home/dev/maistro/jobs/e6864f0bae804b308b7d7fb3db9ff287/`.

| Command | Outcome / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,326 findings matched; `worker-vulture.log`. Exact CI scan, no ledger amendment needed. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; `worker-schema.log`. Current test independently includes all three Gauntlet columns at lines 175–177; live PostgreSQL skips are not soak proof. |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 100 passed; `worker-focused.log`. Includes negative admission/artifact evidence, real process sampler, production limiter and backpressure coverage. |
| `uv run ruff check .` | PASS; `worker-ruff.log`. |
| `uv run ruff format --check .` | PASS, 3,170 files; `worker-format.log`. |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites / 29,499 unique identities / zero duplicate evidence; `worker-inventory.log`. |
| `uv run python scripts/check-merge-markers.py` | PASS; `worker-markers.log`. |
| `uv run python -` (import current driver and evaluate round-30 evidence) | Assertions PASS: historical evidence fails `sustain_duration` and `exact_rc_artifact`; 420.08 seconds versus 14,400 minimum; current preflight artifact check remains false. `worker-evidence.log`. |

## Acceptance assessment

| Criterion | Current evidence / disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED complete.** `m3a-load-profile.md:153–172` explicitly lacks multi-user/Workspace, Graph fan-out, successful tools/models, Design/Canvas and Goal/background-worker traffic. |
| Two deployed application replicas | **UNVERIFIED for RC.** Executed ASGI tests use separate middleware instances, not deployed RC containers. |
| Sustained saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED.** Current evaluator rejects historical 420.08-second run against the four-hour minimum. No fresh saturation/long-window observations. |
| No duplicated physical work / Goal reconciliation | **UNVERIFIED.** `run_soak.py:1075–1163` races schedule admission then cancels its probe Run; it does not execute physical Attempts or sustained Goal reconciliation. |
| Security/rate/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED as stated; stronger shared-budget interpretation falsified.** Executed `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` independently on both production middleware instances for the same principal/client. `maistro_server/api/rate_limit.py:32–37` documents process-local budgets. Reconcile through the existing security seam, not a parallel authorization mechanism. |
| Full telemetry and explicit thresholds | **UNVERIFIED complete.** Profile documents driver-loop versus application-loop and process-group limitations; no complete long-window pool/worker/leak measurements. Passing sampler tests do not establish deployed application health. |
| Restart during active work, drain/fencing/recovery | **UNVERIFIED.** Boot cleanup/admission tests do not prove physical-work recovery or stale-effect rejection after process death. |
| Long exact-RC/config soak | **BLOCKED / UNVERIFIED.** No selected immutable RC artifact/configuration supplied. `run_soak.py:730–741` deliberately rejects this host preflight. Both artifact and duration checks fail for historical evidence. |
| Findings reclassified to earliest broken invariant | **UNVERIFIED completeness.** Historical findings preserved; no fresh load findings or GitHub mutations. |
| Hash-bound machine/human evidence | **UNVERIFIED for candidate.** Existing evidence is historical, not recertified for this HEAD. This report is local validation only. |

## Handoff

**BLOCKED, not integration approval.** Only this report changes this round; no production/test changes, inventory delta, grants or ledger changes. The supplied historical test failure is already repaired and the exact scanner is clean, so no evidence-backed CI code repair remains. No develop-sync conflict was present; no remote refresh/merge was needed.

Provide the selected immutable RC image/package/config hashes and supported deployment contract, reconcile replica-budget acceptance, then run the complete representative production campaign with at least four hours of sustained traffic, application telemetry and active-work fault injection. Repeating this CI-repair lane without those prerequisites cannot establish acceptance. No new tests were added because no implementation changed; existing meaningful regressions were executed instead.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "selected RC and production acceptance execution"}`. Local validation complete; issue acceptance remains unresolved.
