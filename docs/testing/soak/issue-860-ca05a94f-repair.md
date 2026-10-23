# Issue #860 — bounded repair ca05a94f

## Frozen scope

- Issue #860 only; assigned worktree `/home/dev/Git/wt/auto-860`, branch
  `auto-860`, starting HEAD `1a4563c9877b55ea827c9aa558b0e0d739f46c59`,
  base `d592654aca614fb74467487542693c46b3aa30fb`; clean on arrival.
- This round's job directory supplied **no `check-*.log` files** (driver
  `checks: []`); the prior-failure reference
  (`98a11313…/check-3.log`, `test_ensure_schema_fences_ddl_behind_advisory_lock`
  expecting 21 DDL calls and observing 24) was captured against the older head
  `872fd2ce` and was re-executed here rather than trusted.
- Candidate edits limited to this report. No test addition (no inventory
  delta), no ledger amendment unless the exact vulture gate produced unbanked
  findings, no remote mutations.

## Deterministic gates re-executed at this head (all green)

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra dev` | Resolved/checked, no drift |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| `uv run mypy` (10 CI src dirs per `ci.yml:118–130`) | Success: no issues in 1,027 source files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0; 1,326 findings = 1,326 reviewed identities, unclassified 0, never_allowlist 0 → **no ledger amendment justified** |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | **37 passed, 6 skipped** — prior check-3 failure is dead at this head; current `expected_ddl` (lines 162–189) already lists all 24 statements including the three validation-audit columns |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -q` | **100 passed** |
| `uv run python scripts/check-suite-inventory.py` | ok: 17 suite(s) match |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |
| `uv run python scripts/check-merge-markers.py` | ok: no conflict markers |
| `bash scripts/verify-monorepo-layout.sh` | ok |

## Acceptance re-derived from raw evidence at this head

- Live import of `failed_promotion_checks()` from
  `scripts/soak/run_soak.py` against the newest full evidence pack
  (`evidence/m3a-round30-shakedown.json`) → `['sustain_duration',
  'exact_rc_artifact']`; records: `minimum_seconds=14400,
  observed_seconds=420.08, ok=false` and `topology="host-uvicorn-preflight",
  ok=false`. Both failures are structural by design
  (`preflight_artifact_check` deliberately has no CLI override,
  `run_soak.py:730–741`).
- Fresh AC8 sweep of this round's capture (316 comments, captured
  2026-10-09T05:22Z — newer than round 38's 178-comment capture): regex
  `release[- ]candidate|\bRC\b|designat|exact[- ]RC|four[- ]hour|4[- ]?hour|14400`
  → **0 matching comments**. No release owner has designated an RC. The
  newest comments are `maistro-progress` bot markers, not rulings.

## Terminal condition (identical to rounds 33–38)

The two remaining failed promotion gates cannot be satisfied by any in-lane
action:

1. `exact_rc_artifact` requires the exact production Compose image/config of a
   release candidate no release owner has designated (0/316 comments at this
   round's fresh capture).
2. `sustain_duration` requires ≥ 14,400 s on that exact RC artifact; any run
   without gate (1)'s designation fails it by construction.

Everything a lane can execute is green at `1a4563c98`. Resolution requires a
release-owner decision: designate the RC and host the ≥ 4 h
production-Compose soak on its exact artifact/configuration, or explicitly
rule on the preflight evidence's sufficiency for the M3 promotion decision.

No tree change was made this round other than this report; no test inventory
delta (no tests added or removed); no `quality/*.json` edit (exact vulture
scan is clean); no GitHub mutation, merge, reset or destructive cleanup.
