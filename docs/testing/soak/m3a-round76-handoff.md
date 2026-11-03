# Issue #860 — round 76 (job 0081c5d3c8b04358af8c1104bc14cf77) independent re-validation at d03a593e6

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head
`d03a593e67cd5e01ad4015ebc2edd1aa397a93b2` (working tree clean on arrival,
exactly the dispatch head — HEAD is round d9fef2e5's own commit; its prior
attempt died on a provider timeout with `checks: []`, nothing to salvage). No
`check-*.log` files exist for this job (driver `checks` empty per manifest), so
the full battery was run directly at HEAD.

## Develop drift this round (checked, no merge)

`git fetch origin` shows `origin/develop` advanced from the prior base
`4aa68edc0b6b` to `bb4257f0960f` — exactly 2 new commits, `d11368cd7`
("#2115 Prepare validated PG root Runs before transaction acquisition") and
`bb4257f09` ("#2114 Reuse PG Run insertion inside caller transaction"),
touching only `packages/maistro-core/src/maistro/runs/pg_store.py`, two new
run-store test files, and two inventory notes. This is **not a develop sync
conflict**: the prior block was the NEEDS-DEEP-REVIEW verdict on external
rows, not a sync failure. This round's manifest already accounts for the
drift — its `base` is the new tip `bb4257f09` and its 365-file surface list
equals the two-dot diff minus exactly those 5 develop-side files — so the
lane validated at the contractual head without merging. `git diff --numstat
bb4257f09..HEAD -- quality/` is empty (0 rows): the per-identity ledgers are
identical to the new base, so the vulture/radon gates' own base resolution
(`4aa68edc`) is unaffected. The new develop commits do not touch
`scripts/soak/`, the promotion gates, or any lane surface.

## Deterministic battery executed (all green at HEAD)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| Soak/contract/release-guard/concurrency set (13 files, same composition as round 75): `tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_gitleaksignore_contract.py`, `tests/test_prod_stack_boot_contract.py`, `tests/test_check_deployment_claims.py`, `tests/test_check_gates_ran.py`, `tests/test_check_release_consistency.py`, `api/test_tasks_concurrency_backpressure.py`, `state/test_writer_concurrency.py`, `runs/test_run_concurrency_limits.py`, `graph/test_concurrency.py`, `persistence/test_sqlite_schema_concurrency.py`, `formal/models/test_strike_concurrency.py` | **308 passed, 16 skipped** (identical to rounds 72–75) |
| Drain + rate-limit set: `test_queue_singleton_drain.py`, `api/test_rate_limit.py`, `packages/maistro-core/tests/security/test_rate_limiter.py` | **38 passed** |
| Promotion-surface/governance/release set: `tests/test_check_promotion_surface.py`, `governance/test_promotion_contract.py`, `governance/test_conformance.py`, `maistro-evolve/test_promotion_governance.py`, `tests/release/test_installed_workspace_proof_schema.py`, `tests/release/test_installed_workspace_request_chain.py` | **283 passed** |
| `test_pg_learnings.py` (incl. the DDL-fence test) + `test_pg_sessions_concurrency.py` via `MAISTRO_TEST_PG_DSN=postgresql://maistro:soak@127.0.0.1:18433/maistro` against soak DB `maistro-soak-pg` (container up 9 h), live-checked at alembic head `062` | **46 passed, 0 skipped** |
| Full `packages/maistro-rsi/tests/` | **1,624 passed, 4 skipped** (byte-for-byte rounds 72–75) |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| `scripts/check-shipped-surface-truth.py` / `scripts/check-doc-links.py` | Matrix complete / every relative markdown link resolves |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml:1076-1082; gates resolve base `4aa68edc0b6b`, candidate `d03a593e67cd` = HEAD) | 1,323/1,323 reviewed identities banked; `quality/` numstat vs the new dispatch base `bb4257f09` empty |
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
  deliberate refusal in `preflight_artifact_check()` (`run_soak.py:729-743`);
  "There is deliberately no CLI override".
- All 8 correctness gates `ok=true` re-read from the pack's
  `thresholds.checks` (12 rows): `exactly_once_task_admission`,
  `exactly_once_schedule_occurrence`, `rate_limit_enforced`,
  `lb_failover_bounded`, `replica_2_rejoined`,
  `nonterminal_runs_after_settle`, `task_admission_availability`,
  `graceful_drain` (required, ok, `drain_5xx=0`, `drain_conn_errors=0`,
  `drain_seconds=1.0`). `rss_growth`/`fd_growth` remain informational
  (`ok=None`). Pack provenance re-verified: added once by `215bdec8a`,
  `215bdec8a^ == 3da4e035eb1f46093d507db0f90b131a3a8d6dbe ==
  hashes.git_head` recorded inside the pack; `git merge-base --is-ancestor
  3da4e035 HEAD` true (plain `git log --follow` extends only to rounds 26/27
  via rename ancestry, not content history).
- Zero drift since the evidence head on the gate surface:
  `git diff 3da4e035eb..HEAD -- scripts/soak/` is empty (0 lines).

## External pair re-derived from this round's own 69-source capture (2026-10-10T13:36:57Z)

- Issue #860 open, 422 comments, updated 2026-10-10T13:21:00Z; body unchanged
  (10 acceptance checklist rows, **10 unchecked / 0 checked**).
- **Parent #89 open / 0 comments / updated 2026-09-22** — no release-owner RC
  designation exists (re-read this round; title "M3-A7 — Run RC soak and
  byte-equivalent final promotion", body lists acceptance requirements only).
- Linked PRs re-read from this round's capture: **#1672 open draft, not
  merged** (`merged_at` null, head `16b244414b`); #1567 (head `d22378795cf3`,
  merged 2026-09-26T01:51:34Z), #1602 (`927a9c3c5bc6`, merged
  2026-09-27T11:37:23Z), #2100 (`b950e5933a28`, merged 2026-10-10T02:09:32Z)
  all closed **and merged**, no RC designation.
- Designation-regex sweep (`RC[-_ ]?\d|release[-_ ]candidate`,
  case-insensitive) across the #860/#86/#89 bodies: **3 hits, all prose false
  positives** (the acceptance text of #860, the smoke-job cross-link in #86,
  the "Promote a release candidate" prose in #89). Zero actual RC
  designations.

## Verdict carried forward

NEEDS-DEEP-REVIEW stays correct and external: rows `load profile / two
replicas / exactly-once / rate limiting / kill-restart / metrics-thresholds /
findings-filed / machine-readable evidence` are proven by the round-43 pack
(8/8 correctness gates) and re-proven by the green battery at HEAD; rows
`sustained load observation window` and `soak of the exact RC artifact` remain
**UNVERIFIED pending release-owner action** (RC designation under #89 plus a
release-owner-hosted ≥14,400 s production-Compose run — 2.7× this lane's
5,400 s budget). Gate weakening is prohibited; no in-lane action can advance
them further. The 2-commit develop advance is soak-neutral (pg_store insert
refactor; no lane-surface or gate-surface intersection) and is recorded above.
Inventory delta 0 (no tests added or removed this round).
