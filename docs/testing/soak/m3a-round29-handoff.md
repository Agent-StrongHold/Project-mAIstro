# Issue #860 — round 29 independent revalidation at the branch tip (repair round)

**Not promotion evidence or integration approval.** This round resolved the
pending lane block — the previous worker requested NEEDS-DEEP-REVIEW after a
verifier round (`job 98a11313…`) failed `check-3.log`
(`test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock`,
24 != 21 expected DDL statements at head `872fd2cea`) and the next repair
attempt died on a provider timeout without executing. The regression was
already repaired in round 24 (`cd77bb81c`); this round independently
re-verified it and every deterministic gate at the current tip, then re-ran
the full functional shakedown so the newest evidence binds to the exact
branch tip `94d5304a0` rather than the docs-only ancestor `5b0398e7b` that
round 28's pack recorded.

## Gate reconciliation at `94d5304a0` (all commands re-executed this round, not carried forward)

| Check | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q -x` (round-22 verifier argv / `check-3.log` regression) | **38 passed, 6 skipped** — regression stays fixed |
| `uv run ruff check .` / `uv run ruff format --check .` | PASS / PASS (3,094 files already formatted) |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 52 passed |
| `uv run python scripts/check-backlog-consistency.py` | PASS (168 items) |
| `bash scripts/verify-monorepo-layout.sh` | PASS |
| `uv run python scripts/check-dependency-namespaces.py` | PASS — no unreviewed top-level namespaces |
| `uv run python scripts/check-reachability.py` (exit code captured) | rc=0 — 170 unreachable == baseline |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI argv, exit code captured) | rc=0 — 1332 reviewed identities == 1332 findings |
| `uv run python scripts/check-suite-inventory.py` (CI argv, ci.yml:622) | ok — 17 suites match the recorded inventory (no tests added this round, zero drift; **no delta note needed**) |
| `git diff --numstat origin/develop -- quality/` | empty — no ledger rows lost; `quality/` untouched |

Round-28 claim replay: `failed_promotion_checks()` over
`m3a-round28-shakedown.json` returns `['sustain_duration', 'exact_rc_artifact']`
— matches the handoff verbatim.

## Fresh shakedown at the branch tip

`DOCKER_HOST=unix:///run/user/1000/docker.sock uv run python
scripts/soak/run_soak.py --sustain-seconds 420 --out-dir
/home/dev/Git/wt/auto-860/docs/testing/soak/evidence`. Started
2026-10-06T20:47:36Z, finished 20:57:02Z. Evidence
`m3a-round29-shakedown.json` with `hashes.git_head =
94d5304a02b7fe16c3c08731daec46163da3ede6` (**the exact branch tip**, closing
the round-28 binding gap: that pack bound to `5b0398e7b`, an ancestor whose
delta to the tip is docs-only) and `git_diff_sha256` = empty-string hash
(sampled pre-rewrite; worktree diff empty at commit time). 46,003 requests /
420.1 s: 200×35606, 202×2224, 401×2774, 404×5399 — **zero 5xx, zero
connection errors**; boot 2.6 s; 212 metric rows; p95 task_submit 73.36 ms.

| Gate | Result |
| --- | --- |
| `exactly_once_task_admission` | **True** — 12 concurrent duplicate submissions → 1 distinct run, 11 duplicates reconciled by M1-B1's idempotency spine; `runs_sharing_one_task_run_identity` = 0 |
| `exactly_once_schedule_occurrence` | **True** (two-process occurrence race: 1 occurrence → 1 run, duplicate claim reported) |
| `rate_limit_enforced` | **True** (800-request probes via LB + both replicas, `enforced_everywhere=true`; process-local per replica per the decided #842 policy) |
| `lb_failover_bounded` | **True** (kill window 8.52 s; 0 5xx + conn errors vs 4320 budget; LB log's only errors are the 4 expected connection-refused/`temporarily disabled` lines inside the deliberate window) |
| `replica_2_rejoined` | **True** (~8 s after SIGTERM) |
| `graceful_drain` | **True** (SIGTERM drained 1.0 s, rc 143, `drain_5xx=0`, `drain_conn_errors=0`, no escalation) |
| `nonterminal_runs_after_settle` | **True** (0; final runs `completed=2225 cancelled=1`) |
| `task_admission_availability` | **True** (ratio 1.0; 0 × 429 outside the kill window; 2195/2195 submissions accepted) |
| `rss_growth` / `fd_growth` | informational: +7.7 % / +7.0 % (~14 MiB on ~183 MiB), FDs 30→44 max / 29→41 max — bounded, no leak signature |
| `sustain_duration` | ok=**False**: observed 420.1 s vs 14400 s floor — unchanged external blocker (floor > the lane's 5400 s job budget) |
| `exact_rc_artifact` | ok=**False**: host-uvicorn-preflight refusal ("not the exact production Compose image and configuration") — unchanged external blocker; no release-owner RC designation exists |

`failed_promotion_checks()` replay over the fresh pack:
`['sustain_duration', 'exact_rc_artifact']` — identical to rounds 6, 26, 27
and 28. Every functional gate is green, now at the branch tip itself.

Honesty notes: `git_clean: false` inside the pack for the same reason as
rounds 26–28 — the tracked fixed-name outputs are rewritten by the run; this
round's copies were renamed to `m3a-round29-shakedown-*` and the tracked files
restored byte-identically from `HEAD` via `git show` redirects (`git status`
shows exactly the six new untracked evidence files; no modification to any
tracked file). One observation differs from round 28 and is recorded as
measured: `pg_waiting_locks` max **0** across all 212 rows (round 28 peaked
transiently at 2). No tests were added (suite inventory zero drift; no delta
note required); no production code, gates, ledgers, harness flags, or
pre-existing evidence were modified.

## Acceptance state after this round

- **AC1** load profile: defined (`m3a-load-profile.md`); RC designation of the
  profile still requires the release owner. PARTIAL.
- **AC2** ≥2 replicas: re-proven at the branch tip (two replicas behind nginx,
  boot 2.6 s). MET at harness grade.
- **AC3** sustained load: saturation/backpressure/leak/drain/restart re-observed
  at the branch tip (plus round 8's 1200 s run); the 14400 s promotion floor
  remains unmet anywhere and is not executable in-lane. NOT MET for the floor.
- **AC4** exactly-once across replicas: re-proven at the branch tip across
  M1-B1's admission path. MET at harness grade.
- **AC5** rate limiting: re-proven at the branch tip; per-replica N × aggregate
  is the decided, documented policy; #842 closed. MET at harness grade.
- **AC6** metrics with pass/fail thresholds: emitted (212 rows) and gated by
  the 52-test regression suite. MET.
- **AC7** kill/restart mid-load: graceful drain + bounded failover + rejoin
  re-proven at the branch tip (0 5xx, 0 conn errors, 0 silent loss). MET at
  harness grade.
- **AC8** long soak of the exact RC artifact: BLOCKED on external
  prerequisites, unchanged — no release-owner RC designation exists;
  `preflight_artifact_check` refuses host-topology equivalence by design;
  14400 s floor exceeds the lane's 5400 s job budget. AC8's change clause is
  satisfied: the newest functional evidence binds to the branch tip containing
  every merged runtime change through M1-B1.
- **AC9** findings filed to earliest broken invariant: the two failing checks
  are classified as external promotion prerequisites, not runtime defects
  (rounds 21–29 handoffs); GitHub filing remains prohibited in-lane. PARTIAL.
- **AC10** machine- + human-readable evidence tied to hashes: fresh pack +
  this handoff at the exact branch tip. MET for harness-grade rounds.

Residual blockers are unchanged and external to lane authority: release-owner
RC designation + a ≥14400 s soak of that exact artifact on production Compose.
