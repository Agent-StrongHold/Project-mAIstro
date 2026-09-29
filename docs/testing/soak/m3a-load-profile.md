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
| Liveness reads | 20% | `GET /health/live` (no auth) | unauthenticated-path rate limiting |
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
   `Idempotency-Key` through the LB ⇒ ≤ 1 distinct `run_id`, statuses only
   200/202/409.
4. **Exactly-once schedule occurrence**: two **OS processes** race
   `ScheduleRunAdmitter.admit_due` over one due occurrence in the canonical
   PostgreSQL store ⇒ exactly 1 Run created for the occurrence, the loser
   reporting it `already_fired` (the cross-process form of
   `test_two_admitters_concurrently_claim_each_due_occurrence_once`, #220/#850).
5. **Rate limiting under concurrency / replica selection**: 800-request
   bursts unauthenticated (through LB and direct to a replica) and
   authenticated (through LB) ⇒ HTTP 429 with `Retry-After` on each path;
   per-replica enforcement (`N × limit` aggregate is the documented #842
   semantics, not a bypass).

## Pass/fail thresholds

Hard (any miss fails the soak):

| # | Check | Threshold |
|---|---|---|
| H1 | Exactly-once task admission | distinct run_ids ≤ 1; statuses ⊆ {200,202,409} |
| H2 | Exactly-once schedule occurrence | runs created for the raced occurrence == 1 |
| H3 | Rate limiting | 429 + `Retry-After` observed on all three burst paths |
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
minimum, so it cannot print a promotion-pass result for a short run. The
harness is parameterized; nothing about it caps duration.

## Out of scope here (documented limits)

- The soak exercises the **supported multi-replica profile** (stateless
  maistro-server ×2). The Conductor variant app (`hive-conductor`) is
  single-process by design (in-memory/SQLite product projections); its
  scheduler's cross-runner safety is proven at the canonical seam it delegates
  to (`ScheduleRunAdmitter` + PostgreSQL claim tier), which phase 4 races
  across processes.
- Model/provider latency is not part of the profile (no LiteLLM in the soak
  cell); admission/queue/spine behavior is.

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
Admission reconciliation under sustained multi-replica load is therefore
covered by H2 + the sustained task/schedule mix, and run 2 must state the
duplicate-admission counter evidence (`duplicate_evidence`) alongside it.
