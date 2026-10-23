# Issue #860 — round 71 (job f1cf63c7) independent re-validation at c3d9bb86

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head `c3d9bb86bcb89aa60e98f93472e00d72a3d1573d`
(working tree clean on arrival, exactly the dispatch head — HEAD is round
73cf210d's own commit, and the immediately prior attempt `80f98f17` died on a
provider timeout at this same head with `checks: []`, so nothing to salvage).
No `check-*.log` files exist for this job (driver `checks` empty), so the full
battery was run directly. `origin/develop` was re-fetched this round and is
still exactly the dispatch base `4aa68edc0b6b85ae23f97e611d693927218863dc`,
already an ancestor of HEAD — no sync conflict and no merge needed.

## Deterministic battery executed (all green at HEAD)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| Soak/contract/release-guard/concurrency set (13 files): `tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_gitleaksignore_contract.py`, `tests/test_prod_stack_boot_contract.py`, `tests/test_check_deployment_claims.py`, `tests/test_check_gates_ran.py`, `tests/test_check_release_consistency.py`, `test_tasks_concurrency_backpressure.py`, `test_writer_concurrency.py`, `test_run_concurrency_limits.py`, `graph/test_concurrency.py`, `test_sqlite_schema_concurrency.py`, `formal/models/test_strike_concurrency.py` | **308 passed, 16 skipped** (skips are PG-parameterized rows) |
| Drain + rate-limit server tests: `test_queue_singleton_drain.py`, `api/test_rate_limit.py` | **28 passed** |
| Promotion-surface/governance/release set: `tests/test_check_promotion_surface.py`, `governance/test_promotion_contract.py`, `maistro-evolve/test_promotion_governance.py`, `tests/release/test_installed_workspace_proof_schema.py`, `tests/release/test_installed_workspace_request_chain.py` | **271 passed** |
| `test_pg_learnings.py` (incl. `test_ensure_schema_fences_ddl_behind_advisory_lock`) + `test_pg_sessions_concurrency.py` via `MAISTRO_TEST_PG_DSN` against the soak DB `maistro-soak-pg:18433/maistro`, already at alembic head `062` on arrival | **46 passed, 0 skipped** — the stale 2026-10-06 `check-3.log` DDL-fence failure is confirmed resolved (it was shared-dev-DB drift, not code; green on the correctly migrated DB) |
| Full `packages/maistro-rsi/tests/` | **1,624 passed, 4 skipped** |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (base `4aa68edc0b6b` == dispatch base, candidate `c3d9bb86bcb8`) | 1,323/1,323 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `scripts/check-shipped-surface-truth.py` / `scripts/check-doc-links.py` | Matrix complete / every relative markdown link resolves |

## Promotion replay (live gate code, this round, at HEAD)

`failed_promotion_checks()` (`scripts/soak/run_soak.py:744`) applied to the
round-43 pack `docs/testing/soak/evidence/m3a-round43-shakedown.json` returns
exactly `['sustain_duration', 'exact_rc_artifact']`:

- `sustain_duration`: observed `420.09 s` vs `PROMOTION_MIN_SUSTAIN_SECONDS =
  14_400` (`run_soak.py:67`, compared at `:1601-1602`). `--sustain-seconds`
  only sets the run length, never the floor — no override exists. The 14,400 s
  continuous floor exceeds this lane's 5,400 s job budget with background
  execution prohibited — **no in-lane run can flip this row**.
- `exact_rc_artifact`: `{'ok': False, 'reason': 'not the exact production
  Compose image and configuration', 'topology': 'host-uvicorn-preflight'}` —
  deliberate refusal in `preflight_artifact_check()` (`run_soak.py:729-743`);
  "There is deliberately no CLI override".
- All 8 correctness gates `ok=true` in the pack:
  `exactly_once_task_admission`, `exactly_once_schedule_occurrence`,
  `rate_limit_enforced`, `lb_failover_bounded`, `replica_2_rejoined`,
  `nonterminal_runs_after_settle`, `task_admission_availability`,
  `graceful_drain` (SIGTERM required, drained, `drain_5xx=0`,
  `drain_conn_errors=0`). `rss_growth`/`fd_growth` are informational
  (`ok=None`).
- Pack provenance re-verified: added once by `215bdec8a` whose parent ==
  recorded `hashes.git_head 3da4e035eb1f46093d507db0f90b131a3a8d6dbe`, never
  modified since (file history is that single commit), ancestor of HEAD.
  `docs/testing/soak/m3a-load-profile.md` present (row 1 of the issue's
  acceptance list, unchanged this capture).
- Zero drift since the evidence head: `git log 3da4e035eb..HEAD --` on
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `tests/test_release_guard.py`, `tests/test_check_promotion_surface.py`,
  `tests/test_gitleaksignore_contract.py`, `docs/testing/soak/m3a-load-profile.md`
  is empty; `git diff 3da4e035 HEAD -- scripts/soak/ scripts/deploy/
  packages/maistro-core/tests/governance/` is empty.

## External pair re-derived from this round's own 69-source capture (2026-10-10T11:19Z)

- Issue #860 open, 408 comments, updated 2026-10-10T11:04:04Z; body unchanged
  (10 acceptance checklist rows).
- **Parent #89 open / 0 comments / updated 2026-09-22** — no release-owner RC
  designation exists in the body.
- Linked PR heads unchanged: **#1672 open draft** at `16b244414b01`;
  #1567 (`d2237879`), #1602 (`927a9c3c`), #2100 (`b950e593`) closed **and
  merged**, no RC designation.
- A designation-regex sweep across all 69 captured sources finds **0 hits**.

## Verdict carried forward

NEEDS-DEEP-REVIEW stays correct and external: rows `load profile / two
replicas / exactly-once / rate limiting / kill-restart / metrics-thresholds`
are proven by the round-43 pack (8/8 correctness gates) and re-proven by the
green battery at HEAD; rows `sustained soak of the exact RC artifact` remain
**UNVERIFIED pending release-owner action** (RC designation under #89 plus a
release-owner-hosted ≥14,400 s production-Compose run). Gate weakening is
prohibited; no in-lane action can advance them further.

Inventory delta: 0 (no collected tests added or removed;
`check-suite-inventory.py` 17/17 green confirms). The only tree change this
round is this handoff note.
