# Issue #860 — round 44 (job 17fd3aa8) verification: stale check-3 failure
# confirmed repaired at HEAD; full driver sequence re-executed green

**Not promotion evidence or integration approval.** This round re-executed the
exact deterministic sequence that failed in job `98a11313` (check-3.log,
`assert 24 == 21` in `test_ensure_schema_fences_ddl_behind_advisory_lock`)
against this round's starting head `215bdec8adcc20e15b7bc268822caed9e55b11af`,
replayed the round-43 promotion gates from the archived pack, and confirmed the
two terminal blockers remain external and unchanged. No source, test, gate, or
ledger file changed; the only artifact is this handoff note.

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`,
  starting head `215bdec8adcc20e15b7bc268822caed9e55b11af` (clean on arrival),
  develop base `0d49d4e068de9ecbf0f9510e33781dba8abc87de`.
- The supplied prior failure (`98a11313/check-3.log`) ran at head `872fd2ceae`
  — **before** `cd77bb81c` ("extend learnings schema-fence coverage to the
  merged M4-B2 Gauntlet columns"), which is an ancestor of the starting head
  (`git merge-base --is-ancestor cd77bb81c HEAD` → true). Production
  `ensure_schema` emits 24 DDL statements (16 `_EPISTEMIC_COLUMNS` rows incl.
  `validated_evaluator_version`/`validation_run_ids`/
  `validation_content_hash`, plus `org_id`, `stage`, `validated_by`,
  `promoted_by`, the transitions table, and three indexes); the committed test
  pins the same 24-entry ordered list. The failure is stale.

## Deterministic checks re-executed this round at `215bdec8a` (all green)

Exactly the `98a11313` driver argv, in order:

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra dev` | resolved, no drift |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q -x` | **38 passed, 6 skipped** (the previously failing fence test included) |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | ok: 1 suite matches |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-server/tests` | ok: 1 suite matches |

Additional acceptance validation executed this round:

- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py
  -q` → **81 passed**.
- `failed_promotion_checks()` (pure function) replayed on
  `docs/testing/soak/evidence/m3a-round43-shakedown.json`: functional gates all
  ok — `exactly_once_task_admission`, `exactly_once_schedule_occurrence`,
  `rate_limit_enforced`, `lb_failover_bounded`, `replica_2_rejoined`,
  `graceful_drain`, `nonterminal_runs_after_settle`,
  `task_admission_availability`; failed list is exactly
  `['sustain_duration', 'exact_rc_artifact']` — identical to the round-43
  record at `hashes.git_head = 3da4e035eb1f…`.
- Parent #89 re-read from this round's own dispatch capture: **open**, "M3-A7 —
  Run RC soak and byte-equivalent final promotion", acceptance requires RC
  artifacts "built only from the candidate commit" — no RC designation exists
  (linked PRs #1567/#1602 closed unmerged, #1672 open draft).

## Acceptance ledger (issue #860's ten rows)

| Row | State |
| --- | --- |
| Representative load profile | Proven — `profile` in pack; request mix in `kind_counts` (49,151 requests, 5 kinds) |
| ≥ 2 application replicas | Proven — 2× replicas :18201/:18202 behind nginx LB, boot 2.6 s, logs committed |
| Sustained load w/ pool, queue, lease, retry, memory, FD, shutdown observation | Proven at shakedown scale — RSS +6.8/8.3 %, FD 30→38 / 29→35, p95 ≤ 47 ms, admission ratio 1.0, SIGTERM drain; the ≥ 4 h RC-soak remainder is row 8 |
| Exactly-once admission/occurrence/scheduling across replicas | Proven — 12 duplicate submissions → 1 run; pinned occurrence race → 1 run, loser `already_fired` |
| Rate limiting effective, no replica-selection bypass | Proven — enforced through LB and directly per replica, authenticated and unauthenticated |
| Metrics with explicit pass/fail thresholds | Proven — `thresholds.checks` with numeric bounds (RSS/FD growth, failover budget 4,320 s window, admission ratio ≥ 0.99) |
| Kill/restart one replica mid-work | Proven — SIGTERM drain 1.0 s, 0 5xx, 0 conn errors, no escalation, rejoin ~6 s, 0 nonterminal runs after settle |
| Long-running soak of the exact RC artifact | **Externally blocked** — no RC exists to soak (parent #89 open, no designation); `exact_rc_artifact` refuses by design with no CLI override |
| Findings filed/fixed to broken invariants | Proven — F7 learnings schema fence (advisory lock + ordered-DDL test), F10 LB retry fix, drain probe, admission/rate-limit harness hardening (`b5cf09bbe`…`fc143e11a`, `74bfc53df`, `c4f45b309`) |
| Machine- and human-readable evidence tied to hashes | Proven — `m3a-round43-shakedown.json` + logs bound to `git_head` 3da4e035eb, PG image digest, nginx/env sha256; handoff docs per round |

8 of 10 rows carry executed evidence; the remaining 2 are the single external
dependency expressed twice (a release-owner-designated RC, and the ≥ 14,400 s
soak of that RC). Rounds 26–43 hit the identical terminal pair; further
in-lane repair rounds cannot change it.

## Handoff

No code repair exists for the remaining rows: they require a release owner to
designate an RC (commit + Compose image/configuration) and a production runner
for the 4-hour soak. The harness already supports that run unchanged (round 43
proved Docker works here via `DOCKER_HOST=unix:///run/user/1000/docker.sock`).
This lane's deterministic surface is fully green at the starting head; the
verdict this round escalates the external decision instead of re-reporting
BLOCKED, because automated rounds are provably at a fixed point.

Progress: checked 1 issue; done 0 acceptance-complete issues (8/10 rows
evidenced, 2 externally blocked); skipped 0; validation-command errors 0;
escalated 1 (release-owner RC designation, parent #89).
