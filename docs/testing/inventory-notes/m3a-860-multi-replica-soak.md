# M3-A #860 multi-replica load & concurrency soak harness

Adds `scripts/soak/run_soak.py` and `scripts/soak/nginx-soak.conf` — the
falsification harness defined by `docs/testing/soak/m3a-load-profile.md` and
run for issue #860 (parent #89, M3-A).

What the harness does (no pytest nodes are added or removed; this is a
runnable evidence producer, so the delta is tooling, not collected tests):

- Boots the RC application surface (`maistro_server` via the RC entrypoint's
  exact migration-then-uvicorn path) as two replicas behind an nginx LB that
  mirrors `deploy/nginx.conf` passive-health policy.
- Drives a sustained mixed request profile (readiness/liveness/task
  admission/receipt reads/metrics gate) while sampling RSS, open descriptors,
  PostgreSQL sessions/locks, and canonical spine depth per status.
- Proves exactly-once task admission (concurrent duplicate
  `Idempotency-Key` submissions through the LB), exactly-once schedule
  occurrence claim (two OS processes racing `ScheduleRunAdmitter.admit_due`
  on the canonical PostgreSQL store — the process-level form of
  `packages/maistro-core/tests/scheduling/test_pg_admission.py::
  test_two_admitters_concurrently_claim_each_due_occurrence_once`), rate-limit
  enforcement (LB, direct-replica, authenticated bursts), and SIGKILL/restart
  of one replica mid-load with LB failover and rejoin.
- Emits `evidence/m3a-soak-evidence.json` + `evidence/metrics.jsonl` tied to
  commit/diff/config/image hashes, with mechanical pass/fail against the
  profile thresholds.

Existing pytest inventory is unchanged: the harness reuses the live-Postgres
admission-race pattern already covered by
`packages/maestro-core/tests/scheduling/test_pg_admission.py` (path as on
disk: `packages/maistro-core/tests/scheduling/test_pg_admission.py`) rather
than duplicating it as a unit test; the soak evidence is the deliverable.

## Repair round (2026-09-29, this lane)

Verdict on run 1 stands: **NEEDS-REPAIR and re-soak** — no promotion claim
changes. The round confirmed all six prior findings against this head and
repaired the three harness-side ones:

- F6 (undocumented env): `uv sync --locked --extra dev --dry-run` reports
  `Would uninstall maistro-server` → harness now pins
  `uv run --package maistro-server` (clean-env check: 91 packages installed,
  `maistro_server.entrypoint.run_migrations` imports OK); harness's own
  `run_migrations()` executed OK against the soak DB.
- Boot-failure orphan: `boot_stack`/teardown now `killpg` + fail loudly if a
  replica port still accepts connections.
- Claim gate: due occurrence pinned to the most recent hourly instant;
  `phase_claim_probe` verifies per occurrence against the durable
  `(schedule_id, scheduled_for)` claim. Live two-process rerun: 1 Run,
  loser `already_fired`, SQL 1 occurrence × 1 run, `ok=true`.
- F7 (production, filed not fixed here): concurrent-boot
  `CREATE INDEX IF NOT EXISTS idx_learnings_scope` race reproduced against
  pinned pg18 (`duplicate key value violates unique constraint
  "pg_class_relname_nsp_index"`); must be fixed before the promotion soak.

### Mini soak at the repair head (functional validation, NOT promotion evidence)

`--sustain-seconds 120 --rps 4 --workers 4` on a clean tree at the repair
commit, evidence in `evidence/m3a-repair-validation*.json|.log` (120 s ≪ the
4 h minimum; this run validates the harness, it does not sign the RC):

- Repairs live: real SIGKILL failover (killed → rejoined in 15 s, vs run 1's
  <1 s no-op), `rate_limit_enforced=true` on the `/tasks` probe,
  `exactly_once_schedule_occurrence=true` (per-occurrence gate),
  `hashes.git_clean=true`.
