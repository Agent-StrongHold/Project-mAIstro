---
inventory-delta:
  packages/maistro-core/tests: +15
  packages/maistro-server/tests: +2
---

# Issue #1182: opt-in system-wide active root-Run ceiling

Closes the one acceptance residual the previous verification round recorded
for #1182 ("an explicit system/global ceiling where needed"): the admission
authority (`RunStore.create_run` on all three backends) now also enforces an
opt-in system-wide ceiling on concurrently active root Runs, configured via
`MAX_ACTIVE_ROOT_RUNS_SYSTEM`. Unset stays the owner-decided baseline of 8
per principal / 32 per Workspace with no global bound; a configured value can
only tighten. On PostgreSQL a system-wide advisory lock serializes the count
across replicas, in the existing workspace→principal lock order (system last,
so the order stays acyclic). `/health/ready`'s admin payload reports the
effective ceilings, `system: null` included.

## maistro-core/tests/runs/test_run_concurrency_limits.py (+15)

- `test_the_system_ceiling_is_opt_in_and_validated` — default None, positive
  values accepted, zero refused (1).
- `test_configured_reads_the_system_ceiling_setting` — the settings knob is
  the one `RunConcurrencyLimits.configured()` enforces (1).
- `test_a_non_positive_system_ceiling_is_refused_at_settings` — `0` and `-3`
  are refused at Settings, so a typo cannot silently close every submit
  surface (2).
- `test_the_spine_wiring_enforces_the_configured_system_ceiling` — the
  shipped `wire_execution_spine` path on memory and SQLite (2).
- `test_the_system_ceiling_spans_workspaces_and_principals`,
  `test_terminalizing_a_run_frees_its_system_slot`,
  `test_concurrent_admission_holds_the_system_ceiling` — the new
  `system_spine` fixture runs each on memory, SQLite and PostgreSQL; the
  concurrent case is the serialized advisory-lock path on real PostgreSQL (9).

## maistro-server/tests/api/test_resource_policy_health.py (+2)

- `test_readiness_exposes_run_concurrency_limits_to_admin_callers` — admin
  payload shows per-principal/per-Workspace/system (null and 64), anonymous
  probes keep the status-only contract.
- `test_readiness_degraded_still_reports_run_concurrency_limits_to_admins` —
  the 503 detailed payload carries the same ceilings when a dependency is
  down.

## Independent re-verification (2026-10-24, live evidence, tree unmodified)

Executed on this worktree at `cc605a6c` against the live `pgvector:pg18`
container (`MAISTRO_TEST_PG_DSN` set, so no `[postgres]` leg skipped):

- `uv run pytest packages/maistro-core/tests/runs/test_run_concurrency_limits.py -q`
  → **79 passed** (principal/Workspace/system ceilings, fairness, parked-resume,
  duplicate-vs-backpressure, stranded-turn reclaim; concurrent-admission cases
  exercised the real advisory-lock path on PostgreSQL 18).
- `uv run pytest packages/maistro-core/tests/runs -q` → **1670 passed,
  3 skipped**; `uv run pytest packages/maistro-server/tests/api -q` → **552
  passed** (includes the 429-without-retained-claim and admin-diagnostics
  regressions); `test_resource_policy_declared_floors.py` → 8 passed
  (tighten-freely / loosen-only-with-override for both ceilings).
- **Fail-before proof:** a `-p` plugin neutering only
  `RunConcurrencyLimits.check` (no other change) makes all 15 ceiling tests
  fail across memory, SQLite and PostgreSQL — the check is the single
  refusing site; without the plugin all pass.
- **Gates with CI's exact arguments:** `ruff check .` / `ruff format --check .`
  clean; `check-suite-inventory.py` (21 suites match); `check-security-inventory.py`;
  `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (1321 reviewed = 1321 findings); `check-radon-baseline.py`;
  `check-reachability.py`; `check-reachability-dispositions.py`;
  `check-ratchet-provenance.py`; `check-promotion-surface.py`;
  `check_direct_effects.py` — all exit 0. Running the vulture gate without its
  CI path arguments fails on `tests/`-scoped rows the blocking job never sees
  (the documented default-scan trap), which is an invocation error, not debt.
- mypy on `maistro/runs`, `maistro/config`, `maistro/security`,
  `maistro_server/api`: clean (remaining repo mypy errors are pre-existing
  import-stub issues in unrelated `cli`/`maistro_canvas` modules).

Known residuals, unchanged: RC/load evidence under #860 is an external-issue
dependency (delegated by this issue's own 2026-10-03 decomposition);
`pytest.mark.ac("SPEC-1182/AC-6")` at `test_resource_policy_health.py:99`
names no declared spec criterion (report-only bucket, like the two
pre-existing `SPEC-082226-2a10/AC-6` markers in the same file); the branch
needs a sync merge from `origin/develop` before integration — develop's delta
touches adjacent regions of `settings.py`/`store.py`/`sqlite_store.py`/
`pg_store.py`/`health.py`, so expect small same-region conflicts there.
