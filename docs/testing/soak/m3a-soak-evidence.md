# M3-A #860 — multi-replica load & concurrency soak evidence pack (run 1)

**Status: PROVISIONAL — soak duration below the profile minimum, and run 1
discovered three defects (two in the harness, one in the LB path) that the
profile's falsification purpose exists to find.** Verdict for promotion:
BLOCKED pending an exact-RC production-topology soak at profile duration. A
longer run of the host-process preflight harness cannot satisfy that requirement. No
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
| H2 exactly-once schedule occurrence | **PASS** — two OS processes raced `ScheduleRunAdmitter.admit_due` on the canonical PostgreSQL store: one created Run `3adbdca2…`, the loser reported the occurrence `2026-09-29 05:00:00+00:00` as `already_fired`. **One admitted Run across claimants** (#220/#850 claim tier); physical execution was not probed | `exactly_once_schedule_claim` |
| Boot under the RC entrypoint | both replicas + full alembic chain migrate and serve; first-boot took **87 s** (root compose `start_period: 300s` exists for exactly this) | `replica_boot_seconds`, replica logs |
| S4 latency | p95 6.5–8.0 ms across all classes through the LB (of what got through — see F3) | `p95_latency_ms` |
| S1/S2 memory & descriptors | **INVALID as application evidence** — the old sampler observed the `uv` wrapper, not its application child (F12 below) | Historical `rss_growth`, `fd_growth` retained unchanged |
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

---

# Run 5 (final validation, head `6e8c866e5`) and run 6 shakedown (head `b31c5fdaa`)

Both runs are **gate-enforcing preflight evidence, not promotion evidence**:
`--sustain-seconds 90` ≪ the profile's 4-hour minimum, so `sustain_duration`
correctly fails and the driver exits 1. These are historical results under
the gates at those heads: run 5 also failed H3, and run 6 passed its then-current
functional gates. Neither run satisfies today's six-path H3 probe or the explicit
`exact_rc_artifact` gate. The current host-process driver always fails the latter,
regardless of duration. Machine evidence (hash-tied,
`git_clean=true` at each run's own head):
`evidence/m3a-round5-final.json`, `evidence/m3a-round6-shakedown.json` with
`-metrics.jsonl`, `-lb.log`, `-replica-1820{1,2}.log`,
`-nginx-soak-rendered.conf` beside each.

## Run 5 — first gate-enforcing run; found the H3 probe-shape defect

At `6e8c866e5` (clean): H1 true (12 duplicate submissions → 12×202, exactly 1
`run_id`), H2 true, H4 true (73 ≤ budget 1296 in a 3.52 s kill window),
SIGTERM drain `drained=true` in 1.0 s without escalation, H5 = 0 nonterminal
runs after settle, H6 ratio 1.0 (205/202 outside the kill window), RSS/FDs
flat. **H3 `rate_limit_enforced=false`** — root-caused as a probe-shape
defect, not a limiter defect: the burst probe was *sequential*, and at the
profile budget (3000/min ⇒ 50/s refill + burst 100) a sequential local loop
can never outpace the bucket — the authenticated-through-LB probe observed
800×200. Fix (repair 6a, commit `b31c5fdaa`): 16-way concurrent burst lanes,
matching the profile's "> 100 req/s concentrated burst" shape. Run 5 also
stalled ~14 min between evidence write and exit on unbounded Docker Desktop
CLI calls at teardown; repair 6a bounds every teardown docker call (60 s) and
the pg pool close (30 s).

## Run 6 — shakedown at `b31c5fdaa` (clean): all functional gates green

`--sustain-seconds 90 --rps 4 --workers 4 --settle-seconds 60`; exit 1 with
`FAILED checks: ['sustain_duration']` — the only failing gate, as designed
for a sub-minimum run.

| Check | Result | Evidence |
|---|---|---|
| H1 exactly-once task admission | **PASS** — 12 duplicate `Idempotency-Key` submissions → 12×202, 1 distinct `run_id` | `exactly_once_tasks` |
| H2 exactly-once schedule occurrence | **PASS at admission only** — two OS processes race `admit_due`; one durable Run per occurrence. The probe cancels its queued Run without executing it, so physical-work deduplication is unverified | `exactly_once_schedule_claim` |
| H3 rate limiting under concurrency | **PARTIAL, historical three-path probe only** — direct replica 1 unauthenticated: 600×429; LB auth: 430×429 / 370×200; LB unauth: 446×429. Historical `enforced_everywhere=true` covers only those paths, not both replicas/identity classes. Limiter state is process-local; switching replicas increases aggregate allowance. No cluster-wide budget or replica-selection non-bypass proof | `rate_limit` (`direct_replica_unauthenticated`, not today's `direct_replicas`) |
| H4 LB failover bounded | **PASS** — 35 5xx+conn-errors ≤ budget 432 in the 4.52 s measured kill window | `lb_failover_bounded` |
| Graceful drain (SIGTERM) | **PASS** — `drained=true` in 2.0 s, rc=143, **no SIGKILL escalation**, 17 drain-window 5xx within budget. The round-2 F8 hang does not reproduce at this head (post-#819 shutdown path) | `graceful_drain` |
| Replica rejoin | **PASS** — replica_2 restarted and rejoined | `replica_2_rejoined` |
| H5 nonterminal runs after settle | **PASS** — 0 (`--fresh-db` schema reset; the run measures only itself) | `nonterminal_runs_after_settle` |
| H6 admission availability | **PASS** — ratio 1.0 (63/63 task submissions outside the kill window accepted 202; kill-window submissions accounted separately) | `task_admission_availability` |
| S1/S2 RSS/FD growth | **INVALID as application evidence** — wrapper-only measurements; no application leak conclusion (F12 below) | Historical `rss_growth`, `fd_growth` retained unchanged |
| Sustain duration | **FAIL (by design)** — 90.43 s observed vs 14400 s minimum; recorded as requested + observed so a stalled driver can never sign a longer run | `sustain_duration` |

Teardown was fully bounded: the slow Docker Desktop CLI hit the new 60 s
`docker rm` guard, was logged, and the driver exited immediately instead of
stalling (the run-5 failure mode is closed).

### Observation (recorded, not gated): `health_ready` 503 during provider-less soak

With F3 fixed, the clean signal is: **every** `health_ready` probe through the
LB returns 503 during the sustained phase while all other classes serve
(200/202/404/401). Boot-time readiness passed (5.1 s boot gate requires
readiness). Probable mechanism (attribution probable, not proven): the
readiness handler aggregates the LLM circuit state and dependency probes
(`packages/maistro-server/src/maistro_server/api/health.py`); in the
provider-less soak cell task execution fails, the circuit opens, and
readiness answers the status-only `{"status": "not_ready"}` 503 — i.e.
**degraded signaling works**, which is itself an acceptance surface
("degraded behavior remains effective"). The instant ~40 ms 503 latency fits
an in-process circuit check rather than a pool wait. Un-gated by the profile
today; the promotion soak (with its real provider configuration) must confirm
readiness returns 200 there.

## What still separates this from a promotion signature

1. **Duration**: a ≥ 4 h sustained soak (`sustain_duration` gate is honest —
   it cannot be argued away by the CLI exit status).
2. **Exact RC artifact**: the profile's artifact-identity contract requires
   the production Compose image/config (Redis, replication, shared store);
   the current harness is the documented preflight emulator. The identity
   contract table in `m3a-load-profile.md` lists exactly what a promotion
   run must record.
3. **Re-proof of drain under promotion-duration load**: run 6 records process
   exit/rejoin at 90 s; the 4 h run must correlate in-flight physical Attempts,
   lease fencing and recovery under long-lived connections and deeper queues.
4. **Rate-limit acceptance remains unmet**: #842 documents independent
   per-process limits (`rate_limit.py:25-30`), not shared rate-limit state.
   Current six-path probes can show every replica rejects overload, but cannot
   prove a cluster-wide allowance. The production-middleware regression in
   `tests/test_soak_promotion_gates.py` demonstrates the same identity receiving
   another allowance on replica 2 after exhausting replica 1. Resolve this
   deployment/acceptance mismatch before promotion; do not silently reinterpret
   #860's non-bypass requirement as passed.

## Recovery repair — admission oracle (not a new soak)

**F11 (harness, reproduced and repaired): all-conflict responses passed H1.**
The actual HTTP probe returned `ok=true`, `distinct_run_ids=[]` for twelve
HTTP 409 responses. At-most-one counted zero admitted Runs as success. Earliest
broken invariant: M3-A evidence validity (#89/#860), not a demonstrated runtime
duplication defect. H1 now requires a concurrent probe with one observed
canonical identity, validates every successful receipt, and includes HTTP 200
replay IDs in the comparison. Twelve HTTP-probe regression cases exercise this
oracle. Historical raw evidence is unchanged; this is not fresh load evidence.
No external issue filing was performed (prohibited in this lane).

## Process sampling repair — not a new soak

**F12 (harness, reproduced and repaired): S1/S2 sampled the uv wrapper only.**
A live `uv run` child allocated 32 MiB and opened 16 descriptors, yet the old
`sample_once` reported identical wrapper RSS (25952 KiB before and after).
Earliest broken invariant: M3-A evidence validity (#89/#860), not a demonstrated
application leak. Historical S1/S2 conclusions above are invalid as application
measurements; raw evidence is preserved, not recomputed or relabelled as fresh.

The sampler now records every observed member of the replica's process group,
per-PID RSS/descriptors and process count, with aggregate RSS/descriptors only
when all observed members were measured. It keeps observing the group when the
wrapper exits. This is a non-atomic Linux snapshot, not a cgroup/container census;
detached workers, application-loop latency, and long-window leak/recovery proof
remain unverified. Summed RSS can double-count shared pages. The live subprocess
regression detects child growth, but does not substitute for a new RC soak.
No external finding was filed (GitHub mutations are prohibited in this lane).

See [m3a-salvage-validation.md](m3a-salvage-validation.md) for this recovery's
validation and [m3a-repair-handoff.md](m3a-repair-handoff.md) for earlier
remaining acceptance gaps. Historical JSON/logs are preserved unchanged; no new
production soak is claimed by this repair.
