# M3-A #860 — multi-replica load & concurrency soak evidence pack (run 1)

**Status: PROVISIONAL — soak duration below the profile minimum, and run 1
discovered three defects (two in the harness, one in the LB path) that the
profile's falsification purpose exists to find.** Verdict for promotion:
NEEDS-REPAIR and re-soak of the repaired harness at profile duration. No
correctness claim in this pack is promotion evidence yet.

- Profile: [m3a-load-profile.md](m3a-load-profile.md) (thresholds H1–H6, S1–S5)
- Machine evidence: `evidence/m3a-soak-evidence.json`, `evidence/metrics.jsonl`,
  `evidence/replica-1820{1,2}.log`
- Executed: 2026-09-29, `--sustain-seconds 240 --rps 8 --workers 6`,
  nginx LB mirroring `deploy/nginx.conf`, 2× `maistro_server` replicas
  (RC entrypoint path), `pgvector/pgvector:pg18`.

## What passed (real, reproduced observations)

| Check | Result | Evidence |
|---|---|---|
| H1 exactly-once task admission | **PASS** — 12 concurrent duplicate `Idempotency-Key` submissions through the LB → 12× `202`, exactly **1** distinct `run_id` | `exactly_once_tasks` |
| H2 exactly-once schedule occurrence | **PASS** — two OS processes raced `ScheduleRunAdmitter.admit_due` on the canonical PostgreSQL store: one created Run `3adbdca2…`, the loser reported the occurrence `2026-09-29 05:00:00+00:00` as `already_fired`. **Zero duplicate physical work across claimants** (#220/#850 claim tier) | `exactly_once_schedule_claim` |
| Boot under the RC entrypoint | both replicas + full alembic chain migrate and serve; first-boot took **87 s** (root compose `start_period: 300s` exists for exactly this) | `replica_boot_seconds`, replica logs |
| S4 latency | p95 6.5–8.0 ms across all classes through the LB (of what got through — see F3) | `p95_latency_ms` |
| S1/S2 memory & descriptors | replica_1 RSS −16.9%, replica_2 +3.0% over the window; fds flat at 11 — no growth signal | `rss_growth`, `fd_growth` |
| S5 security surfaces | unauthenticated `/metrics` stayed gated (401s in `status_counts`); `REQUIRE_AUTH` enforced under load | `status_counts` |

## Findings (falsified or defective — must be repaired before promotion soak)

- **F1 (harness, fixed in this branch): the replica kill was a no-op.**
  `kill_restart.rejoined=true` arrived **< 1 s** after `SIGKILL` — impossible
  for an ~87 s boot. Cause: the harness spawns `uv run python -m uvicorn …`;
  the signal hit the `uv` wrapper and the uvicorn child in the session kept
  serving. `run_soak.py` now kills the process group (`os.killpg`). **The H4
  failover/drain/recovery claim is UNPROVEN in run 1** and needs the re-soak.
- **F2 (harness, fixed in this branch): the rate-limit probe targeted an
  exempt path.** `RateLimitMiddleware` deliberately skips `/health*`
  (`packages/maistro-server/src/maistro_server/api/rate_limit.py:120-121`), so
  bursts against `/health/live` can never 429 — recorded here because the
  exemption itself is security-relevant: an unauthenticated flood of
  `/health/live` is not rate-limited by design (cheap endpoints, but the
  exemption is silent in the module docstring's enforcement-scope paragraph).
  The probe now bursts `GET /tasks` (limiter runs before authz). **H3 is
  UNPROVEN in run 1.**
- **F3 (unresolved — the load-discovered defect this issue exists to catch):
  sustained 502 storm through the LB.** 7445 of 7590 driver requests through
  nginx returned **502** during the sustained window, while single probes
  through the same LB succeeded at 05:31:42 (boot gate) and 800-request bursts
  succeeded at ~05:36 (post-phase). Consistent DB state (52 completed + 4
  queued runs against 1539 submitted tasks) confirms only ~51 requests
  actually reached the application. The 502s are nginx→upstream connection
  failures under sustained proxied load in this soak cell (WSL mirrored
  networking + docker host-gateway upstreams are the suspect environment
  factors; no replica-side error appears in the replica logs for them).
  **Until reproduced and root-caused, the "supported production profile"
  multi-replica serving claim is not demonstrated under sustained load.**
- **F4 (observation, expected by design): `/health/ready` returns 503 with no
  LiteLLM in the cell** (LLM circuit open ⇒ `degraded`, not dead). Boot
  readiness therefore uses `/health/live`, the RC image's own healthcheck
  surface. Degraded-mode behavior was observable and did not crash either
  replica.
- **F5 (profile gap, documented): run 1 sustained 240 s; the profile minimum
  for a promotion-signing soak is ≥ 4 h.** Pool saturation, lease
  expiry/reclaim under a *real* mid-flight kill (F1 made run 1's kill a
  no-op), and shutdown drain (`SHUTDOWN_DRAIN_TIMEOUT`) remain unobserved.

## Re-soak checklist (what run 2 must do)

1. Run 1's harness fixes (process-group kill; non-exempt rate-limit probe) are
   in `scripts/soak/run_soak.py` on this branch.
2. Root-cause F3 (first suspect: nginx host-gateway upstreaming under mirrored
   WSL networking; alternative: run the replicas inside the docker network on
   the prod compose topology itself).
3. `--sustain-seconds 14400` (profile minimum), kill at 35% with verification
   that the victim actually stopped serving (assert port closed) before the
   restart, and a post-kill reconciliation of mid-flight Attempts.
4. File F3/F2 to the earliest broken milestone invariant before promotion.

## RC artifact identity (run 1)

Recorded in `evidence/m3a-soak-evidence.json` under `hashes` (git head,
diff/status hashes, VERSION, soak env hash, nginx conf hash, PostgreSQL image
digest, CPython version). Any code or runtime-config change — including the
harness fixes above — requires a new soak per the profile.
