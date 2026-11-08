# Issue #860 — round 30: boot-hygiene repair + fresh soak at the exact head (repair round)

**Not promotion evidence or integration approval.** Round 29 ended BLOCKED on
the two external promotion gates (`sustain_duration`, `exact_rc_artifact`).
This round (a) re-verified every deterministic gate at the assigned head, (b)
found and fixed a genuine harness incident chain while re-running the soak,
and (c) produced a fresh functional-evidence pack bound to the exact new
commit with a clean tree.

## Harness incident chain found by execution (and repaired)

The first soak attempt of this round failed inside the harness, and the
failure mode mattered more than the failure:

1. A relative `--out-dir` was handed to `docker run -v` as a bind source;
   docker rejected it (`invalid characters for a local volume name`) **after
   both replicas were already up**.
2. `boot_stack`'s LB-failure path raised `RuntimeError("LB did not become
   ready")` **without killing the replicas** — the replica-failure path had
   the orphan doctrine, the LB path did not.
3. The retry then "booted in 0.0s" by silently adopting the orphans, and its
   `--fresh-db` schema reset landed under the orphans' live pools: the
   exactly-once probe returned **12×500**, admission ratio 0.0, 1943×502.
   That run is invalid as evidence; it was written to scratch only and is not
   committed.

Repairs landed as `c4f45b309` (scripts/soak/run_soak.py + tests):
`resolve_out_dir()` normalizes `--out-dir` before anything boots;
`ensure_replica_ports_free()` refuses to boot over occupied replica ports;
`kill_replicas_and_collect_orphans()` is shared cleanup, now used by the
LB-failure path too. Four regression tests added (`tests/: +4`, inventory
note `m3a-860-boot-hygiene`); the LB-leak test is **discriminated**: executed
against the pre-fix module it observes zero kills and would fail its
`len(killed) == 2` assertion. Worktree hygiene: attempt 1 overwrote the two
tracked fixed-name replica logs; both were restored byte-identically from
`HEAD` via `git show` redirects before anything was staged.

## Gate reconciliation at `c4f45b309` (re-executed this round)

