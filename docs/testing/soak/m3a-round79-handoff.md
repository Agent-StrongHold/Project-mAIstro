# Issue #860 — round 79 (job 5ba0c1bb2f384f34a3bb0dc19ace1416) independent re-validation at 9c8de9d84

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head
`9c8de9d845b9c817dfeef5ab16279a0217a6f01a` (working tree clean on arrival,
exactly the dispatch head — HEAD is round f98359011f63's own commit; that
attempt completed with verdict NEEDS-DEEP-REVIEW and its docs-only round-78
handoff is the sole content delta from the previously validated
`2d1cc21ca`). No `check-*.log` files exist for this job (driver `checks`
empty per manifest), so the full battery was run directly at HEAD. Every
gate reproduced its rounds-72–78 result exactly.

## Develop drift this round (none new)

`git fetch origin` at round start: `origin/develop` is still `bb4257f0960f` —
the dispatch base itself, one merge ahead of the gates-resolved merge-base
`4aa68edc0b6b` (branch fork point). The 2-commit advance
(`d11368cd7`/`bb4257f09`, #2114/#2115 pg_store insert refactor + 2 run-store
tests + 2 inventory notes) remains the only drift; re-verified soak-neutral
this round. The manifest `surfaces` list (368 files) was programmatically
checked against the two-dot branch diff (`git diff --name-only HEAD
origin/develop`, 373 files): 0 surfaces fall outside the diff and the only
extras are exactly the 5 develop-side files, present solely because the
branch forked at `4aa68edc` before them. Not a sync conflict; validated at
the contractual head without merging.

## Deterministic battery executed (all green at HEAD)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| Soak/contract/release-guard/concurrency set (13 files, same composition as rounds 72–78): `tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_gitleaksignore_contract.py`, `tests/test_prod_stack_boot_contract.py`, `tests/test_check_deployment_claims.py`, `tests/test_check_gates_ran.py`, `tests/test_check_release_consistency.py`, `api/test_tasks_concurrency_backpressure.py`, `state/test_writer_concurrency.py`, `runs/test_run_concurrency_limits.py`, `graph/test_concurrency.py`, `persistence/test_sqlite_schema_concurrency.py`, `formal/models/test_strike_concurrency.py` | **308 passed, 16 skipped** |
| Drain + rate-limit set: `packages/maistro-server/tests/test_queue_singleton_drain.py`, `api/test_rate_limit.py`, `packages/maistro-core/tests/security/test_rate_limiter.py` | **38 passed** |
| Promotion-surface/governance/release set: `tests/test_check_promotion_surface.py`, `governance/test_promotion_contract.py`, `governance/test_conformance.py`, `maistro-evolve/test_promotion_governance.py`, `tests/release/test_installed_workspace_proof_schema.py`, `tests/release/test_installed_workspace_request_chain.py` | **283 passed** |
| `test_pg_learnings.py` (incl. the DDL-fence test) + `test_pg_sessions_concurrency.py` via `MAISTRO_TEST_PG_DSN=postgresql://maistro:soak@127.0.0.1:18433/maistro` against soak DB `maistro-soak-pg` (container up 11 h), live-checked at alembic head `062` | **46 passed, 0 skipped** |
| Full `packages/maistro-rsi/tests/` | **1,624 passed, 4 skipped** |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| `scripts/check-shipped-surface-truth.py` / `scripts/check-doc-links.py` | Matrix complete / every relative markdown link resolves |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml:1076-1082; gates resolve base `4aa68edc0b6b`, candidate `9c8de9d845b9` = HEAD) | 1,323/1,323 reviewed identities banked; `git diff --numstat bb4257f09..HEAD -- quality/` = 0 rows (ledgers identical to the dispatch base) |
| `scripts/check-radon-baseline.py` with CI's exact invocation (no positional args, quality.yml:852) | 137/137 C-or-worse blocks banked |

## Promotion replay (live gate code, this round, at HEAD)

`failed_promotion_checks()` applied to the round-43 pack
`docs/testing/soak/evidence/m3a-round43-shakedown.json` returns exactly
`['sustain_duration', 'exact_rc_artifact']` — re-executed this round:

