# Issue #860 — round 74 (job d1f24d27) independent re-validation at b257f95d1

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head
`b257f95d14548409341bacf18ca6e5d0377eb6ca` (working tree clean on arrival,
exactly the dispatch head — HEAD is round 6ee92b28's own commit, whose
immediately prior attempt died on a provider timeout at this same head with
`checks: []`, so nothing to salvage). No `check-*.log` files exist for this
job (driver `checks` empty per manifest), so the full battery was run directly
at HEAD. `origin/develop` was re-fetched this round and is still exactly the
dispatch base `4aa68edc0b6b85ae23f97e611d693927218863dc`, already an ancestor
of HEAD — no sync conflict and no merge needed.

## Deterministic battery executed (all green at HEAD)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| Soak/contract/release-guard/concurrency set (13 files, same composition as round 73): `tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_gitleaksignore_contract.py`, `tests/test_prod_stack_boot_contract.py`, `tests/test_check_deployment_claims.py`, `tests/test_check_gates_ran.py`, `tests/test_check_release_consistency.py`, `api/test_tasks_concurrency_backpressure.py`, `state/test_writer_concurrency.py`, `runs/test_run_concurrency_limits.py`, `graph/test_concurrency.py`, `persistence/test_sqlite_schema_concurrency.py`, `formal/models/test_strike_concurrency.py` | **308 passed, 16 skipped** (skips are PG-parameterized rows) |
| Drain + rate-limit server/core tests: `test_queue_singleton_drain.py`, `api/test_rate_limit.py`, `packages/maistro-core/tests/security/test_rate_limiter.py` | **38 passed** |
| Promotion-surface/governance/release set: `tests/test_check_promotion_surface.py`, `governance/test_promotion_contract.py`, `governance/test_conformance.py`, `maistro-evolve/test_promotion_governance.py`, `tests/release/test_installed_workspace_proof_schema.py`, `tests/release/test_installed_workspace_request_chain.py` | **283 passed** |
| `test_pg_learnings.py` (incl. `test_ensure_schema_fences_ddl_behind_advisory_lock`) + `test_pg_sessions_concurrency.py` via `MAISTRO_TEST_PG_DSN=postgresql://maistro:soak@127.0.0.1:18433/maistro` against the soak DB `maistro-soak-pg` (container up 9 h), already at alembic head `062` | **46 passed, 0 skipped** |
| Full `packages/maistro-rsi/tests/` | **1,624 passed, 4 skipped** (byte-for-byte the rounds 72/73 count) |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory (script carries the develop-side #1712 `--suite` directory-expansion/sha256 hardening, pre-existing since before round 73's evidence head; gate green with it) |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| `scripts/check-shipped-surface-truth.py` / `scripts/check-doc-links.py` | Matrix complete / 0 broken relative links |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml:1077-1081; base `4aa68edc0b6b` == dispatch base, candidate `b257f95d1454`) | 1,323/1,323 reviewed identities banked; `quality/` numstat vs base empty |
| `scripts/check-radon-baseline.py` **with CI's exact invocation (no positional args, quality.yml:852)** | 137/137 C-or-worse blocks banked |

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
  `thresholds.checks` (12 rows total): `exactly_once_task_admission`,
  `exactly_once_schedule_occurrence`, `rate_limit_enforced`,
  `lb_failover_bounded`, `replica_2_rejoined`,
  `nonterminal_runs_after_settle`, `task_admission_availability`,
  `graceful_drain` (required, ok, `drain_5xx=0`, `drain_conn_errors=0`,
  `drain_seconds=1.0`). `rss_growth`/`fd_growth` remain informational
  (`ok=None`). Supporting fields: `duplicate_evidence`
  `runs_sharing_one_task_run_identity=0`, `final_runs_by_status`
  completed=2359/cancelled=1, `nonterminal_runs=0`, kill window 5.54 s with
  `rejoined=true`, replica boot 2.6 s.
- Pack provenance re-verified: plain `git log` on the pack path shows exactly
  one commit, `215bdec8a` (added once, never modified — `--follow` extends
  into rounds 26/27 only via rename ancestry, not content history);
  `215bdec8a^ == 3da4e035eb1f46093d507db0f90b131a3a8d6dbe ==
  hashes.git_head` recorded inside the pack;
  `git merge-base --is-ancestor 3da4e035 HEAD` true.
  `docs/testing/soak/m3a-load-profile.md` present (row 1 of the issue's
  acceptance list, last touched round 30).
- Zero drift since the evidence head on the gate surface:
  `git diff 3da4e035eb..HEAD -- scripts/soak/` is empty (0 lines).

## External pair re-derived from this round's own 69-source capture (2026-10-10T12:45Z)

- Issue #860 open, 417 comments, updated 2026-10-10T12:30:28Z; body unchanged
  (10 acceptance checklist rows, all unchecked).
- **Parent #89 open / 0 comments / updated 2026-09-22** — no release-owner RC
  designation exists (re-read this round; title "M3-A7 — Run RC soak and
  byte-equivalent final promotion", body lists acceptance requirements only).
- Linked PR heads unchanged: **#1672 open, not merged** (`merged_at` null);
  #1567 (`d2237879`, merged_at 2026-09-26), #1602 (`927a9c3c`, merged_at
  2026-09-27), #2100 (`b950e593`, merged_at 2026-10-10) all closed **and
  merged**, no RC designation.
- Designation-regex sweep (`RC[-_ ]?\d|release[-_ ]candidate`,
  case-insensitive) across #860/#86/#89 bodies: **3 hits, all prose false
  positives** — the acceptance text of #860, the smoke-job cross-link in #86,
  and the "Promote a release candidate" prose in #89. Zero actual RC
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
them further.