- F3 reproduced unchanged (1671/2271 sustained requests = 502 through the
  LB while all phase/burst requests succeed) — still the promotion blocker.
- New gate observation, handled: `exactly_once_task_admission` failed
  strictly because 4/6 duplicate submissions got LB 502s while the 2
  delivered agreed on one run_id — exactly-once unproven under the storm,
  not falsified; the phase now records `delivered` + `cause` so run 2 can
  tell transport degradation from a duplicate (gate strictness unchanged).
- Teardown left no orphans (replica/LB ports free after exit).

No pytest nodes added or removed; deltas remain `scripts/soak/` tooling and
evidence prose.

---

## Repair round 2 (this lane) — gate repairs, F7 fix, drain probe, metric gaps

State at entry: HEAD `2520eeb7369c`, branch `auto-860`, tree clean.

Gate repairs (CI evidence, not soak evidence):

- gitleaks `generic-api-key` at `scripts/soak/run_soak.py:51`: the
  hex-padded synthetic values were de-shaped (the delegation key is opaque to
  the server; the router key only needs to clear the ≥32-char Settings
  warning) and the introducing commit's immutable blob is covered by a
  `.gitleaksignore` fingerprint, per that file's placeholder-fixture
  convention. Verified: `gitleaks git --log-opts=b268f053..2520eeb7369c` rc=1
  before, rc=0 after; `gitleaks detect --no-git` on the tree: no leaks.
- Security-inventory constructor census: the harness now drives all load
  through the pooled `maistro.http` seam (`shared_client`), registering its
  loopback origins once up front via `configure_outbound_policy` (the
  operator-configured pattern, never adjacent to a fetch site). One real bug
  found by doing this: readiness probes inside `boot_stack` previously ran
  before origin registration and were refused by the default-deny policy —
  registration now precedes any fetch.
  `tests/test_check_security_inventory.py`: 48 passed.
