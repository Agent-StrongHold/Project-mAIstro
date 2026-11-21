# Issue #860 — round 28 develop-sync revalidation (repair round)

**Not promotion evidence or integration approval.** This round resolved the
pending lane item created after round 27: *origin/develop advanced +2 past the
round-27 merge base*. Because one of those commits (M1-B1 task admission
idempotency) changes the exact admission surface AC4 probes, the round-27
functional evidence was stale for a promotion candidate containing develop;
the merge moved the head (AC8's own change clause), so the full functional
shakedown was re-executed at the merged head.

## Develop sync: `5b0398e7b` merges 06a65a8ea + df00785bb

`git merge origin/develop` — **zero conflicts** (verified before merging by
comming `git diff --name-only 3f8ccbe9d..origin/develop` against the branch's
own changed-file list: empty intersection). develop's two commits are large
squashed WIP landings (117 files, +9652/−616):

- `06a65a8ea` — M9-C1 extension contract versioning/feature negotiation
  (`maistro/extensions/compat.py`, ADR-100526-9c55; no runtime admission path).
- `df00785bb` — M1-B1 stable idempotency contract for task submission
  (`maistro/tasks/idempotency.py` spine: explicit/fingerprint keys scoped by
  SHA-256 over (principal, Workspace, action, key), lease-guarded claim/
  complete/release, migration `038_task_idempotency`, +56 tests). This is a
  **runtime change to task admission** — the exact mechanism AC4's
  exactly-once probes exercise.

## Gate reconciliation at the merged head

| Reconciliation | Result |
| --- | --- |
| `uv sync --locked --extra dev` | clean (no new deps; `maistro_server` resolves via the dev/CI test path as in every prior round) |
| `uv run python scripts/check-suite-inventory.py` (17 suites) | **PASS, zero drift** — develop's own notes (`m1-1176-b1.md` et al.) pre-recorded the movement: 28,081 node IDs collected, 0 duplicates; **no delta note needed from this round** |
| `uv run ruff check .` / `uv run ruff format --check .` | PASS / PASS (3,094 files) |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 52 passed |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` (round-22 verifier argv) | 38 passed, 6 skipped — the `check-3.log` regression stays fixed (`cd77bb81c`) |
| `uv run python scripts/check-backlog-consistency.py` | PASS |
| `bash scripts/verify-monorepo-layout.sh` | PASS |
| `uv run python scripts/check-dependency-namespaces.py` | PASS — no unreviewed top-level namespaces |
| `uv run python scripts/check-reachability.py` | PASS — 170 unreachable == baseline |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI argv) | PASS — 1332 reviewed identities == 1332 findings; `quality/` untouched by this round |
| `git diff --numstat origin/develop -- quality/` | empty — no ledger rows lost |

## Fresh shakedown at the merged head

`DOCKER_HOST=unix:///run/user/1000/docker.sock uv run python
scripts/soak/run_soak.py --sustain-seconds 420 --out-dir
/home/dev/Git/wt/auto-860/docs/testing/soak/evidence` (absolute out-dir — see
round 26). Result at `hashes.git_head =
5b0398e7bdc439a8ed1aa2367a23b551bbd417b7`, evidence
`m3a-round28-shakedown.json` (46,880 requests / 420.07 s; 200×36306,
202×2257, 401×2828, 404×5489 — **zero 5xx, zero connection errors**; boot
2.6 s; 212 metric rows; driver loop lag max 2.64 ms; p95 task_submit
63.64 ms):

| Gate | Result |
| --- | --- |
| `exactly_once_task_admission` | **True** — 12 concurrent duplicate submissions → 1 distinct run, 11 duplicates reconciled by M1-B1's new idempotency spine; `runs_sharing_one_task_run_identity` = 0. **The AC4 probe now exercises the merged develop admission path, not just the pre-sync one.** |
| `exactly_once_schedule_occurrence` | **True** (two-process occurrence race: 1 occurrence → 1 run, duplicate claim reported) |
| `rate_limit_enforced` | **True** (800-request probes through the LB authenticated + unauthenticated and directly on both replicas; `enforced_everywhere=true`; documented scope: process-local per replica, aggregate = replicas × limit — the decided #842 policy) |
| `lb_failover_bounded` | **True** (kill window 6.02 s, window traffic 445×200/16×202/32×401/75×404 — 0 5xx + conn errors vs 4320 budget) |
| `replica_2_rejoined` | **True** (~6 s) |
| `graceful_drain` | **True** (SIGTERM drained 1.0 s, rc 143, `drain_5xx=0`, `drain_conn_errors=0`, no escalation) |
| `nonterminal_runs_after_settle` | **True** (0; final runs `completed=2258 cancelled=1`) |
| `task_admission_availability` | **True** (ratio 1.0; 0 × 429 outside the kill window) |
| `rss_growth` / `fd_growth` | informational: +8.2 % / +7.0 % (~15 MiB on ~182 MiB), FDs 30→43 max / 29→40 max — bounded, no leak signature |
| `sustain_duration` | ok=**False**: observed 420.07 s vs 14400 s floor — unchanged external blocker (floor > the lane's 5400 s job budget; single-foreground-command model) |
| `exact_rc_artifact` | ok=**False**: `host-uvicorn-preflight` refusal (design; no release-owner RC designation exists) — unchanged external blocker |

`failed_promotion_checks()` replay: `['sustain_duration', 'exact_rc_artifact']`
— identical to rounds 6, 26 and 27. Every functional gate is green at a head
that now contains the merged develop admission change.

Honesty notes: `git_clean: false` for the same reason as rounds 26–27 — the
tracked fixed-name outputs (`m3a-soak-evidence.json`, `metrics.jsonl`,
`replica-1820{1,2}.log`) are rewritten by the run itself; this round's copies
were renamed to the `m3a-round28-shakedown-*` names and the tracked files
restored from `HEAD` via `git show` (no work discarded); `git status` shows
exactly the six new untracked evidence files. Binding identity is
`hashes.git_head` plus `git_diff_sha256` (empty diff) / `git_status_sha256`
inside the pack. One observation differs from round 27 and is recorded as
observed: `pg_waiting_locks` peaked at **2** (transient) versus 0 in round 27 —
no lock-contruption signature (max 2 of pool 10+, sample window 212 rows), but
the number is reported as measured, not carried forward.

## Acceptance state after this round

- **AC1** load profile: defined (`m3a-load-profile.md`); RC designation of the
  profile still requires the release owner. PARTIAL.
- **AC2** ≥2 replicas: **re-proven at the merged head** (two replicas behind
  nginx, boot 2.6 s). MET at harness grade.
- **AC3** sustained load: saturation/backpressure/leak/drain/restart observed
  at the merged head (plus round-8's 1200 s run); the 14400 s promotion floor
  remains unmet anywhere and is not executable in-lane. NOT MET for the floor.
- **AC4** exactly-once across replicas: **re-proven at the merged head,
  now across M1-B1's rewritten admission path**. MET at harness grade.
- **AC5** rate limiting: enforcement re-proven at the merged head; per-replica
  N × aggregate is the decided, documented policy (`rate_limit.py`); #842
  closed. MET at harness grade under the claimed policy.
- **AC6** metrics with pass/fail thresholds: emitted (212 rows) and gated by
  the 52-test regression suite. MET.
- **AC7** kill/restart mid-load: graceful drain + bounded failover + rejoin
  re-proven at the merged head (0 5xx, 0 conn errors, 0 silent loss). MET at
  harness grade.
- **AC8** long soak of the exact RC artifact: **BLOCKED on external
  prerequisites, unchanged** — no release-owner RC designation exists;
  `preflight_artifact_check` refuses host-topology equivalence by design
  (`run_soak.py` — "This host-process preflight cannot sign promotion");
  14400 s floor exceeds the lane's 5400 s job budget. Requires release-owner
  action outside lane authority. What this round DID resolve is AC8's change
  clause for the develop sync: the newest functional evidence now binds to a
  head containing every merged runtime change, including M1-B1.
- **AC9** findings filed to earliest broken invariant: classifications
  recorded here and in rounds 21–27 handoffs; the two failing checks are
  classified as external promotion prerequisites, not runtime defects; GitHub
  filing remains prohibited in-lane. PARTIAL.
- **AC10** machine- + human-readable evidence tied to hashes: this pack +
  handoff at the merged head. MET for harness-grade rounds.

No tests were added (suite inventory reconciled by develop's own notes; no
delta note required); no production code, gates, ledgers, or pre-existing
evidence were modified. The six new evidence files and this handoff are this
round's outputs, plus the develop-sync merge commit `5b0398e7b`.
