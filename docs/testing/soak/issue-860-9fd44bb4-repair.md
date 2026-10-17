# Issue #860 — CI-repair acceptance audit (9fd44bb4)

**BLOCKED; not promotion evidence.** Only issue #860 was checked in the assigned
`auto-860` worktree, starting clean at
`0bbd06e307028793ebf4f19f9e498fdf194557a2`; assigned develop base:
`a8258ee24dd957d0f0b302db4eee90661fe23439`.

The captured dispatch, previous result, repository instructions, production
middleware, soak evaluator and adjacent tests were inspected. No driver
`check-*.log` files were supplied. Fresh validation logs are in
`/home/dev/maistro/jobs/9fd44bb401324ecda6c2af669e131a2b/`.

## Repair disposition

The prescribed vulture failure **did not reproduce**. CI's exact command found
1,336 findings matching 1,336 reviewed identities, zero unclassified and zero
never-allowlist findings. The existing provenance resolver selected trusted base
`56332162cf63`. There are no evidenced unbanked identities to amend or dead
identities to remove. No ledger, grant, production code, gate, or test changed;
this report is the only repository change. Suite inventory is unchanged.

The previous whitespace finding also did not reproduce against the assigned
base. Passing static checks do not establish the issue's load acceptance.

## Executed checks

| Command | Outcome / job log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,336 exact identities; `check-vulture.log` |
| `uv run ruff check .` | PASS; `check-ruff.log` |
| `uv run ruff format --check .` | PASS, 3,003 files; `check-format.log` |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | PASS, 52 cases; `check-soak-tests.log` |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | PASS, 23 cases; `check-server-tests.log` |
| `git diff --check a8258ee24dd957d0f0b302db4eee90661fe23439...HEAD` | PASS; `check-diff.log` |
| `DOCKER_HOST=unix:///var/run/docker.sock docker compose -f deploy/docker-compose.prod.yml config --quiet` | FAIL: required `LITELLM_BASE_URL` missing; `check-compose-preconditions.log` |
| Import current soak module; evaluate round-6 JSON with `failed_promotion_checks`; assert duration/artifact rejection | PASS: rejected `sustain_duration` and `exact_rc_artifact`; `check-historical-evidence.log` |

Compose failed at configuration interpolation, before service startup; this is
not evidence of a Docker daemon failure. No credentials were invented or printed.
The historical JSON records 90.43 seconds against the 14,400-second minimum and
names commit `b31c5fdaa63b40506335bbb288889e87bdb9ba0c` (line 70), not the
assigned HEAD. No fresh load run or production restart was executed.

## Production behavior and architectural reconciliation

`packages/maistro-server/src/maistro_server/main.py:628` installs the real
`RateLimitMiddleware`; `api/rate_limit.py:72-77` constructs a process-local
`InMemoryRateLimiter`. The executed regression at
`tests/test_soak_promotion_gates.py:439-489` exhausts one instance with an identity,
then observes another instance accept two more requests for that same identity,
for both authenticated and unauthenticated cases. This reproduces independent
replica allowances, not replica-selection-safe enforcement. These are ASGI seam
tests, not deployed production replicas.

Accepted ADR-085 requires principal-keyed limits; the current #842 implementation
explicitly documents process-local scope (`api/rate_limit.py:25-30`). Neither is
proof of #860's stronger replica-selection criterion. No second authentication
path or unreviewed shared-store design was introduced to conceal this mismatch.

Accepted ADR-081226-a66b and ADR-081626-f383 retain canonical execution ownership
and durable Attempt fencing. The latter explicitly does not define lease-expiry
takeover; elapsed time or admission deduplication must not be presented as proof
of physical-work reclaim. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
ADR-081 is **Proposed**, not an accepted waiver of load/recovery criteria.

`scripts/soak/run_soak.py:635-668` rejects host-uvicorn preflight as exact-RC
promotion evidence, including otherwise-passing synthetic four-hour results.
Those executed regression cases prove fail-closed behavior, not an actual soak.

## Acceptance matrix

| #860 criterion | Executed evidence or remaining gap |
| --- | --- |
| Representative users/Workspaces, request mix, Graph fan-out, schedules, queue, tools/models, Canvas and workers | **UNVERIFIED**. `m3a-load-profile.md:152-163` lists missing representative surfaces; no new production traffic was generated. |
| At least two application replicas | **UNVERIFIED** for the selected RC. Compose declares two replicas but configuration validation failed; two ASGI instances are not deployment evidence. |
| Sustained saturation, queue growth, lease reclaim, retries, memory/descriptor/process leaks and restart behavior | **UNVERIFIED**. Current evaluator rejects the historical 90.43-second run; no current long-window observations exist from this round. |
| Exactly-once admission, Goal reconciliation and physical-work fencing | **UNVERIFIED**. Admission probe regressions pass, but `m3a-load-profile.md:197-200` distinguishes a cancelled schedule probe from sustained reconciliation or physical Attempt execution. |
| Replica-selection-safe rate limiting, security and degraded behavior | **NOT SATISFIED**. Independent allowances reproduced with real production middleware. Local rate-limit and admission-backpressure tests pass; they do not prove cross-replica budgets or full security under load. |
| Complete PostgreSQL, application-loop, worker/process, RSS, descriptor, queue and error telemetry with thresholds | **UNVERIFIED**. Process-group sampler regressions pass; missing application-loop and production-worker observations remain documented at `m3a-load-profile.md:157-163`. |
| Kill/restart during active work, drain, fencing and recovery | **UNVERIFIED**. No active production workload or kill/restart was executed. Rejoin or terminal Run counts alone cannot prove physical recovery. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED**. Current runner rejects exact-artifact eligibility; historical duration fails and current Compose configuration is incomplete. |
| Findings filed/reclassified to earliest broken milestone invariant | **UNVERIFIED**. Prior local classifications are not evidence of complete triage; no GitHub mutations are permitted or performed. |
| Machine/human evidence bound to exact current image/package/commit/config hashes | **UNVERIFIED**. Historical JSON names a different commit; these validation logs and this report are not an RC soak evidence pack. |

## Required handoff

Supply the selected immutable RC image/configuration and reachable authorized
model gateway configuration. Complete the production-path profile and runner
using existing canonical services, resolve the replica-budget acceptance mismatch,
and execute a new >=4-hour exact-artifact soak with representative traffic,
production telemetry and physical recovery/fencing observations. Repeating the
passing vulture gate or lengthening the host emulator cannot unblock promotion.

Progress: checked 1 issue; done 0 acceptance-complete repairs; skipped 0 issues;
1 prerequisite command failure. The audit/handoff is complete; implementation and
soak remain blocked. No push, merge, PR, comment or issue closure was performed.