- Vulture per-identity ledger (CI-repair mandate): `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → rc=0, 1402 reviewed identities = 1402
  findings at candidate head; nothing unbanked, ledger unamended.

F7 fixed in production code (see `pg-learnings-schema-fence.md`):
`PgLearningStore.ensure_schema` now fences its DDL behind
`pg_advisory_xact_lock(0x6D61656C)` in one transaction, the established
`events.pg_envelope` pattern. Round-1's live pg18 duplicate-key crash was in
exactly this statement.

Harness capabilities added (still `scripts/soak/` tooling; one collected test
added under `packages/maistro-core/tests/persistence/`, inventoried
separately):

- `--kill-signal SIGTERM` graceful-drain probe: signals the replica's whole
  process group, waits ≤ `SHUTDOWN_DRAIN_TIMEOUT` + slack for a clean exit,
  records `drained` / `drain_seconds` / `exit_code` / `escalated` and the
  5xx + connection-error delta across the drain window, escalates to SIGKILL
  on timeout (recorded, never silent), restarts and requires rejoin.
- Metrics gaps closed in `sample_once`: `pg_probe_ms` (real asyncpg
  round-trip latency on a dedicated pool, docker-exec psql kept as fallback
  channel), `driver_loop_lag_ms` (load driver event-loop sleep overshoot).
- Goal reconciliation scope, now explicit: goal→Run admission reconciliation
  lives in `maistro.scheduling.admission` (`_reconcile_claims`,
  `_reconcile_pending_fires`) and executes on every schedule admission; the
  cross-process occurrence fence it relies on is exercised live by
  `phase_claim_probe` every run (per-occurrence SQL gate). No separate
  goal-reconciliation daemon exists to soak; run 2 records this scoping in
  the profile instead of leaving it implicit.

Scratch validation run (NOT promotion evidence; dirty tree, 90 s ≪ 4 h,
evidence `/tmp/soak-round2b/` outside the repo):

- Concurrent two-replica boot: **10.9 s, both replicas ready** — the F7
  lottery path did not fire at the fix.
- `exactly_once_schedule_occurrence=true` (1 occurrence → 1 Run, loser
  `already_fired`), `rate_limit_enforced=true` (LB + direct), RSS/FD flat
  (0.0 % / 0 fds), `pg_probe_ms` 0.98–7.66, `driver_loop_lag_ms` ≤ 2.39.
- **F3 reproduced and sharpened**: 13001/13068 requests 502 through the LB
  during the sustained phase (round 0: 7445/7590; round 1: 1671/1733 —
  correction: round 1's commit message said 1671/2271, the evidence file's
  1671/1733 is correct). The 12 duplicate EO submissions all got 502
  (delivered 0): exactly-once under the storm remains unproven, not
  falsified.
- **New filed finding (drain defect, F8)**: under SIGTERM the replica logs
  "Shutting down" → "Waiting for application shutdown." and never completes —
  45.1 s window, `exited=false`, escalated to SIGKILL; 6579 5xx inside the
  drain window. Graceful drain is broken under load and must be fixed (and
  re-proven) before the promotion soak can claim shutdown behavior.
- H5 itemization (nonterminal `queued` runs after settle): 9 total, all
  itemized with run_ids — `eb185c1d32274b3f86f6e1649c69d483`,
  `a5f0b819d1a74291aa641d8e2360cba8`, `15def3bae377447aab90db8bfa3b1279`,
  `63a36fc7718a43a29008cb96e7e75ceb`, `94e504764a484f4592cb9c868deda70d`,
  `c936304b7aa14dc3aeb3c07097e56d33` (the six carried since the mini soak —
  the previously unitemized debt), plus
  `e5ce0126bb084e46ae2e14b174a29547`, `c1c8a2fffddb41c587dc8726f70ca29e`,
  `ed1d85bdbc564995927b8c537c5dea6a` created by this scratch run.
  Cohort attribution per ID is not proven (no per-row timestamp column was
  selected); the 6-vs-3 split rests on the mini-soak evidence recording 6.
- `--claim-probe` import resolution: verified `uv run python -c "import
  maistro.scheduling.admission"` succeeds on this tree (root workspace deps
  include maistro-core), so the documented bare-`uv run` sub-mode entry no
  longer depends on an undocumented venv state; the `run_migrations`
  `--package maistro-server` fix from round 1 remains for the server surface.

---

## Repair round 3 (this lane) — suite-inventory ledger format repair

State at entry: HEAD `74bfc53df3ca`, branch `auto-860`, tree clean. The
verifier's `check-suite-inventory.py --suite packages/maistro-core/tests`
failed with `cannot read ... as <suite>: <±count>` — this note's and
`pg-learnings-schema-fence.md`'s `inventory-delta:` blocks were written in a
shape the ledger cannot parse:

- entries for non-gated paths (`scripts/`, `docs/testing/soak/evidence/`) —
  the ledger only records gated suite recipes, and prose after the count is
  rejected rather than silently read as zero.
- the fence note keyed its delta to the per-file test path instead of the
  gated suite that contains it.

Repaired content, no count semantics changed: this note records **no**
`inventory-delta:` key at all (it moved no collected test — its own first
paragraph already says so, and that is the ledger's documented shape for a
count-free change); the fence note now records `packages/maistro-core/tests:
+1` with the test-name/FakeConnection prose kept in its body. Verified:
`--show` parses all 634 unfolded notes; `--suite packages/maistro-core/tests`
collects 11531 == expected 11531 (`ok: 1 suite(s) match`). Ruff check/format
clean, `test_pg_learnings.py` 27 passed/5 skipped, vulture ratchet 1402 ==
1402 (rc=0, ledger unamended), gitleaks clean over `b268f053..HEAD`,
canonical six-package mypy: no issues in 727 files. No soak semantics
touched; run-2 status (F3 and F8 open, promotion soak pending) stands.

---