- `sustain_duration`: observed `420.09 s` vs
  `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` (`run_soak.py:67`, compared at
  `:1601-1602`; pack row `{observed_seconds: 420.09, minimum_seconds: 14400,
  ok: False}`). `--sustain-seconds` (default 420, `run_soak.py:1678`) only
  sets run length, never the floor — no override exists. The 14,400 s
  continuous floor exceeds this job's `timeout_s = 5400` (read directly from
  this round's `manifest.json`) with background execution prohibited — **no
  in-lane run can flip this row**.
- `exact_rc_artifact`: `{'ok': False, 'reason': 'not the exact production
  Compose image and configuration', 'topology': 'host-uvicorn-preflight'}` —
  deliberate refusal in `preflight_artifact_check()` (`run_soak.py:730-743`);
  "There is deliberately no CLI override".
- All 8 correctness gates `ok=true` re-read from the pack's
  `thresholds.checks`: `exactly_once_task_admission`,
  `exactly_once_schedule_occurrence`, `rate_limit_enforced`,
  `lb_failover_bounded` (0 observed 5xx+conn errors in the 5.54 s window vs
  27.0 s upper bound), `replica_2_rejoined`,
  `nonterminal_runs_after_settle` (count 0), `task_admission_availability`
  (ratio 1.0, 2333/2333 submissions accepted outside the kill window),
  `graceful_drain` (required, ok, `drain_5xx=0`, `drain_conn_errors=0`,
  `drain_seconds=1.0`, SIGTERM, not escalated). `rss_growth`/`fd_growth`
  remain informational (rows without an `ok` field by design). Pack stats:
  `final_runs_by_status` completed=2359/cancelled=1, `nonterminal_runs`=0,
  `duplicate_evidence` 0 shared run/task identities, kill→rejoin window
  5.54 s, `replica_boot_seconds` 2.6.
- Pack provenance re-verified: added once by `215bdec8a`,
  `215bdec8a^ == 3da4e035eb1f46093d507db0f90b131a3a8d6dbe ==
  hashes.git_head` recorded inside the pack; `git merge-base --is-ancestor
  3da4e035 HEAD` true. Zero drift since the evidence head on the gate
  surface: `git diff 3da4e035eb..HEAD -- scripts/soak/` is empty (0 lines).

## External pair re-derived from this round's own 69-source capture (2026-10-10T14:53Z)

- Issue #860 open, 429 comments, updated 2026-10-10T14:37:36Z; body unchanged
  (10 acceptance checklist rows, **10 unchecked / 0 checked**). A sweep of
  all 429 fetched comments found **zero checked checkboxes and zero
  RC-designation tokens**; the three latest comments are lane progress
  markers only (job `b01f8aff` started 14:26:13Z; job `f98359011f63` started
  14:28:28Z, blocked 14:37:36Z).
- **Parent #89 open / 0 comments / updated 2026-09-22** — no release-owner RC
  designation exists (body re-read this round; the single "release candidate"
  hit is prose acceptance text, not a designation).
- Linked PRs re-read from this round's capture: **#1672 open draft, not
  merged** (`merged_at` null, draft true, head `16b244414b`); #1567 (head
  `d22378795cf3`, merged 2026-09-26T01:51:34Z), #1602 (`927a9c3c5bc6`,
  merged 2026-09-27T11:37:23Z), #2100 (`b950e5933a28`, merged
  2026-10-10T02:09:32Z) all closed **and merged**, no RC designation.

## Verdict carried forward

NEEDS-DEEP-REVIEW stays correct and external: rows `load profile / two
replicas / exactly-once / rate limiting / kill-restart / metrics-thresholds /
findings-filed / machine-readable evidence` are proven by the round-43 pack
(8/8 correctness gates) and re-proven by the green battery at HEAD; rows
`sustained load observation window` and `soak of the exact RC artifact` remain
**UNVERIFIED pending release-owner action** (RC designation under #89 plus a
release-owner-hosted ≥14,400 s production-Compose run — 2.7× this lane's
5,400 s budget). Gate weakening is prohibited; no in-lane action can advance
them further. Inventory delta 0 (no tests added or removed this round).