| Check | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` (the round-22 `check-3.log` regression) | **38 passed, 6 skipped** — stays fixed |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | **56 passed** (52 + 4 new) |
| `uv run ruff check .` / `uv run ruff format --check .` | PASS / PASS |
| `uv run python scripts/check-backlog-consistency.py` | PASS (168 items) |
| `bash scripts/verify-monorepo-layout.sh` | PASS |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI argv) | rc=0 — 1332 reviewed == 1332 findings |
| `uv run python scripts/check-suite-inventory.py` | ok — 17 suites match; `tests/: +4` recorded in `m3a-860-boot-hygiene` |
| `git diff --numstat origin/develop -- quality/` | empty — `quality/` untouched |

## Fresh shakedown at `c4f45b309` (clean tree, scratch out-dir)

Started 2026-10-06T21:41:53Z, finished 21:51:22Z. Pack:
`evidence/m3a-round30-shakedown.json` — `hashes.git_head =
c4f45b309fd622f2e8a4b315dad35e721d81aad3` (**the exact head of this round's
fix commit**), `git_clean: true`, empty-diff hash. **47,175 requests /
420.08 s: 200×36541, 202×2264, 401×2845, 404×5525 — zero 5xx, zero
connection errors**; real boot 2.5 s; 212 metric rows, all `complete: true`,
zero unmeasured/unclassified PIDs; pg probe p95 3.25 ms (max 8.19), driver
loop lag max 2.03 ms, pg waiting locks max 0, sessions max 13 (≤ pool
budget); p95 task_submit 60.41 ms.

| Gate | Result |
| --- | --- |
| `exactly_once_task_admission` | **True** — 12 concurrent duplicates → 1 distinct run, 11 reconciled, statuses ⊆ {202} |
| `exactly_once_schedule_occurrence` | **True** (two-process race, 1 occurrence → 1 run) |
| `rate_limit_enforced` | **True** — enforced_everywhere across LB + both direct replicas |
| `lb_failover_bounded` | **True** — window 7.03 s, 0 5xx + conn errors vs 4320 budget; LB log shows only the 4 expected kill-window error lines |
| `replica_2_rejoined` | **True** (~6 s after SIGTERM) |
| `graceful_drain` | **True** — SIGTERM drained 1.0 s, rc 143, 0 5xx, 0 conn errors, no escalation |
| `nonterminal_runs_after_settle` | **True** — 0; final runs `completed=2265 cancelled=1` |
| `task_admission_availability` | **True** — ratio 1.0; 2248/2248 accepted 202 outside the kill window |
| `rss_growth` / `fd_growth` | informational (bounded; no leak signature) |
| `sustain_duration` | ok=**False**: 420.08 s vs 14400 s floor — unchanged external blocker (floor > the lane's 5400 s job budget) |
| `exact_rc_artifact` | ok=**False** — unchanged external blocker: the preflight runner refuses host-topology equivalence by design (`preflight_artifact_check`), and no release-owner RC designation exists (#89 owns RC selection) |

`failed_promotion_checks()` replay over the fresh pack:
`['sustain_duration', 'exact_rc_artifact']` — identical to rounds 6, 26–29.

## Acceptance state after this round

- **AC1** load profile: defined (`m3a-load-profile.md`); the stale
  "No new soak has validated this repair" note about the round-2 process-group
  sampler was corrected this round: rounds 26–30 exercised it in full soaks
  (round 30: 212/212 complete rows). RC designation remains the release
  owner's. PARTIAL (designation external).
- **AC2** ≥2 replicas: re-proven at the exact head (two replicas behind
  nginx). MET at harness grade.
- **AC3** sustained load: saturation/backpressure/leak/drain/restart observed
  again (420 s round 30 + 1200 s round-8 production stack); the 14400 s
  promotion floor is not executable in-lane. NOT MET for the floor.
- **AC4** exactly-once across replicas: re-proven at the exact head. MET at
  harness grade.
- **AC5** rate limiting: re-proven at the exact head; per-replica N×
  aggregate is the decided #842 policy. MET at harness grade.
- **AC6** metrics with pass/fail thresholds: emitted (212 rows) and gated by
  the now-56-test regression suite. MET.
- **AC7** kill/restart mid-load: graceful drain + bounded failover + rejoin
  re-proven at the exact head. MET at harness grade.
- **AC8** long soak of the exact RC artifact: BLOCKED on external
  prerequisites, unchanged — no release-owner RC designation; host preflight
  refuses equivalence by design; 14400 s exceeds the lane budget. The change
  clause is satisfied: the newest functional evidence binds to `c4f45b309`,
  which contains every merged runtime change through M1-B1 plus this round's
  harness fixes (harness-only diff; the soaked application code is identical
  to round 29's tip).
- **AC9** findings classification: the two failing checks are classified as
  external promotion prerequisites (rounds 21–30 handoffs); this round's new
  finding — the harness boot-hygiene chain — was fixed and tested in-lane
  rather than filed (fix landed with evidence above). GitHub filing remains
  prohibited in-lane. PARTIAL.
- **AC10** machine- + human-readable evidence tied to hashes: fresh pack +
  this handoff at the exact commit. MET for harness-grade rounds.

## Residual blockers (unchanged, external to lane authority)

1. A release-owner designation of the RC artifact/configuration (#89's
   selection), without which `exact_rc_artifact` cannot be satisfied by
   design.
2. A runner window ≥ 14400 s of the sustained profile against that exact
   artifact (production Compose), which no 5400 s lane job can host.

Until one of these changes, further soak rounds can only re-demonstrate the
same harness-grade evidence. The in-lane work is complete: every functional
gate is green at the exact head, all deterministic repo gates pass, and the
two remaining gates require decisions/resources above the lane.
