# Issue #860 round-37 independent revalidation (job 68640d0d)

- Branch tip at start and end: `550f5d3ac0918322f74fba2a9e1b6e45935bab5d` (round-36
  docs tip; tree clean, no develop action required — base `1df433bf5` is already
  merged into this lineage via `653620201a`).
- The driver for this job executed **no deterministic checks** (`checks: []` in
  `manifest.json`; no `check-*.log` files in the job directory). Every gate and
  evidence claim below was re-executed/re-derived by the worker at this head,
  not trusted from round 36.

## Deterministic gates re-executed this round (CI argv, all green)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3105 files already formatted |
| `uv run python scripts/check-suite-inventory.py` | ok: 17 suite(s) match |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1332 reviewed identities -> 1332 findings, rc=0 |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |
| `bash scripts/verify-monorepo-layout.sh` | ok |
| `uv run python scripts/check-contract-markers.py` | OK |
| `uv run mypy <10 CI src dirs>` | Success: no issues found in 1007 source files |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/scheduling/test_pg_admission.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | 57 passed, 2 skipped |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -q` | 53 passed, 6 skipped (the round-33 stale failure is dead) |
| `uv run pytest packages/maistro-core/tests/extensions packages/maistro-core/tests/graph/durable_runs tests/tools/registry tests/test_check_closure_targets.py packages/maistro-registry/tests -q` | 1302 passed, 42 skipped |

## Evidence re-derived from raw artifacts at this head

- `failed_promotion_checks()` imported live from `scripts/soak/run_soak.py:700`
  on the round-30 pack -> `['sustain_duration', 'exact_rc_artifact']`;
  `sustain_seconds=420.08`, `git_head=c4f45b309…`, `git_clean=true`. The two
  failures are structural: the host-uvicorn preflight records
  `topology: "host-uvicorn-preflight"` and there is no override flag.
- AC6 re-computed from the raw `m3a-round30-shakedown-metrics.jsonl` (212
  samples): `pg_connections` 5–13, `pg_waiting_locks` max 0,
  `driver_loop_lag_ms` max 2.03, `pg_probe_ms` max 8.19, fds 30→35
  (max 42/40). RSS growth recomputed per-replica process group from the first
  complete sample: 7.0% / 5.2% (S1 < 20% holds). A naive min-over-all-samples
  computation shows 51.2% for replica_2 only because sample #74 falls inside
  the kill/restart window, where the killed application child is absent and
  only the wrapper is measured — the pack's first-complete-sample semantics is
  the correct one and matches row 0 (`complete=true`, 182936 KB).
- AC4 spot re-read: `exactly_once_tasks` = 12 concurrent submissions,
  12 delivered, 1 distinct run id, 11 duplicates, statuses 12×202;
  `exactly_once_schedule_claim` = 1 run for the raced occurrence, loser
  reported `already_fired`, 0 occurrences with multiple runs. The same seam is
  exercised by the committed cross-process test
  (`packages/maistro-core/tests/scheduling/test_pg_admission.py`, passing).
- AC5 spot re-read: 429 + `Retry-After` + `x-ratelimit-remaining: 0` on all six
  burst paths (LB + both direct replicas × authenticated/unauthenticated),
  `enforced_everywhere` true; N× aggregate is documented #842 policy.
- AC7 spot re-read: `kill_restart` SIGTERM, `drained=true`, 0 5xx and 0 conn
  errors in the 7.03 s window, `rejoined=true`, exit 143.

## AC8 external blocker re-confirmed at capture time

- Regex sweep of all 176 issue comments in this job's dispatch context
  (captured 2026-10-07T02:29Z): **0** release-candidate/RC-designation matches.
  No release owner has designated the RC artifact that #89 would promote.
- Production drift since the pack's `git_head=c4f45b309` re-measured:
  27 non-docs paths including `packages/maistro-core/src/maistro/extensions/*`
  (ADR-104/#950), `graph/durable_runs/execution_store.py` (#1334),
  `packages/maistro-registry/src/maistro_registry/*` (#2023). Under the
  artifact-identity contract in `m3a-load-profile.md`, the promotion-signing
  soak must postdate the `653620201a` merge — unchanged from round 36.

## Terminal condition (identical to rounds 33–36, now with fresh evidence)

The two remaining failed promotion gates cannot be satisfied by any in-lane
action:

1. `exact_rc_artifact` requires the exact production Compose image/config of a
   release-candidate that **no release owner has designated** (0/176 comments).
2. `sustain_duration` requires ≥ 14400 s of that exact RC artifact; this lane's
   runtime budget is 5400 s wall clock, and even a minimum run could not pass
   gate (1).

Everything a lane can execute is green at `550f5d3ac`. Resolution requires a
release-owner decision: designate the RC and host the ≥ 4 h production-Compose
soak on an artifact at or after `653620201a`'s lineage, or explicitly rule on
the preflight evidence's sufficiency for the M3 promotion decision. No tree
change was made this round other than this handoff document; no test inventory
delta (no tests added or removed).
