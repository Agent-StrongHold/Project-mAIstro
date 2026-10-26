# Issue #860 repair — job 5599c6a1

## Frozen scope

- One issue: #860; branch `auto-860`; starting HEAD
  `113fadc1a3c13e78d6611e3c3b0c9bf65220d88a`; supplied base
  `2154f845347c9541016288c760f8da3f5cd2e064`.
- Clean starting worktree. No conflict or incoming uncommitted work.
- Review inputs: supplied dispatch snapshot, prior result 2d2f868d, and
  reported failing `98a11313/check-3.log`. No check logs were supplied in
  the current job directory.
- Production/test review scope: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, core persistence schema fence and
  its adjacent test, server rate-limiter/admission wiring, load profile,
  relevant ADRs and CI gate scripts/workflows.
- Allowed repair files: this report, the schema-fence test and its inventory
  note if the reported failure reproduces, and `quality/vulture-baseline.json`
  only if the exact scan demonstrates reviewed retained identities.
- Assumption: this is a writer repair, not the read-only verifier role.
  A prior BLOCKED result is an acceptance-evidence blocker, not proof of a
  develop sync conflict. No GitHub changes or ref synchronization needed.

## Initial evidence

The supplied historical failure reports 24 fenced DDL statements versus 21
expected. The previous result reports independent replica rate allowances
and no exact-RC promotion evidence; these claims require fresh checks.

## Fresh checkpoint

- Exact requested vulture scan: PASS, 1323 reviewed identities / 1323 findings;
  zero unclassified and never-allowlist findings. No ledger amendment warranted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped. Historical failure does not reproduce: the independent
  expected DDL list already includes all three audit-column upgrades (line 175).
- Read all ten acceptance criteria from the frozen issue body. The checked-in
  load profile expressly identifies its host-process runner as preflight only;
  a longer preflight cannot establish exact-artifact acceptance.

## Additional executed validation

All validation used 1200-second timeouts. No full-tree pytest collection or
background command was used.

| Command | Outcome |
| --- | --- |
| `uv sync --locked --extra dev` | PASS; 256 resolved, 214 checked |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3277 files |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q` | PASS; 93 passed in 2.86 seconds |
| `uv run python scripts/check-deployment-claims.py` | PASS; component existence only, not live deployment |
| `uv run python scripts/check-execution-lifecycles.py` | PASS; 19 classified / 19 discovered |

Together with persistence validation: 130 passed, 6 skipped. The vulture command
matches `.github/workflows/quality.yml:1078`; it reports merge-base
`3c761d14db94`, not the supplied comparison base. No baseline, authorization,
gate, test, or runtime change was made. No test addition means no inventory delta.

## Reachable production behavior and architectural reconciliation

- `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215` enters
  a transaction and takes the advisory lock before schema upgrades. The
  independently enumerated 24-statement expectation in
  `packages/maistro-core/tests/persistence/test_pg_learnings.py:161` passes.
  The old 21-statement failure is already repaired, not a current defect.
- `packages/maistro-server/src/maistro_server/main.py:648` installs
  `RateLimitMiddleware`; `api/rate_limit.py:93` constructs an independent
  `InMemoryRateLimiter` per instance. The executed parametrized regression
  `tests/test_soak_promotion_gates.py:439` exhausts the same identity on one
  instance, then obtains a fresh allowance on the other: `[200, 200, 429]`
  on both, for both authenticated and unauthenticated requests. This falsifies
  a shared principal-budget claim at the production middleware seam. It is
  not a deployed multi-replica load test.
- `scripts/soak/run_soak.py:744` unconditionally reports host-process preflight
  artifact non-equivalence. Promotion-gate tests pass, including rejection of
  missing artifact evidence. Extending this emulator to four hours cannot
  establish the exact production image/configuration requirement.
- Read accepted ADR-081626-f383 (lease fencing), ADR-082526-b36a (renewal and
  reclaim), ADR-082826-08f0 (canonical recovery disposition), ADR-085
  (principal-keyed rate limits), and ADR-083026-a91e (absent measurements).
  These preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`, canonical
  lease/reconciliation authority and honest telemetry. Stale-write fencing
  alone is not proof of unique physical work. Principal-keyed local limits
  do not waive #860's replica-selection criterion. No competing execution,
  scheduler, event, Goal-store or authorization path was introduced.

## Acceptance assessment (all ten criteria)

| Criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC workload | UNVERIFIED. Reviewed `m3a-load-profile.md`; it explicitly lacks concurrent users/Workspaces, fan-out, successful tool/model, Design/Canvas and sustained Goal/background-worker coverage. Applicability to a selected RC is not supplied. |
| At least two application replicas | UNVERIFIED for deployed RC. Middleware tests use two ASGI instances, not promoted images. |
| Sustained pool/queue/reclaim/retry/memory/fd/process/shutdown observations | UNVERIFIED. This round's tests take seconds; no long production series generated. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | UNVERIFIED under deployed load. Canonical fencing/recovery and admission regressions pass, but cannot establish this multi-replica physical-work claim. |
| Effective rate/security/degradation without replica-selection bypass | NOT SATISFIED at the tested rate-limit seam: same identity receives independent replica allowances. Deployed security/degraded behavior UNVERIFIED. |
| All required PostgreSQL/loop/worker/RSS/fd/queue/error telemetry and thresholds | UNVERIFIED. Written thresholds are not a complete observed production series; driver loop lag is not application loop lag. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED on deployed RC. Bounded recovery tests passed only. |
| Long soak of exact RC/configuration, repeated after changes | UNVERIFIED. No immutable RC supplied; existing runner fails artifact equivalence by design. |
| Load findings classified at earliest broken invariant before promotion | UNVERIFIED for completeness without representative load. Confirmed replica rate-budget gap recorded here as a prerequisite security/rate-enforcement failure, not throughput tuning. No GitHub mutation permitted. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED. This source-head validation report is not a production soak evidence pack. |

## Final handoff

**BLOCKED**. Only this report changed. No actual vulture debt or schema-fence
failure remains to repair from the supplied CI evidence. Repeating that old
failure does not resolve the acceptance blockers.

Next: supply an immutable RC/configuration and representative workload scope;
resolve the replica rate-budget prerequisite through the existing canonical
security seam; then run a fresh exact-artifact soak (profile minimum four hours)
with complete telemetry, active-work recovery and physical-work observations.
Do not promote on the passing local tests. No remote mutations or integration
approval occurred.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0. Residual risks are the explicitly unverified deployed
behaviors and inherited integration differences outside this frozen repair scope.
Local commit is a handoff checkpoint only.
