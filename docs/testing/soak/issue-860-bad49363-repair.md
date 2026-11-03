# Issue #860 — CI repair validation, job bad49363

## Scope and outcome

**BLOCKED for promotion.** Assigned branch/worktree: `auto-860`,
`/home/dev/Git/wt/auto-860`. Starting HEAD verified as
`8b9f8026b4382fb13095afb8ee9484244a5ede9b`; supplied develop base
`053f93969b4dd607ee64d271e9c8d91f13ececc1`. Initial worktree clean.
Frozen scope: issue #860 soak harness/profile/evidence, adjacent tests and the
explicit vulture per-identity CI repair. No other issue processed.

The job directory contained no `check-*.log` files. Read the previous result
(job `75188967`) but independently executed the checks below. The requested
vulture failure did not reproduce: no unbanked identities, so no ledger
amendment or dead-code deletion is justified. Only this handoff changed;
no new tests, inventory delta, source/configuration edits or GitHub mutations.

## Executed validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS; 1,359 reviewed identities / 1,359 findings, zero unclassified or never-allowlist. Resolved ratchet base `15157c6f2bc5` is distinct from the supplied develop base.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS; 2,774 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`: **88 passed, 5 skipped**, 2.84 seconds. Skips explicitly require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL proof.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS; 19 classified/discovered lifecycles.
- `uv run python scripts/check-merge-markers.py`: PASS.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info`: FAIL (exit 1), cannot connect to Docker daemon. No live container soak attempted after this prerequisite failed.
- Via `uv run python`, imported the existing `failed_promotion_checks` evaluator and asserted rejection for both `sustain_duration` and `exact_rc_artifact` on exactly four historical packs: `m3a-soak-evidence.json`, `m3a-repair-validation.json`, `m3a-round5-final.json`, `m3a-round6-shakedown.json`. All assertions passed. Last two durations are 90.17 and 90.43 seconds. This checks stored verdicts, not the independent accuracy of historical measurements.

## Architecture and reachable behavior

Read repository instructions, documentation authority map, and accepted
ADR-081626-f383 (Attempt lease/fencing), ADR-082126-f69c (recurrence produces
Runs), ADR-085 (principal-keyed rate limits). Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`: schedule admission uniqueness
is not physical Attempt uniqueness, and a second scheduler/store is not a fix.
ADR-085 does not establish cluster-wide limiter storage; issue #860's stronger
replica-selection criterion remains unmet, not waived by local enforcement.

Production installs `RateLimitMiddleware` at `maistro_server/main.py:588`;
`api/rate_limit.py:72` creates a process-local limiter, consistent with its
scope declaration at lines 25–30. Executed middleware tests at
`tests/test_soak_promotion_gates.py:439` show the same authenticated or
unauthenticated identity receiving `[200, 200, 429]` on each independent
instance. These are meaningful production-middleware regressions, not a live
multi-replica soak. The old H3 shared-store claim is already corrected in
`m3a-soak-evidence.md:171`; do not manufacture another wording repair.

`run_soak.py:635` deliberately fails exact-RC identity for the host-process
preflight. Its schedule probe cancels its queued Run (`run_soak.py:970`), so
it cannot establish physical-work fencing. The production Compose artifact
is explicitly a reference requiring digest pinning (`deploy/docker-compose.prod.yml:11`).
No immutable RC/configuration designation was supplied in this job.

## Acceptance disposition

| Criterion | Executed evidence / remaining gap |
|---|---|
| Representative release-candidate profile | PARTIAL: profile defines mix/phases/thresholds; its remaining-gaps section omits concurrent users/Workspaces, fan-out, successful model/tool calls, Design/Canvas and sustained Goal/background-worker traffic. RC applicability UNVERIFIED. |
| Two application replicas | Declared in production Compose; live exact-RC replicas UNVERIFIED (Docker unavailable). |
| Sustained saturation, growth, reclaim, retry, leaks and restart | UNVERIFIED; all four stored packs fail duration/artifact gates. Sampler unit/subprocess tests are not sustained-load proof. |
| Schedule/task/Run/Attempt and Goal physical-work uniqueness | UNVERIFIED; admission/backpressure regressions pass but no physical Attempt correlation under live multi-replica load. |
| Rate/security/degraded non-bypass | Aggregate principal allowance NOT MET: executed middleware regression confirms replica selection provides another allowance. Remaining RC concurrency/security/degraded observations UNVERIFIED. |
| Complete telemetry with thresholds | PARTIAL: documented thresholds and tested process-group sampler; full RC PostgreSQL contention, application-loop latency, worker census, pool saturation and long-window error/leak observations UNVERIFIED. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED; no live deployment. Historical exit/rejoin flags do not prove physical-work recovery. |
| Long-running exact RC artifact/configuration | NOT MET: no four-hour RC soak; host-process runner always fails artifact gate. Docker unavailable and immutable RC/configuration not designated. |
| Findings filed/reclassified before promotion | Local historical findings reviewed; external filing UNVERIFIED. No new load run or GitHub mutations. |
| Machine/human evidence tied to exact hashes | Historical evidence preserved and rejected; qualifying RC image/package/commit/config evidence UNVERIFIED. |

## Handoff

Supply a working container runtime and designate immutable RC images/configuration.
Resolve the aggregate-rate acceptance mismatch through the canonical security
architecture. Complete representative production traffic, physical Attempt
correlation and telemetry, then execute at least four hours on the unchanged
RC. Any subsequent code/runtime-config change requires a fresh soak. Repeating
short host-process preflights cannot unblock promotion.

Progress: checked 1 issue, done 0 (acceptance blocked), skipped 0 issues,
errors 1 (Docker prerequisite). Five PostgreSQL test cases explicitly skipped.
This local validation checkpoint is not integration approval.
