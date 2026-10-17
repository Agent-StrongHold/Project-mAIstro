# Issue #860 round-38 independent revalidation (job a851953ff5bf)

- Branch tip at start and end: `eaa26d98f9a4444dab7197ca2e6f5d210a18de3b`
  (round-37 docs tip; tree clean, `develop` base `b0912ce590d5` — no develop
  sync action required: the lineage already merged develop tip `1df433bf5` via
  `653620201a`, and this round's dispatch reported no sync conflict).
- The driver for this job executed **no deterministic checks** in the job
  directory (no `check-*.log` files). The stale failure carried in the dispatch
  (`/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`,
  `test_ensure_schema_fences_ddl_behind_advisory_lock` expecting 21 DDL calls
  and observing 24) was re-checked at this head and is **dead**: the test file
  passes. Every gate below was re-executed by the worker at this head, not
  trusted from round 37.

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
| `python scripts/check-merge-markers.py` | ok: no conflict markers |
| `uv run mypy <10 CI src dirs per ci.yml:109>` | Success: no issues found in 1007 source files |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/scheduling/test_pg_admission.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_prod_stack_boot_contract.py -q` | 102 passed, 8 skipped (includes the round-33 stale-failure file: 37 passed, 6 skipped) |

## Evidence re-derived from raw artifacts at this head

- `failed_promotion_checks()` imported live from `scripts/soak/run_soak.py` on
  the round-30 pack -> `['sustain_duration', 'exact_rc_artifact']`;
  `sustain_duration` record: `minimum_seconds=14400, observed_seconds=420.08,
  ok=false`; `exact_rc_artifact` record: `topology="host-uvicorn-preflight",
  ok=false`. Both failures are structural by design (`preflight_artifact_check`
  has deliberately no CLI override), unchanged from round 37.
- AC8 external blocker re-confirmed on this round's **fresh capture**
  (178 comments, captured 2026-10-07T02:55Z — two newer than round-37 saw):
  regex sweep for `release[- ]candidate|RC|designat|exact[- ]RC|four[- ]hour|
  4[- ]?hour|14400|soak` -> **0 matching comments**. The two newest comments
  are `maistro-progress` bot markers for jobs `2d1027f9` and `68640d0d`, not
  release-owner rulings. No RC designation exists.
- Production drift since the pack's `git_head=c4f45b309` re-measured:
  26 paths under `packages/ scripts/ tests/` changed (extensions/ ADR-104
  #950, `graph/durable_runs/execution_store.py` #1334, `maistro_registry/*`
  #2023, plus their tests and two scripts). Round 37 counted 27 under a
  slightly wider filter — same conclusion: under the artifact-identity
  contract in `m3a-load-profile.md`, the promotion-signing soak must postdate
  the `653620201a` merge. Unchanged.

## Terminal condition (identical to rounds 33–37, now with fresh evidence)

The two remaining failed promotion gates cannot be satisfied by any in-lane
action:

1. `exact_rc_artifact` requires the exact production Compose image/config of a
   release-candidate that **no release owner has designated** (0/178 comments
   at this round's capture).
2. `sustain_duration` requires ≥ 14400 s on that exact RC artifact; this lane's
   runtime budget is 5400 s wall clock, and any run would fail gate (1) first.

Everything a lane can execute is green at `eaa26d98f`. Resolution requires a
release-owner decision: designate the RC and host the ≥ 4 h production-Compose
soak on an artifact at or after `653620201a`'s lineage, or explicitly rule on
the preflight evidence's sufficiency for the M3 promotion decision. No tree
change was made this round other than this handoff document; no test inventory
delta (no tests added or removed).
