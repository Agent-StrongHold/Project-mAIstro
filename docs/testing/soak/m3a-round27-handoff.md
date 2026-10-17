# Issue #860 — round 27 develop-sync revalidation (repair round)

**Not promotion evidence or integration approval.** This round resolved the
pending lane item from round 26's result — *origin/develop advanced +1
(3f8ccbe9d, M9-H2 #2016) after the lane base; next sync must reconcile the
suite inventory* — and, because the merge moves the branch head (and AC8's own
clause makes any head move stale the functional gates), re-executed the full
functional shakedown at the merged head.

## Develop sync: `68961ab76` merges 3f8ccbe9d

`git merge origin/develop` — **zero overlapping files** (auto-860 touches soak
evidence/docs; develop adds `packages/maistro-ext-harness` plus gate
registrations), so the merge is trivial and needed no conflict resolution.
What the sync does change is the self-describing gates' input space:

| Reconciliation | Result |
| --- | --- |
| `uv sync --locked --extra dev` | installs `maistro-ext-harness==0.9.0` workspace member |
| `uv run python scripts/check-suite-inventory.py` (all 17 suites) | **PASS** — new suite collects exactly its recorded arithmetic: baseline `0` + `974-ext-host-harness` note delta `+138` = 138 collected; no drift in any other suite (27,932 node IDs, 0 duplicates) |
| `uv run python scripts/check-reachability.py` | PASS — 170 unreachable == baseline (develop registered the harness CLI/`__main__` roots) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI argv) | PASS — 1332 reviewed identities == 1332 findings; `quality/` untouched |
| `git diff --numstat origin/develop -- quality/` | empty — no ledger rows lost |
| `uv run ruff check .` / `uv run ruff format --check .` | PASS / PASS (3,088 files) |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 52 passed |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` (round-22 verifier argv) | 38 passed, 6 skipped — the round-22 `check-3.log` regression stays fixed (`cd77bb81c`) |
| `uv run python scripts/check-backlog-consistency.py` | PASS |
| `bash scripts/verify-monorepo-layout.sh` | PASS |
| `uv run python scripts/check-dependency-namespaces.py` | PASS — no unreviewed top-level namespaces |

No inventory delta note was needed from this round: the merge introduced no
test-count movement in any pre-existing suite, and the harness suite's `+138`
delta was already recorded by develop's own `974-ext-host-harness` note.

## Fresh shakedown at the merged head

`DOCKER_HOST=unix:///run/user/1000/docker.sock uv run python
scripts/soak/run_soak.py --sustain-seconds 420 --out-dir
/home/dev/Git/wt/auto-860/docs/testing/soak/evidence` (absolute out-dir
required — see round 26). Result at
`hashes.git_head = 68961ab76284c7f23b157097c8ff7890bec983a3`, evidence
`m3a-round27-shakedown.json` (45,348 requests; 200×35101, 202×2193, 401×2727,
404×5327 — **zero 5xx, zero connection errors**; boot 2.8 s; 212 metric rows;
driver lag max 2.16 ms; pg_waiting_locks 0 throughout):

| Gate | Result |
| --- | --- |
| `exactly_once_task_admission` | **True** (concurrent duplicate Idempotency-Key; `runs_sharing_one_task_run_identity` = 0) |
| `exactly_once_schedule_occurrence` | **True** (two-process occurrence race) |
| `rate_limit_enforced` | **True** (800-request probes through the LB and directly on both replicas) |
| `lb_failover_bounded` | **True** (kill window 7.04 s, window traffic 200×505/202×20/401×38/404×81 — no 5xx, no conn errors) |
| `replica_2_rejoined` | **True** (~7 s) |
| `graceful_drain` | **True** (SIGTERM drained 1.0 s, rc 143, `drain_5xx=0`, `drain_conn_errors=0`, no escalation) |
| `nonterminal_runs_after_settle` | **True** (0; final runs `completed=2194 cancelled=1`) |
| `task_admission_availability` | **True** (ratio 1.0 outside the kill window) |
| `rss_growth` / `fd_growth` | informational: +8.3 % / +7.5 % (~15 MiB on ~182 MiB), FDs 30→43 max / 29→41 max — bounded, no leak signature |
| `sustain_duration` | ok=**False**: observed 420.06 s vs 14400 s floor — unchanged external blocker |
| `exact_rc_artifact` | ok=**False**: `host-uvicorn-preflight` refusal (design; no release-owner RC designation exists) — unchanged external blocker |

`failed_promotion_checks()` replay: `['sustain_duration', 'exact_rc_artifact']`
— identical to rounds 6 and 26. The functional gate set remains green at a head
containing every merged runtime change, now including the develop M9-H2 sync.

Honesty notes: `git_clean: false` for the same reason as round 26 — the tracked
fixed-name outputs (`m3a-soak-evidence.json`, `metrics.jsonl`,
`replica-1820{1,2}.log`) are rewritten by the run itself. This round's copies
were renamed to the `m3a-round27-shakedown-*` names and the tracked files
restored from `HEAD` via `git show` (no work discarded); `git status` shows
exactly the six new untracked evidence files. Binding identity is
`hashes.git_head` plus `git_diff_sha256`/`git_status_sha256` inside the pack.

## Acceptance state after this round

Unchanged in substance from round 26; evidence is now bound to the merged head
rather than the pre-sync head:

- **AC1** load profile: defined (`m3a-load-profile.md`); RC designation of the
  profile still requires the release owner. PARTIAL.
- **AC2** ≥2 replicas: **re-proven at the merged head** (two replicas behind
  nginx, boot 2.8 s). MET at harness grade.
- **AC3** sustained load: saturation/backpressure/leak/drain/restart observed
  at the merged head (plus round-8's 1200 s run); the 14400 s promotion floor
  remains unmet anywhere and is not executable in-lane (single-foreground-
  command model). NOT MET for the floor.
- **AC4** exactly-once across replicas: **re-proven at the merged head**. MET
  at harness grade.
- **AC5** rate limiting: per-replica enforcement **re-proven at the merged
  head**; #842 closed/completed — per-replica N × aggregate is the decided,
  documented policy (`rate_limit.py:25-34`), so replica selection buys the
  documented aggregate, not a bypass. MET at harness grade under the claimed
  policy.
- **AC6** metrics with pass/fail thresholds: emitted (212 rows) and gated by
  the 52-test regression suite. MET.
- **AC7** kill/restart mid-load: graceful drain + bounded failover + rejoin
  **re-proven at the merged head** (0 5xx, 0 conn errors, 0 silent loss). MET
  at harness grade.
- **AC8** long soak of the exact RC artifact: **BLOCKED** — external
  prerequisites unchanged (no release-owner RC designation;
  `preflight_artifact_check` refuses host-topology equivalence by design;
  14400 s floor not executable in-lane). Requires release-owner action.
- **AC9** findings filed to earliest broken invariant: classified here and in
  rounds 21–26 handoffs; GitHub filing remains prohibited in-lane. PARTIAL.
- **AC10** machine- + human-readable evidence tied to hashes: this pack +
  handoff at the merged head. MET for harness-grade rounds.

No tests were added (no inventory delta required); no production code, gates,
ledgers, or pre-existing evidence were modified. The six new evidence files
and this handoff are this round's outputs, plus the develop-sync merge commit.
