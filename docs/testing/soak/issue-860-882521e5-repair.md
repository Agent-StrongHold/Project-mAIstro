# Issue #860 — repair checkpoint, job 882521e5

Status: **BLOCKED; not promotion or integration approval.**

## Frozen scope

Only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
Verified starting HEAD: `6015cdda4cbcee79e08e86661fe3acbafa27d2a9`.
Supplied develop base: `8c8fc8d6706a0837bd991c4e92138bf4d776ac9e`.
Initial worktree clean; no salvage or sync conflict. Initial job-directory
snapshot has no driver `check-*.log` files. Prior result read at
`/home/dev/maistro/jobs/54dd426ce8314e0cab7fde98a430ecef/result.json`;
its results are not current validation.

Validation snapshot: exact vulture CI command, ruff lint/format, existing
pg-learnings/backpressure/soak-promotion/production-boot tests, deployment and
execution-lifecycle gates, Docker prerequisite, and four existing machine
packs (`m3a-soak-evidence.json`, `m3a-repair-validation.json`,
`m3a-round5-final.json`, `m3a-round6-shakedown.json`). Inspect the corresponding
production seams, profile, evidence report, deployment configuration and
relevant ADRs. Candidate edits restricted to this checkpoint and genuinely
reproduced defects in those seams; ledger edits only for actual scan evidence.
No new issue discovery, GitHub mutation or replacement execution authority.

Ambiguity: no immutable RC image/configuration is designated in the assignment.
Proceed by checking prerequisites and evidence rejection, not by inventing an
RC or treating a host preflight as promotion evidence.

## Fresh validation results

Logs: `/home/dev/maistro/jobs/882521e503364144bc6fd0ee4048233f/check-writer-*.log`.

- Exact requested vulture scan passed: 1,361 findings / 1,361 reviewed
  identities, zero unclassified and zero never-allowlist. The resolved ratchet
  base is `053f93969b4d`, not the supplied develop base. No ledger amendment
  or dead-code removal is justified by this scan.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 2,798 files formatted.
- Targeted pytest: 88 passed, five skipped in 2.45 seconds. All five skips
  require `MAISTRO_TEST_PG_DSN`; they are not live PostgreSQL evidence.
- `DOCKER_HOST=unix:///var/run/docker.sock timeout 90 docker info`: failed
  (exit 1), cannot connect to the Docker daemon. No container soak attempted
  after this prerequisite failure.
- `uv run python scripts/check-deployment-claims.py`: passed (named components
  exist; not runtime deployment proof).
- `uv run python scripts/check-execution-lifecycles.py`: passed, 19 classified
  / 19 discovered work-state vocabularies.
- `uv run python scripts/check-merge-markers.py`: passed.
- An executed `uv run python` import of `failed_promotion_checks` rejects all
  four frozen evidence packs on both `sustain_duration` and
  `exact_rc_artifact`. The last two record 90.17 and 90.43 seconds, not the
  required 14,400 seconds. This checks rejection, not historical measurement
  accuracy.

Exact pytest command:

```sh
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs
```

## Production behavior and architecture

Read repository instructions, documentation authority map, accepted
ADR-081626-f383 (Attempt leases/fencing), ADR-082126-f69c (recurrence produces
Runs), ADR-085 (principal-keyed rate limits), and ADR-081 (still Proposed).
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. Schedule admission
uniqueness cannot be substituted for physical Attempt fencing, and no new
execution or authorization authority is justified here.

- `maistro_server/main.py:588` installs the actual `RateLimitMiddleware`.
  `api/rate_limit.py:25-30,72` documents and constructs process-local state.
  Executed `tests/test_soak_promotion_gates.py:439` confirms the same identity
  receives `[200, 200, 429]` independently on both middleware instances.
  This falsifies an aggregate shared allowance; ASGI instances are not a
  live deployment soak. ADR-085 does not mandate a shared store, but it does
  not waive #860's stronger replica-selection non-bypass requirement.
- `api/tasks.py:117` translates canonical `RunConcurrencyExceeded` into 429
  with `Retry-After`. The executed backpressure test uses the real queue,
  admission spine and router, fills a principal's ceiling, checks independent
  principal admission, frees a slot and retries. It is not cross-replica proof.
- `pg_learnings.py:142` encloses schema DDL in a transaction after an advisory
  lock. The executed schema test asserts statement/transaction ordering using
  a fake connection; no fresh live concurrent-DDL proof is claimed.
- `run_soak.py:635` explicitly rejects exact-RC identity for its host-process
  topology. At `run_soak.py:949-974`, schedule-probe work is cancelled without
  execution. Deployment Compose declares two replicas but is a reference
  artifact requiring deployment-specific image pinning (`:11`).
- The prior H3 shared-store wording is already corrected at
  `m3a-soak-evidence.md:171`. No additional cosmetic wording repair is needed.

## Acceptance disposition

| Criterion | Current executed evidence / gap |
|---|---|
| Representative RC profile | PARTIAL: existing profile defines preflight mix and thresholds, but explicitly lacks multi-user/Workspace, fan-out, successful model/tool, Design/Canvas and Goal/background-worker traffic. RC applicability UNVERIFIED. |
| At least two application replicas | Production Compose declares two; live exact-RC execution UNVERIFIED because Docker is unavailable. |
| Sustained pool/queue/reclaim/retry/leak/restart observations | UNVERIFIED: all four stored packs fail duration/artifact gates; unit sampler tests are not sustained load. |
| Schedule/task/Run/Attempt and Goal physical-work uniqueness | UNVERIFIED: admission/backpressure tests pass, but the schedule probe never executes its Run. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for aggregate allowance: executed production middleware tests demonstrate independent budgets. Live RC security/degraded behavior UNVERIFIED. |
| Complete telemetry with pass/fail thresholds | PARTIAL profile/sampler coverage; production-loop latency, contention, pool saturation, detached workers and long-window leak/error measurements UNVERIFIED. |
| Active-work kill/restart with drain/fencing/recovery | UNVERIFIED: no live RC run; process rejoin is not proof of physical-work recovery. |
| Long-running exact RC artifact/configuration | NOT MET: no qualifying four-hour pack in the frozen evidence; host runner always fails exact-artifact certification. Immutable RC/configuration not designated. |
| Findings filed/reclassified before promotion | Local historical classifications preserved in the evidence report; external filing UNVERIFIED. No new load observation or GitHub mutation. |
| Machine/human evidence tied to exact hashes | Historical packs exist but fail current gates; qualifying RC image/package/commit/configuration evidence UNVERIFIED. |

## Handoff

Only this checkpoint changed. No source/runtime-config, ledger/grant, test or
inventory changes: there is no new test-count delta. The requested vulture CI
failure did not reproduce, so speculative scanner fixes would be unjustified.

Next prerequisites: restore the container runtime and designate an immutable
RC/configuration; resolve the aggregate-rate acceptance mismatch through the
canonical security architecture; complete representative production traffic,
physical-work correlation and telemetry; run at least four hours on the
unchanged RC. Any code/runtime-config change requires another soak. Another
short host preflight or ledger edit cannot resolve these blockers.

Progress: checked 1 issue, done 0 (acceptance blocked), skipped 0 issues,
errors 1 (Docker prerequisite). Five PostgreSQL tests explicitly skipped.
