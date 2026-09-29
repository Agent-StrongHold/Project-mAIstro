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
  serving. `run_soak.py` now kills the process group (`os.killpg`) — for the
  mid-load kill, the boot-failure cleanup (which had the same bug and left an
  orphan bound to :18202), and final teardown — and the boot-failure path now
  fails loudly if either replica port still accepts connections.
  **The H4 failover/drain/recovery claim is UNPROVEN in run 1** and needs the re-soak.
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
- **F6 (harness, fixed in the repair round): the harness required an
  undocumented environment.** The root workspace project does not depend on
  `maistro-server`, so the documented `uv sync` does **not** install it —
  `uv sync --locked --extra dev --dry-run` reports `Would uninstall
  maistro-server` — yet `run_migrations()`/`start_replica()` ran bare
  `uv run python -c "import maistro_server…"`, which is ModuleNotFoundError on
  any clean checkout (reproduced by the first repair attempt). Both now run
  `uv run --package maistro-server …`, which names the workspace member and
  self-satisfies it (verified: a throwaway clean `UV_PROJECT_ENVIRONMENT`
  installs 91 packages and the entrypoint import succeeds). The README's
  "`uv sync` — install every package in the workspace" claim is false for the
  API server with uv 0.12.11 and is filed here for the docs owners; the
  harness no longer depends on it.
- **F7 (production defect, FILED — not fixed in this lane): concurrent
  replica boot on a fresh database can kill a replica at startup.**
  `PgLearningStore.ensure_schema()` runs `CREATE INDEX IF NOT EXISTS
  idx_learnings_scope` on every app boot (container.py), no alembic migration
  creates that index (001 creates only `ix_learnings_org_tool`/
  `ix_learnings_status`), and concurrent `CREATE INDEX IF NOT EXISTS` on the
  same missing index is not race-safe in PostgreSQL: reproduced against the
  pinned `pgvector/pgvector:pg18` image with two backends racing the same
  statement — the loser dies with `duplicate key value violates unique
  constraint "pg_class_relname_nsp_index"` (asyncpg: UniqueViolationError),
  matching the crash a prior repair attempt observed booting two replicas
  concurrently on a fresh DB. Earliest broken invariant: M3-A replica-boot
  availability under the supported multi-replica profile (#89), in the
  durable-state/scheduler-replica-safety family (#333/#850). Must be repaired
  (advisory lock or tolerate-and-recheck) before the promotion soak, since
  the profile requires two replicas booting against one store.
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

1. Run 1's harness fixes are on this branch and repair-round-hardened:
   process-group kill for the mid-load kill *and* boot-failure/teardown paths
   (with a loud failure if a killed replica's port still accepts
   connections); the rate-limit probe targets the non-exempt `GET /tasks`;
   migrations/replicas pin `--package maistro-server` so the documented
   `uv sync` suffices; the schedule-claim race pins one due occurrence and
   the gate verifies **per occurrence** against the durable
   `(schedule_id, scheduled_for)` claim (repair-round live rerun: two
   processes raced, exactly one Run, loser `already_fired`, SQL shows 1
   occurrence × 1 run, gate `ok=true`).
2. Repair F7 before the promotion soak: two replicas booting concurrently on
   a fresh DB is the profile's own boot step, and F7 makes that a crash
   lottery.
3. Root-cause F3 (first suspect: nginx host-gateway upstreaming under mirrored
   WSL networking; alternative: run the replicas inside the docker network on
   the prod compose topology itself).
4. `--sustain-seconds 14400` (profile minimum), kill at 35% with verification
   that the victim actually stopped serving (assert port closed) before the
   restart, and a post-kill reconciliation of mid-flight Attempts.
5. File F3/F2 to the earliest broken milestone invariant before promotion.
6. Run 2 must execute on a clean tree at the promotion head — run 1's
   committed evidence is self-invalidating as RC-soak evidence (it recorded
   `git_clean=false` at the pre-commit base `b268f053`, not the RC artifact).

## RC artifact identity (run 1)

Recorded in `evidence/m3a-soak-evidence.json` under `hashes` (git head,
diff/status hashes, VERSION, soak env hash, nginx conf hash, PostgreSQL image
digest, CPython version). Any code or runtime-config change — including the
harness fixes above — requires a new soak per the profile.
