# Issue #860 — round 26 functional-shakedown revalidation (repair round)

**Not promotion evidence or integration approval.** This round re-executed the
deterministic battery at the assigned head `9b443c3c9` **and** ran a fresh
full functional shakedown of the two-replica cell at that head, because the
last full functional validation (round 6, `b31c5fdaa`) predated both the M4-B2
Gauntlet-columns merge (`20c975f3b`) and the develop M9 merge (`09ed6e6da`) —
the issue's own "any code/runtime-config change requires a new soak" clause
made the functional gates stale even though the 14400 s promotion soak remains
blocked on external prerequisites.

## Fresh evidence: `m3a-round26-shakedown.json` at head `9b443c3c9`

`uv run python scripts/soak/run_soak.py --sustain-seconds 420 --out-dir
/home/dev/Git/wt/auto-860/docs/testing/soak/evidence` (absolute out-dir is
required: the nginx LB is a bind-mounted docker container and a relative path
fails the volume-name check — first attempt aborted at LB boot and was cleaned
up: orphaned replica process groups killed, no stray containers, ports freed).

Result at `hashes.git_head = 9b443c3c91e7c6344ddead7ab8cf4521a48ff3f4`
(46,273 requests; status counts 200×35811, 202×2235, 401×2791, 404×5436 —
zero 5xx, zero connection errors):

| Gate | Result |
| --- | --- |
| `exactly_once_task_admission` | **True** |
| `exactly_once_schedule_occurrence` | **True** |
| `rate_limit_enforced` | **True** (429 + Retry-After observed through LB and directly on every replica, authenticated and unauthenticated) |
| `lb_failover_bounded` | **True** |
| `replica_2_rejoined` | **True** (SIGTERM drain 1.0 s, rc 143, `drain_5xx=0`, `drain_conn_errors=0`, no escalation; rejoin ~7 s) |
| `graceful_drain` | **ok=True** |
| `nonterminal_runs_after_settle` | **True** (count 0) |
| `task_admission_availability` | **True** (2215/2215 outside kill window, ratio 1.0) |
| `rss_growth` / `fd_growth` | informational: +8.2 % / +7.4 % (~15 MiB on ~180 MiB), FDs 30→43 max / 29→42 max — bounded, no leak signature |
| `sustain_duration` | ok=**False**: observed 420.09 s vs 14400 s floor |
| `exact_rc_artifact` | ok=**False**: `host-uvicorn-preflight` refusal (design; no CLI override) |

`failed_promotion_checks()` replay of the pack: `['sustain_duration',
'exact_rc_artifact']` — identical to the round-6 shakedown's failure set. The
functional gate set has now been observed green at a head containing every
merged runtime change.

Honesty notes: the pack records `git_clean: false` because the tracked
fixed-name output files (`m3a-soak-evidence.json`, `metrics.jsonl`,
`replica-1820{1,2}.log`) are rewritten during the run; at evidence-write time
the only dirty paths were this run's own in-flight outputs. `git diff
--stat`-equivalent verification: after renaming the outputs to the
`m3a-round26-shakedown-*` names and restoring the tracked files from `HEAD`
via `git show`, `git status` shows exactly the six new untracked evidence
files. The binding identity is `hashes.git_head` plus the recorded
`git_diff_sha256`/`git_status_sha256`.

## #842 reconciliation (corrects rounds 21–25's framing)

Rounds 21–25 described the cross-replica rate-budget question as "pending
#842's ownership decision, outside lane authority". That is stale: **#842 is
closed as completed** (2026-09-07, per dispatch evidence), and its acceptance
reads "Distributed/supported multi-replica deployments share enforcement state
or explicitly fail safe **within the claimed policy**; a process-local limiter
cannot be advertised as cluster-wide." The shipped policy
(`packages/maistro-server/src/maistro_server/api/rate_limit.py:25-34`)
documents process-local enforcement with aggregate = N × limit, deliberately
not advertised as cluster-wide — i.e. the decided policy, not a pending
decision. The soak gate already encodes exactly that policy (per-replica 429 +
Retry-After; no cluster-wide budget requirement). Selecting a replica therefore
gains at most the documented N × aggregate — that is the claimed policy, not a
bypass. AC5's remaining gap is not ownership: it is the same gap as AC8 — the
gates have not been observed against a release-owner-designated RC artifact.

## Deterministic battery re-executed at `9b443c3c9`

| Command | Result |
| --- | --- |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 52 passed |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` (round-22 verifier argv) | 38 passed, 6 skipped |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-server/tests` | PASS |
| `uv run python scripts/check-backlog-consistency.py` | PASS |
| `bash scripts/verify-monorepo-layout.sh` | PASS |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI argv) | PASS |
| `git diff --numstat origin/develop -- quality/` | empty — no ledger rows lost |

## Acceptance state after this round

- **AC1** load profile: defined (`m3a-load-profile.md`); RC designation of the
  profile still requires the release owner. PARTIAL.
- **AC2** ≥2 replicas: exercised and re-proven at the current head (this
  round's cell: two replicas behind nginx). MET for the host-uvicorn cell;
  promotion-grade (exact RC artifact) still pending.
- **AC3** sustained load: saturation/backpressure/leak/drain/restart behaviors
  observed (this round + round-8 1200 s); 14400 s floor not reached anywhere.
  NOT MET for the floor.
- **AC4** exactly-once across replicas: **re-proven at current head** (task
  admission + schedule occurrence, concurrent duplicate Idempotency-Key and
  two-process occurrence race). MET at harness grade.
- **AC5** rate limiting under concurrency: per-replica enforcement re-proven
  at current head; policy reconciliation to completed #842 recorded above.
  MET at harness grade under the claimed policy; bypass-by-replica-selection
  within the documented aggregate is the policy, not a defect.
- **AC6** machine-readable metrics with thresholds: emitted and gated
  (52-test regression suite). MET.
- **AC7** kill/restart mid-load: graceful drain + failover + rejoin proven at
  current head (0 5xx, 0 conn errors, 0 silent loss). MET at harness grade.
- **AC8** long soak of the exact RC artifact: **BLOCKED** — unchanged external
  prerequisites: no release-owner RC designation; `preflight_artifact_check`
  refuses host-topology equivalence by design; 420 s/1200 s ≪ 14400 s. No
  in-lane path exists (a 4 h soak is also outside the lane's single-command
  execution model).
- **AC9** findings filed to earliest broken invariant: classification recorded
  here and in rounds 21–25 handoffs; GitHub filing remains prohibited in-lane.
  PARTIAL.
- **AC10** machine- + human-readable evidence tied to hashes: this pack +
  handoff. MET for harness-grade rounds.

No tests were added (no inventory delta required); no production code, gates,
ledgers, or pre-existing evidence were modified. The six new evidence files
are the round-26 shakedown outputs.
