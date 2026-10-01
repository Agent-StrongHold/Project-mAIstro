# M3-A #860 — representative release-candidate load & concurrency soak profile

This document defines the load profile, the pass/fail thresholds, and the
evidence contract for the M3-A promotion gate (#89). It is written **before**
the results it judges: the soak driver (`scripts/soak/run_soak.py`) evaluates
these thresholds mechanically and emits machine-readable evidence tied to the
exact commit/diff/config hashes. The evidence pack interpreting one run lives
beside it (`m3a-soak-evidence.md`, `evidence/m3a-soak-evidence.json`).

This is a falsification harness, not a benchmark. The goal is to observe the
supported concurrency/recovery claims failing or holding — never to maximize
throughput. M6 may optimize numbers after correctness is demonstrated.

## Supported topology under test

`deploy/docker-compose.prod.yml` (SPEC-070226-fbe3 / ADR-081): nginx load
balancer → **2× stateless `maistro-server` replicas** → PostgreSQL (+ streaming
replica) / Redis / shared file store. The current `run_soak.py` harness is a
**preflight emulator**, not that exact artifact: it runs host `uvicorn`
processes and a standalone PostgreSQL/LB container, so it cannot sign a
promotion soak for the Compose image, Redis, replication, or shared-store
configuration. It is retained to falsify the canonical HTTP/admission seams;
a promotion-signing run must execute the exact production Compose image and
configuration, with its image/config hashes in evidence.

## Artifact identity contract

A promotion-signing Compose soak must record the following identity. The
current host-process preflight records only the entries it can observe and is
therefore deliberately insufficient for promotion.

| Component | Required identity |
|---|---|
| Code | `git_head` + `git_diff_sha256` + `git_status_sha256` (dirty flag) |
| Release version | `VERSION` file content |
| Application image | immutable image digest for both `maistro-server` replicas |
| Config | normalized production Compose environment/config hash |
| LB config | `deploy/nginx.conf` hash |
| Database | primary and replica PostgreSQL image digests |
| Shared services | Redis and shared-store configuration/identity |
| Runtime | CPython version inside the promoted image |

Any code or runtime-config change invalidates a recorded soak and requires a
new one (acceptance: "any code/runtime-config change requires a new soak").

## Load profile (representative release-candidate traffic)

Per-replica boot configuration (documented, low-budget so saturation is
observable): DB pool `pool_size=2`, `max_overflow=3` (⇒ ≤ 10 PostgreSQL
sessions per replica), rate limit (dev override `ALLOW_UNSAFE_RESOURCE_OVERRIDES=true`, recorded in the config hash) `RATE_LIMIT_PER_MINUTE=3000` with
`RATE_LIMIT_BURST=100` — sized so the sustained authenticated share of phase 1
(≈ 36 req/s ≈ 2160/min) keeps ≥ 25% headroom under the per-minute window,
while the phase-5 concentrated bursts (> 100 req/s) trip the 1-second burst
rule — `REQUIRE_AUTH=true` with one API key.

Request mix (executed profile, `--rps 8 --workers 6` ⇒ ≈ 48 req/s offered
through the LB):

| Class | Share | Endpoint | Purpose |
|---|---|---|---|
| Readiness reads | 45% | `GET /health/ready` (auth) | steady-state latency/pool baseline |
| Liveness reads | 20% | `GET /health/live` (no auth) | liveness under load (health paths are rate-limit exempt) |
| Task admission | 20% | `POST /tasks` (auth, unique `Idempotency-Key`) | Run/Attempt admission, queue growth, durable spine writes |
| Receipt reads | 10% | `GET /tasks/{id}` (auth) | store reads under load |
| Metrics gate | 5% | `GET /metrics` (no auth) | security surface must stay gated under load |

Model calls are **not** stubbed: task execution fails fast against the absent
LiteLLM endpoint, which is itself a degraded-path load class (error accounting,
attempt terminalization) — recorded as such, not hidden.

## Concurrency/falsification phases

1. **Sustained mixed load** (`--sustain-seconds`, default 420) with 2 s metric
   sampling: per-replica RSS + open descriptors (`/proc`), PostgreSQL session
   count + waiting locks (`pg_stat_activity`/`pg_locks`), canonical spine
   depth by status (`canonical_runs`), status-code and per-class latency
   histograms.
2. **Replica kill/restart mid-load**: `SIGKILL` replica 2 at 35% of the window,
   restart after 12 s; LB passive health must fail over; replica must rejoin;
   no silent loss/duplication of admitted work.
3. **Exactly-once task admission**: 12 concurrent `POST /tasks` with one
   `Idempotency-Key` through the LB ⇒ exactly 1 observed distinct `run_id`,
   a non-empty identity on every 200/202 receipt, statuses only 200/202/409.
   All-conflict or empty probes fail: absence of admission is not deduplication.
4. **Exactly-once schedule occurrence**: two **OS processes** race
   `ScheduleRunAdmitter.admit_due` over one due occurrence in the canonical
   PostgreSQL store ⇒ exactly 1 Run created for the occurrence, the loser
   reporting it `already_fired` (the cross-process form of
   `test_two_admitters_concurrently_claim_each_due_occurrence_once`, #220/#850).
5. **Rate limiting under concurrency / replica selection**: 800-request
   bursts for both unauthenticated and authenticated identities through the
   LB **and directly to each of the two replicas** (six probes total) ⇒
   HTTP 429 with `Retry-After` on every path. Direct evidence is keyed by
   replica origin in `rate_limit.direct_replicas`; a healthy LB result cannot
   hide a replica with enforcement disabled. This tests process-local
   enforcement (`N × limit` aggregate per the documented #842 semantics),
   **not** a cluster-wide budget or proof that replica selection cannot
   increase a principal's aggregate allowance.

## Pass/fail thresholds

Hard (any miss fails the soak):

| # | Check | Threshold |
|---|---|---|
| Artifact | Exact RC topology | Host-process preflight always fails `exact_rc_artifact`; a longer emulator run is not promotion evidence |
| H1 | Exactly-once task admission | ≥ 2 submissions; exactly 1 observed distinct run_id; every 200/202 has a non-empty identity; statuses ⊆ {200,202,409} |
| H2 | Exactly-once schedule occurrence | runs created for the raced occurrence == 1 |
| H3 | Rate limiting | 429 + `Retry-After` observed on all six burst paths (LB + both direct replicas, authenticated + unauthenticated) |
| H4 | Replica kill/restart | replica 2 rejoins healthy; LB failover keeps client-visible 5xx + connection errors ≤ kill-window budget (`(restart_delay + 15s) × offered load`) |
| H5 | No silent stall | non-terminal `canonical_runs` after the settle window are enumerated; the automated gate requires **0**. Any non-zero result is a promotion failure pending a separately filed/reclassified finding. |
| H6 | Task admission availability | `POST /tasks` 202 ratio ≥ 99% outside the kill window |

Soft (observed, reported, judged in the evidence pack):

| # | Check | Expectation |
|---|---|---|
| S1 | Memory | per-replica RSS growth over the window < 20% (no unbounded climb) |
| S2 | Descriptors | open fds return near baseline; no monotonic growth |
| S3 | PostgreSQL | sessions ≤ pool budget (2 × 10 + margin); no waiting locks sustained |
| S4 | Latency | p95 `/health/ready` < 250 ms sustained (excl. kill window) |
| S5 | Security | unauthenticated `/metrics` stays 401 under load |

## Soak duration requirement & executed evidence

The acceptance requires a *long-running* soak of the exact RC artifact. The
profile minimum for a promotion-signing soak is **≥ 4 hours** of the sustained
profile above (`--sustain-seconds 14400`). Each executed run records its actual
duration in the evidence JSON (`sustain_seconds`) and evidence pack; a run
shorter than the profile minimum can only ever be **provisional** evidence and
must say so. The driver mechanically fails `sustain_duration` below this
minimum, so it cannot print a promotion-pass result for a short run. It also
always emits `exact_rc_artifact.ok=false`: its host-process boot path does not
run the promoted Compose artifact. Missing/null artifact checks fail closed for
older evidence. There is no flag to override this limitation. The harness is
parameterized; nothing caps duration, but even ≥ 4 hours cannot make it a
promotion-signing runner.

## Out of scope here (documented limits)

- The soak exercises the **supported multi-replica profile** (stateless
  maistro-server ×2). The Conductor variant app (`hive-conductor`) is
  single-process by design (in-memory/SQLite product projections); its
  scheduler's cross-runner safety is proven at the canonical seam it delegates
  to (`ScheduleRunAdmitter` + PostgreSQL claim tier), which phase 4 races
  across processes.
- Model/provider latency is not part of the profile (no LiteLLM in the soak
  cell); admission/queue/spine behavior is.

## Remaining representative-profile gaps

The current preflight uses one API key, not a concurrent population of users and
Workspaces. It does not exercise Graph/node fan-out, successful tool/model calls,
Design/Canvas operations or Goal/background-worker reconciliation. Inclusion or
exclusion of those surfaces must be justified against the selected RC deployment
configuration before a representative promotion profile is considered complete.
Driver loop lag is not application event-loop lag. Process-exit/rejoin and terminal
Run counts alone do not prove physical-work fencing/recovery. Required worker
counts, pool saturation, lease reclaim and long-window leak/error observations
remain unverified. These are blockers, not acceptance waivers.

## Round-2 amendments (repair lane, 2520eeb7369c → )

Instrumentation and probes added by the repair round; every promotion soak
(runs ≥ 4 h) must capture these alongside the original series:

- `pg_probe_ms` per sample — a real asyncpg `SELECT 1` round-trip on a
  dedicated driver pool (wire latency under load, not psql spawn wall time).
  Judged under S3/S4: sustained p95 > 50 ms with sessions under the pool
  budget indicates lock or pool contention worth filing.
- `driver_loop_lag_ms` per sample — the load driver's event-loop sleep
  overshoot, proving the offered load itself was delivered on a healthy loop
  (a driver-side stall invalidates the sample window it occurs in).
- `--kill-signal SIGTERM` drain probe (the driver default) — the
  graceful-shutdown counterpart of the separately runnable SIGKILL failover
  phase: the victim must exit cleanly within
  `SHUTDOWN_DRAIN_TIMEOUT` (30 s) + slack, without escalation, and the drain
  window's 5xx/connection-error delta is recorded against the H4 budget.
  It is exit-gated whenever SIGTERM is selected. Run 2's scratch validation
  exposed this as **failed** (lifespan shutdown
  never completes; 6579 5xx in the window) — filed as the drain defect above;
  a promotion soak cannot pass H4-drain until it is fixed and re-proven.

Goal reconciliation scoping (closes the "nowhere exercised or scoped out"
gap): goal→Run admission reconciliation is `ScheduleRunAdmitter`'s
`_reconcile_claims` / `_reconcile_pending_fires` in
`packages/maistro-core/src/maistro/scheduling/admission.py`. There is no
separate reconciliation worker to soak; the reconciliation executes inside
every schedule admission, and the cross-process fence it stands on is raced
live by phase 4 (`--claim-probe`) with the per-occurrence SQL gate (H2).
This admission probe is not evidence of sustained Goal desired-state
reconciliation or physical Attempt fencing: phase 4 races one occurrence, then
cancels the queued probe Run without executing it. The sustained mix has no
schedule traffic. Those acceptance surfaces remain unverified and require
production-path workloads; a duplicate-admission counter alone cannot prove them.

## Round-5 amendments (repair lane, b5f9abbcc → )

Root-caused and re-probed by the round-5 repair; every promotion soak must
run on these terms:

- **F3 root cause (soak cell, not product): the LB conf named its upstreams
  `host.docker.internal`, which Docker Desktop answers with an unreachable
  IPv6 address AND the IPv4 gateway.** nginx round-robins NEW upstream
  connections across all addresses of a named peer and counts each
  `connect() failed (101: Network unreachable)` toward `max_fails` for the
  *peer*, so under any sustained connection churn both replicas flap into
  the passive-health down state and the LB answers mass instant
  "no live upstreams" 502s (run 1: 7445/7590; only ~51 requests reached the
  application). The driver now renders the conf with the resolved IPv4
  literal (`nginx-soak-rendered.conf`, hash + IP recorded in evidence) and
  captures the LB container's `docker logs` to `lb.log` before teardown.
  Production is immune: `deploy/nginx.conf` targets compose service names,
  which resolve to a single container address.
- **F9 (product, fixed): a full active-root-Run ceiling escaped POST /tasks
  as an unhandled 500.** `RunConcurrencyExceeded` (#1182, designed retryable
  backpressure) now maps to `429` + `Retry-After` (see
  `m3a-860-f9-concurrency-backpressure-429.md`). H6 consequently counts a
  429 with `Retry-After` as *available admission machinery* alongside 202;
  5xx and connection failures still fail it, and the 202 count is recorded
  beside the ratio so an all-backpressure window cannot masquerade as an
  accepted-load result.
- **task_submit share 20% → ~4.8%.** The soak cell runs no LiteLLM; admitted
  runs take ~10–60 s through the retry path and the 4-worker runner drains
  < 1 run/s/replica, so the 20% share tripped the ceiling for the whole
  window. At the profile share the ceiling (production default 8, untouched)
  backpressures briefly and bounds the queue — which is also what makes the
  H5 settle-to-zero contract satisfiable: at load end at most one ceiling's
  worth of Runs remains, and `--settle-seconds` (default now 120) covers the
  drain. Measuring the degraded executor's latency itself is filed as a
  finding, not tuned away.
- **Fresh database per run (`--fresh-db`, default on).** H5's "0
  non-terminal" and every status count are claims about *this run*; the
  persistent soak DB accumulated every prior run's claim-probe Runs (never
  executed by design), making H5 structurally unsatisfiable. The flag is
  part of `soak_env_sha256`.
- **Claim-probe cleanup.** After H2's SQL verdict, the probe terminalizes
  its own Run QUEUED→CANCELLED through `PgRunStore` (recorded as
  `probe_run_cleanup`); a failed race preserves the duplicate rows for
  forensics.
- **Drain gate hardening.** `failed_promotion_checks` fails evidence whose
  `graceful_drain` record is missing/null, not merely `required`-and-failed.
- **Rate-limit probe.** Default probe size is 800 (the phase-5 spec);
  `probe_requests` / `rate_limit_burst` / `probe_below_burst` travel with
  the verdict so an undersized probe is never mistaken for falsification.