## Independent verify round (this lane) — re-verification at merge head 52e0ec456

State at entry: HEAD `52e0ec456baa` (`Merge commit '0fb3dc69…' into auto-860`),
branch `auto-860`, tree clean. The merge touches none of this lane's files
(`git diff bcb7c14ec..52e0ec456` is empty over `scripts/soak/`,
`docs/testing/soak/`, `pg_learnings.py`, `test_pg_learnings.py`, and both
inventory notes), so every round-3 statement carries over unchanged.

Re-executed by the verifier (not trusted from any prior run):

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -q` → 27 passed, 5 skipped; `-k schema` fence test passes; the
  `pg_advisory_xact_lock` fence is present at
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py:141`.
- `uv run ruff check .` → pass.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` → 11531 == 11531, `ok: 1 suite(s) match`.

Verdict on this head stands: **NEEDS-REPAIR and re-soak** — promotion status
unchanged. Open items, re-derived from the tree and committed evidence:

- Promotion soak (≥ 4 h, exact RC artifact at the promotion head) has not run.
  Committed evidence is `m3a-soak-evidence.json` (head `b268f053`) and
  `m3a-repair-validation.json` (head `b5cf09b`, 120 s ≪ 4 h); neither signs
  `52e0ec456` or any RC artifact.
- F3 stands: committed `m3a-repair-validation.json` shows 1671 × 502 in the
  sustained phase and `task_admission_ratio` 0.0587 against the H6 ≥ 99 %
  budget.
- F8 stands and its machine evidence is uncommitted (scratch dir
  `/tmp/soak-round2b/` per round 2); only the narration is in-repo.
- Harness gate gap: `scripts/soak/run_soak.py:1156-1163` exit-gates only
  `exactly_once_task_admission`, `exactly_once_schedule_occurrence`,
  `rate_limit_enforced`, `replica_2_rejoined`; `lb_failover_bounded` (H4),
  `task_admission_ratio` (H6), `graceful_drain.ok`, `nonterminal_runs_after_settle`
  (H5), `rss_growth`/`fd_growth` (S1/S2) are recorded but never evaluated, so
  `all hard checks passed` (`run_soak.py:1167`) is reachable with failing
  bounds.
- `sustain_seconds` is consumed (`run_soak.py:901,907`) but never written to
  the evidence JSON, which the profile requires (`m3a-load-profile.md:114`).
- PR body for this head uses "Refs #860" only — no closure keywords; no issue
  closure performed from this lane.

---

## Repair round 4 (this lane) — promotion-gate enforcement and current drain probe

The verifier's gate finding was repaired in `scripts/soak/run_soak.py` rather
than narrated away: `failed_promotion_checks()` now makes H1–H6, the observed
four-hour duration, and a selected SIGTERM drain determine the CLI exit status.
The driver records both requested and observed `sustain_seconds`; captures
lock-consistent request-counter snapshots around the measured kill/rejoin
window; evaluates H6 only outside that window; requires `Retry-After` with
all three H3 429 probes; and enumerates every non-terminal Run before failing
H5. `tests/test_soak_promotion_gates.py` (2 passed) regression-tests that H4,
H5, H6, duration, and a required drain cannot be omitted from the exit result.

A fresh, deliberately short host-process preflight was executed after the
merge-head #819 shutdown change, outside the repository at
`/tmp/auto-860-soak-verify/`: `--sustain-seconds 20 --rps 1 --workers 1
--eo-concurrency 2 --rate-limit-probe-requests 20 --settle-seconds 1
--sample-interval 1 --out-dir /tmp/auto-860-soak-verify`. It exited 1 as
required, recording observed `sustain_seconds=20.64`, H1/H2 true, SIGTERM
`drained=true` in 22.3s without escalation, and correctly failed H3 (the tiny
20-request burst cannot exceed the configured burst), H5 (10 queued Runs,
enumerated), H6 (0.5), and duration. The earlier F8 **reproduction is no
longer current**: this host preflight observes a successful drain, but it is
not a promotion proof because it is short, dirty, host-process topology, and
still has H3/H5/H6 failures.

The remaining promotion blockers are intentional and explicit: no ≥4-hour
clean exact-Compose-image/configuration soak exists; the current driver is a
host-process preflight rather than `deploy/docker-compose.prod.yml`; and the
fresh preflight preserves nonterminal queue debt and sub-threshold admission.

---

## Repair round 5 (this lane) — F3 root-caused (LB dual-address poisoning), F9 fixed (ceiling→429), soak scope made per-run

State at entry: HEAD `c9d9b6250`, branch `auto-860`, tree clean. All five
verify findings from the round-4 verify were taken up; none were cosmetic.

- **F3 root cause found and fixed (soak-cell defect, production immune).**
  With the still-running round-5 scratch stack used as a live lab: the LB log
  showed nginx connecting to `host.docker.internal` as BOTH
  `[fdc4:f303:9324::254]` (IPv6 — `connect() failed (101: Network
  unreachable)`) and `192.168.65.254` (IPv4). nginx round-robins new upstream
  connections across a named peer's addresses and counts each v6 miss toward
  `max_fails` **for the peer**, so both replicas flapped into the passive
  down state under churn and the LB answered mass instant
  "no live upstreams" 502s. Bisect evidence: driver-mix load → 2661/2713 502;
  `/health/ready`-only → 1428/1428; live+submit (no ready) → clean; plain
  12-way concurrency at 636 rps → 99.97% 200 (warm pooled conns never roll
  the address dice). Production is immune (`deploy/nginx.conf` resolves
  compose service names to single addresses). Fix: the driver renders
  `nginx-soak-rendered.conf` with the resolved IPv4 literal (hash + IP in
  evidence) and captures `docker logs` of the LB to `lb.log` before teardown
  (F3 had been undiagnosable for four rounds because the LB side was deleted
  at cleanup). Adding `keepalive 32` (deploy parity, kept) alone did NOT fix
  the storm — the diagnosis above supersedes that hypothesis.
- **F9 (product) fixed**: full per-principal active-root-Run ceiling escaped
  `POST /tasks` as unhandled 500s (observed live: 100/131 concurrent
  submissions → 500 `RunConcurrencyExceeded`). Now 429 + `Retry-After`; see
  `m3a-860-f9-concurrency-backpressure-429.md` (inventory-delta:
  `packages/maistro-server/tests: +1`, 407 passed in the suite).
- **H5 made meaningful without weakening it**: every one of the round-4
  preflight's 10 nonterminal Runs was queried and is a prior claim-probe Run
  (`payload ? 'task_id'` = false on all 10) — zero stalled task work; the
  persistent DB just accumulated probe artifacts across runs. The driver now
  resets the dedicated soak schema before migrations (`--fresh-db` default,
  flag inside `soak_env_sha256`) and the claim probe terminalizes its own
  verified Run QUEUED→CANCELLED through `PgRunStore` after H2's SQL verdict
  (`probe_run_cleanup` in evidence; failed races preserve duplicates). The
  H5 == 0 gate itself is unchanged.
- **Drain-gate hardening** (round-4 verify finding): a missing/null
  `graceful_drain` record now fails `failed_promotion_checks` instead of only
  inspecting `required`-flagged dicts; two regression tests added to
  `tests/test_soak_promotion_gates.py` (4 passed).
- **H3 probe interpretable**: round-4's `rate_limit_enforced=false` came from
  a 20-request probe against burst 60 — no burst smaller than the budget can
  observe the limiter. Probe default is 800 (profile phase-5 spec) and
  `probe_requests`/`rate_limit_burst`/`probe_below_burst` travel with the
  strict verdict.
- **task_submit share 20% → ~4.8%** (profile round-5 amendment): measured
  degraded-executor drain (< 1 run/s/replica, no LiteLLM) cannot absorb the
  20% share; the ceiling now backpressures briefly and bounds the queue,
  which is what makes H5's settle-to-zero satisfiable. H6 counts 202 +
  designed-backpressure 429 as available; 5xx/conn failures still fail it.

Validated: ruff check/format clean; `packages/maistro-server/tests/api/` 407
passed; `tests/test_soak_promotion_gates.py` 4 passed; suite inventory
matches (+1 recorded); vulture 1402 == 1402 rc=0; six-package mypy clean.
Round-5 validation soak numbers: see `docs/testing/soak/m3a-soak-evidence.md`
(run 5) and `evidence/m3a-round5-*` — promotion status is decided there, not
in this note.

---

## Repair round 6 (this lane) — salvage of the timed-out round-5 writer; concurrent H3 burst; bounded teardown; gate-enforcing green evidence

State at entry: HEAD `6e8c866e5`, branch `auto-860`, with an uncommitted
`scripts/soak/run_soak.py` diff left by the timed-out round-5 writer (job
`6c4bf5d86f92`, `state: timed_out`, agent_exit 124). The diff was preserved
verbatim (`git diff > incoming-860-salvage.patch` before anything else),
validated, and completed — nothing was discarded.

Salvaged and committed as `b31c5fdaa` ("repair 6a"):

- **H3 burst probes made concurrent (16 lanes).** Round-5 final's
  `rate_limit_enforced=false` was probe-shape, not limiter: the sequential
  loop (~50 req/s locally) cannot outpace the 3000/min + 50/s-refill bucket,
  so the authenticated-through-LB probe observed 800×200. 16-way lanes
  deliver the profile's "> 100 req/s concentrated burst" shape; run 6 then
  observed 429 + `Retry-After` + `x-ratelimit-*` on all three probe paths
  (LB-auth 430×429), `enforced_everywhere=true`.
- **Bounded teardown.** Round-5 final stalled ~14 min between evidence write
  and exit on unbounded Docker Desktop CLI calls; `_teardown_lb` bounds every
  docker call at 60 s and `pg_pool.close()` at 30 s. Run 6 hit the 60 s
  `docker rm` guard, logged it, and exited immediately — failure mode closed.
- The round-4 verify's `graceful_drain`-gate hardening (missing key ⇒ fail)
  is in the tree with regression tests (`tests/test_soak_promotion_gates.py`,
  4 passed at this head).

Committed evidence (fixes the round-5 note's dangling references —
`evidence/m3a-round5-*` and the "(run 5)" pack section existed only in
`/tmp/soak-round5-final` and were never in git):

- `evidence/m3a-round5-final.json` + logs/metrics/rendered conf — head
  `6e8c866e5`, `git_clean=true`; first gate-enforcing run; every hard gate
  green except H3 (probe shape, above) and `sustain_duration` (90.17 s).
- `evidence/m3a-round6-shakedown.json` + logs/metrics/rendered conf — head
  `b31c5fdaa`, `git_clean=true`; re-executed live by this round (not trusted
  from any prior run): **H1–H6, graceful drain (SIGTERM, 2.0 s, no
  escalation), and rejoin all pass; exit 1 on `sustain_duration` only**
  (90.43 s ≪ 14400 s, the honest promotion blocker). Drain defect F8 does
  not reproduce at this head; the pack's run-6 section records the
  `health_ready` 503 provider-less-soak observation (degraded signaling
  working; attribution probable-not-proven) and the three remaining promotion
  separators (duration, exact Compose artifact, drain re-proof at duration).

Validation at `b31c5fdaa` + evidence/docs: ruff check/format clean on the
changed script and tree; `tests/test_soak_promotion_gates.py` 4 passed; the
promotion verdict for #89 remains **NEEDS-REPAIR and re-soak** — this round
upgrades the harness and proves all functional gates, it does not sign a
promotion (no ≥4 h exact-Compose soak exists).
