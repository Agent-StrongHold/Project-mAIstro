# Issue #860 — round 70 (job 73cf210d) independent re-validation at e161a341

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head `e161a34193e4b9c32e9ae09e0258a391ea27369b`
(working tree clean on arrival, exactly the dispatch head — HEAD is the prior round
d6660fee's own `end_head`, so nothing to salvage). No `check-*.log` files exist for
this job (driver `checks` empty again), so the full battery was run directly.
`origin/develop` base `4aa68edc` is already an ancestor of HEAD via round 68's merge
`070727f936`; no merge was needed. The round-53 escalation (NEEDS-DEEP-REVIEW)
remains **external and unchanged**: acceptance row 8 (and the sustained-portion of
row 3) require a release-owner RC designation under parent #89 plus a
release-owner-hosted ≥14,400 s soak of the exact production Compose artifact,
neither of which any repair worker can supply.

## Deterministic battery executed (all green at HEAD)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| Soak/contract/release-guard set: `tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_check_promotion_surface.py`, `packages/maistro-core/tests/governance/test_promotion_contract.py` | **164 passed** |
| Concurrency set: `test_writer_concurrency.py`, `graph/test_concurrency.py`, `test_run_concurrency_limits.py`, `test_tasks_concurrency_backpressure.py`, `test_sqlite_schema_concurrency.py` | **74 passed, 16 skipped** |
| Broadened-set remainder: `tests/test_check_release_consistency.py`, `packages/maistro-evolve/tests/test_promotion_governance.py`, `tests/release/test_installed_workspace_proof_schema.py`, `tests/release/test_installed_workspace_request_chain.py` | **254 passed** |
| `test_pg_sessions_concurrency.py` + full `memory/learnings` (incl. evidence promotion) via `MAISTRO_TEST_PG_DSN` against the soak DB `maistro-soak-pg:18433/maistro` — migrated `061 -> 062` on arrival (container DB was one migration stale; alembic upgrade `062_audit_cursor_indexes` applied, then 320 passed) | **320 passed, 0 skipped** |
| `tests/test_gitleaksignore_contract.py` | **8 passed** |
| Full `packages/maistro-rsi/tests/` | **1,624 passed, 4 skipped** (1,624 + 8 gitleaksignore = 1,632, matching round 69) |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (base `4aa68edc0b6b` == dispatch base, candidate `e161a34193e4`) | 1,323/1,323 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `scripts/check-shipped-surface-truth.py` | Matrix complete |
| `scripts/check-doc-links.py` | Every relative markdown link resolves |

mypy not run: this round touched zero Python files (the only tree change is this
handoff note), so the type state is unchanged from round 69's battery.

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
  issue's acceptance list, body unchanged this capture).
- Zero drift since the evidence head: `git log 3da4e035eb..HEAD --` on
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `tests/test_release_guard.py`, `tests/test_check_promotion_surface.py`,
  `tests/test_gitleaksignore_contract.py`, `docs/testing/soak/m3a-load-profile.md`
  is empty; the pack itself is touched only by its own addition `215bdec8a`;
  `git diff 3da4e035 HEAD -- scripts/soak/ scripts/deploy/
  packages/maistro-core/tests/governance/` is empty.

## External pair re-derived from this round's own 69-source capture (2026-10-10T10:55Z)

- Issue #860 open, 406 comments, updated 2026-10-10T10:40:25Z; body unchanged
  (10 acceptance checklist rows).
- **Parent #89 open / 0 comments / updated 2026-09-22** — no release-owner RC
  designation exists.
- Linked PR heads unchanged: **#1672 open draft** at `16b244414b01`;
  #1567 (`d2237879`), #1602 (`927a9c3c`), #2100 (`b950e593`) closed **and
  merged**, no RC designation.

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
