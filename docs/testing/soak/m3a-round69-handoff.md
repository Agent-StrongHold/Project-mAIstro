# Issue #860 — round 69 (job d6660fee) independent re-validation at de12fa9bc

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head `de12fa9bc2a46c27d9239a7d60c032c84805615e`
(working tree clean on arrival, exactly the dispatch head — HEAD is the prior round
f8121790's own `end_head`, so nothing to salvage; the prior result artifact
`40c1119806694279a6784f70aaf53b09/result.json` is the same head dying on a provider
timeout with `checks: []`). No `check-*.log` files exist for this job (driver
`checks` empty again), so the full battery was run directly. No merge was needed:
`git fetch origin` shows `origin/develop == 4aa68edc == dispatch base`, already an
ancestor of HEAD via round 68's merge `070727f936`. The round-53 escalation
(NEEDS-DEEP-REVIEW) remains **external and unchanged**: acceptance rows 8 (and the
sustained-portion of row 3) require a release-owner RC designation under parent #89
plus a release-owner-hosted ≥14,400 s soak of the exact production Compose artifact,
neither of which any repair worker can supply.

## Deterministic battery executed (all green at HEAD)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| `pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-core/tests/persistence/test_pg_sessions_concurrency.py` against the round-68 `m3a860` database (still present in `maistro-postgres`, `alembic_version` at head `062`) via `MAISTRO_TEST_PG_DSN` | **46 passed**, 0 skipped |
| Soak/contract/release-guard/concurrency set (13 files: `tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_check_release_consistency.py`, `tests/test_check_promotion_surface.py`, `packages/maistro-core/tests/governance/test_promotion_contract.py`, `packages/maistro-core/tests/graph/test_concurrency.py`, `packages/maistro-core/tests/persistence/test_sqlite_schema_concurrency.py`, `packages/maistro-core/tests/runs/test_run_concurrency_limits.py`, `packages/maistro-core/tests/state/test_writer_concurrency.py`, `packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`, `packages/maistro-evolve/tests/test_promotion_governance.py`, `tests/release/test_installed_workspace_proof_schema.py`, `tests/release/test_installed_workspace_request_chain.py`) | **492 passed, 16 skipped** in 11.56 s |
| `tests/test_gitleaksignore_contract.py` + **full** `packages/maistro-rsi/tests/` (broader than round 68's 5-file promotion subset) | **1,632 passed, 4 skipped** in 80.15 s |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (candidate `de12fa9bc2a4`) | 1,323/1,323 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `scripts/check-shipped-surface-truth.py` | Matrix complete |
| `scripts/check-doc-links.py` | Every relative markdown link resolves |

mypy not run: this round touched zero Python files (the only tree change is this
handoff note), so the type state is unchanged from round 68's post-merge battery.

## Promotion replay (live gate code, this round, at HEAD)

`failed_promotion_checks()` (`scripts/soak/run_soak.py:744`) applied to the
round-43 pack `docs/testing/soak/evidence/m3a-round43-shakedown.json` returns
exactly `['sustain_duration', 'exact_rc_artifact']`:

- `sustain_duration`: observed `420.09 s` vs `PROMOTION_MIN_SUSTAIN_SECONDS =
  14_400` (`run_soak.py:67`, compared at `:1601-1602`). No env/CLI override
  exists. The 14,400 s continuous floor exceeds this lane's 5,400 s job budget
  with background execution prohibited — **no in-lane run can flip this row**.
- `exact_rc_artifact`: `{'ok': False, 'reason': 'not the exact production Compose
  image and configuration', 'topology': 'host-uvicorn-preflight'}` — deliberate
  refusal of the host-uvicorn-preflight topology in
  `preflight_artifact_check()` (`run_soak.py:729-743`); "There is deliberately no
  CLI override".
- All 8 correctness gates `ok=true` in the pack:
  `exactly_once_task_admission`, `exactly_once_schedule_occurrence`,
  `rate_limit_enforced`, `lb_failover_bounded`, `replica_2_rejoined`,
  `nonterminal_runs_after_settle`, `task_admission_availability`,
  `graceful_drain` (SIGTERM required, drained, `drain_5xx=0`,
  `drain_conn_errors=0`). `rss_growth`/`fd_growth` are informational (`ok=None`)
  per the required tuple.
- Pack provenance re-verified: added once by `215bdec8a` whose parent ==
  recorded `hashes.git_head 3da4e035eb1f46093d507db0f90b131a3a8d6dbe`, never
  modified since, ancestor of HEAD. `m3a-load-profile.md` present (row 1 of the
  issue's acceptance list, 10 checklist rows, body unchanged this capture).
- Zero drift since the evidence head: `git diff 3da4e035eb HEAD -- scripts/soak/
  deploy/nginx.conf tests/test_soak_promotion_gates.py
  tests/test_gitleaksignore_contract.py` is empty.

## External pair re-derived from this round's own 69-source capture (2026-10-10T10:30Z)

- Issue #860 open, 403 comments, updated 2026-10-10T10:15:12Z; body unchanged
  (10 acceptance checklist rows).
- **Parent #89 open / 0 comments / updated 2026-09-22** — unlike round 68's
  capture (parent body endpoint returned `data: null`), this round's capture
  contains the parent issue record directly and its comments endpoint returns
  `[]`; both agree with rounds 57–68. No release-owner RC designation exists.
- Linked PR heads unchanged: **#1672 open draft** at `16b244414b01`;
  #1567 (`d2237879`), #1602 (`927a9c3c`), #2100 (`b950e593`) closed **and
  merged**, no RC designation (#2100 is the develop-side soak-fingerprint fix).
- Designation-regex sweep over all comment/timeline records: **1 hit**, and it
  is the issue body's own prose ("Promote a release candidate through the exact
  shipping pipeline…") — no designation.

## Verdict carried forward

NEEDS-DEEP-REVIEW stays correct and external: rows `load profile / two replicas /
exactly-once / rate limiting / kill-restart / metrics-thresholds` are proven by
the round-43 pack (8/8 correctness gates) and re-proven by the green battery at
HEAD; rows `sustained soak of the exact RC artifact` remain **UNVERIFIED pending
release-owner action** (RC designation under #89 + release-owner-hosted
≥14,400 s production-Compose run). Gate weakening is prohibited; no in-lane
action can advance them further.

Inventory delta: 0 (no collected tests added or removed;
`check-suite-inventory.py` 17/17 green confirms). The only tree change this
round is this handoff note.
