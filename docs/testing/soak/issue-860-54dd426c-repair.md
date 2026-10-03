# Issue #860 — repair checkpoint, job 54dd426c

**BLOCKED; not promotion or integration approval.** Only issue #860 processed in
`/home/dev/Git/wt/auto-860`, branch `auto-860`. Starting HEAD independently
verified: `977028009dc720cd0920675db89cdffe14789d2f`; supplied develop base:
`053f93969b4dd607ee64d271e9c8d91f13ececc1`. Initial worktree clean. No sync
conflict. The job directory initially contained no driver `check-*.log` files.
Prior result `bad493638d4344989f4f2a242ab924f3/result.json` was read, not treated
as current verification.

## Executed checks

Fresh command output is retained under
`/home/dev/maistro/jobs/54dd426ce8314e0cab7fde98a430ecef/check-*.log`.

| Command | Current result |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,359 reviewed identities / 1,359 findings; zero unclassified or never-allowlist. Arguments match both CI workflows. Resolved ratchet base `15157c6f2bc5`, not the supplied develop base. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 2,774 files already formatted. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 88 passed, 5 skipped in 2.98 s. All five skips explicitly require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL proof. |
| `uv run python scripts/check-deployment-claims.py` | PASS: named components/backends exist; not deployment runtime proof. |
| `uv run python scripts/check-execution-lifecycles.py` | PASS: 19 classified / 19 discovered work-state vocabularies. |
| `uv run python scripts/check-merge-markers.py` | PASS. |
| `DOCKER_HOST=unix:///var/run/docker.sock timeout 90 docker info` | FAIL, exit 1: cannot connect to Docker daemon at the assigned socket. No container soak attempted after prerequisite failure. |

An additional `uv run python` check imported the existing
`failed_promotion_checks` evaluator and asserted both `sustain_duration` and
`exact_rc_artifact` reject each of the four frozen historical packs:
`m3a-soak-evidence.json`, `m3a-repair-validation.json`, `m3a-round5-final.json`,
`m3a-round6-shakedown.json`. PASS; the last two record 90.17 and 90.43 seconds.
This validates rejection of stored evidence, not historical measurement accuracy.

## Reachable behavior and architectural reconciliation

Read repository instructions, documentation authority map, accepted
ADR-081626-f383 (Attempt lease/fencing), ADR-082126-f69c (recurrence produces
Runs), ADR-085 (principal-keyed rate limits), and ADR-081 (still **Proposed**).
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`: neither a second
scheduler nor another execution/authorization authority is warranted here.
Admission uniqueness is not physical Attempt uniqueness.

Production installs `RateLimitMiddleware` at `maistro_server/main.py:588`.
`api/rate_limit.py:25-30,72` declares and constructs independent in-memory
limiter state. Executed tests at `tests/test_soak_promotion_gates.py:439`
exercise that actual middleware: the same identity receives `[200, 200, 429]`
on each instance. This falsifies a shared aggregate allowance; it is not a
live multi-replica soak. ADR-085 does not specify a shared limiter store, but
that does not waive #860's stronger replica-selection acceptance criterion.
The old H3 shared-store claim was already corrected at
`m3a-soak-evidence.md:171`; no additional wording repair is justified.

`run_soak.py:635` always rejects exact-RC identity because the runner starts
host processes, not the promoted Compose artifact. Its schedule probe cancels
its queued Run without execution (`run_soak.py:949-974`). Production Compose
explicitly requires deployment-specific digest pinning (`deploy/docker-compose.prod.yml:11`).
No immutable RC image/configuration designation was supplied in this job.

## Acceptance disposition

| Criterion | Evidence / remaining gap |
|---|---|
| Representative RC profile | PARTIAL: `m3a-load-profile.md` defines a preflight mix/thresholds and explicitly lists missing concurrent users/Workspaces, fan-out, successful model/tool calls, Design/Canvas and Goal/background-worker traffic. Applicability to the selected RC remains UNVERIFIED. |
| At least two application replicas | Declared in production Compose. Live exact-RC replicas UNVERIFIED; Docker unavailable. |
| Sustained saturation, queue growth, reclaim, retry, resource leaks and restart | UNVERIFIED. Four historical packs rejected by duration/artifact gates; sampler regression tests cannot substitute for sustained load. |
| Schedule/task/Run/Attempt and Goal physical-work uniqueness | UNVERIFIED. Admission/backpressure regressions pass; the schedule probe explicitly does not execute its Run. No physical Attempt correlation under multi-replica load. |
| Rate/security/degraded non-bypass | Aggregate non-bypass NOT MET: executed production-middleware tests demonstrate independent replica allowances. Remaining live RC security/degraded behavior UNVERIFIED. |
| Complete telemetry and explicit thresholds | PARTIAL: profile and process-group sampler tests exist. Full RC PostgreSQL contention, application-loop latency, worker census, pool saturation and long-window error/leak measurements UNVERIFIED. |
| Active-work kill/restart with drain/fencing/recovery | UNVERIFIED. No live deployment; historical exit/rejoin flags do not prove physical-work recovery. |
| Long-running exact RC artifact/configuration | NOT MET: no qualifying four-hour RC soak; host runner cannot certify the artifact. Runtime unavailable and immutable RC/configuration not designated. |
| Findings filed/reclassified before promotion | Local historical findings reviewed in `m3a-soak-evidence.md`; external filing UNVERIFIED. No new load observations or GitHub mutations. |
| Machine/human evidence tied to exact hashes | Historical packs preserved and rejected. Qualifying RC image/package/commit/configuration evidence UNVERIFIED. |

## Handoff

The specified CI failure did not reproduce; no unbanked identity or genuine
dead-code fix was identified. No ledger/grant edit, new test, inventory delta,
source/runtime-config change or GitHub mutation. Only this report changed.

Next: provide a working container runtime and immutable RC image/configuration;
resolve aggregate-rate acceptance through the canonical security architecture;
complete representative production traffic and physical-work/telemetry probes;
then run at least four hours on that unchanged RC. Any code/runtime-config
change requires another soak. Another short host preflight cannot unblock this.

Progress: checked 1 issue, done 0 (acceptance blocked), skipped 0 issues,
errors 1 (Docker prerequisite); five PostgreSQL tests explicitly skipped.
