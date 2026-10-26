# Issue #325 repair round 5 — focused acceptance re-validation (no code changes)

Starting head `c762cea0ac82` (= PR #2298 head, the round-4 exit head). The
previous round's dispatch failed on a provider timeout and an incomplete
context capture (`commits/34d1ef0dffe4.../statuses` uncollectable); this
round's dispatch-context.json contains that statuses source, so the block is
resolved by capture, not by code. Merge-queue evaluation was already green.
No production or test code was touched; this round re-proves every acceptance
criterion against reachable behavior and records the evidence.

## Criteria -> executed evidence

- **Inventory every durable table (incl. `security_violations`, `usage_events`).**
  `uv run python3 scripts/check-durable-table-inventory.py` (CI's exact
  invocation, `.github/workflows/ci.yml:253`) -> `ok: 123 durable tables,
  each with a declared retention`. The gate hard-pins both named tables
  (`REQUIRED_TABLES`); `usage_event_aggregates` is also present.
- **Policy for every table.** `quality/durable-table-retention.json`: 123 rows,
  all `retention` values from the closed enum {run_purge 5, ttl_purge 3,
  window_prune 1, bounded_by_parent 14, indefinite_by_decision 12, undecided
  88}. `undecided` is a *recorded* decision ("no production-driven deletion
  path on every listed backend today"), tracked on the named issue per the
  registry `_doc` — the anti-pattern the issue targets is retention decided by
  omission, which the gate now makes impossible.
- **Quota raw vs aggregate; deleting raw rows cannot corrupt enforced quota.**
  `SqliteUsageLog.purge_expired` upserts per-(scope, day) sums into
  `usage_event_aggregates` and deletes the same bounded batch in one
  `BEGIN IMMEDIATE` transaction. Tests passed:
  `test_purge_aggregates_before_deleting_and_respects_boundary`,
  `test_repeated_bounded_purges_never_double_count_aggregates`,
  `test_purge_then_snapshot_does_not_double_count_idle_scope`.
- **Security/audit evidence + lawful deletion.** Purges delete only expired
  evidence, never `security_strikes` or live leased rows, with explicit legal
  hold sets; tamper-evident history/lawful-deletion policy is a recorded
  product decision (`quality/...retention.json` `policy_scope` ->
  `docs/adr/OUT-OF-SCOPE.md`, 2026-09-23). Tests passed:
  `test_tracker_purge_legal_hold_compiles_the_held_scoped_query`,
  `test_purge_expired_respects_boundary_and_legal_hold`.
- **Run retention Workspace-safe, referentially complete (#1175).** #1175 is
  **closed** (2026-10-24, per dispatch context). Every `run_id`-bearing table
  must be named in `retention_scope.RUN_REFERENCING_TABLES`, machine-checked by
  `test_retention_reference_inventory.py`; cross-Workspace isolation is
  `test_one_workspaces_sweep_cannot_touch_another`. All passed.
- **Durable/observable/idempotent/bounded/multi-replica purges.** Batch limits
  with nonpositive rejection tests; one-transaction aggregate-then-delete;
  SQLite `BEGIN IMMEDIATE` / PostgreSQL `FOR UPDATE SKIP LOCKED` sweep
  coordination. Archive/conformance suites: 220 passed.
- **Health/metrics.** All eight series exist in
  `packages/maistro-core/src/maistro/observability/metrics.py:617-654`
  (`purged_total`, `backlog_remaining`, `backlog_age_seconds`,
  `sweep_last_success_timestamp`, `sweep_failures_total`, `table_rows`,
  `table_bytes`, `oldest_record_timestamp`); backed by
  `tests/observability/test_retention_health.py` and per-scope backlog tests
  in `test_retention_policy.py`. A failed sweep advances failures and never
  the last-success timestamp (`test_a_failed_sweep_is_counted_and_never_reported_successful`).
- **Backup/restore/legal-hold explicit.** `docs/persistence/retention-runbook.md`
  §"Backup, restore, and holds"; restore re-runs the bounded sweep idempotently
  (restore-idempotency tests in `test_sqlite_usage_log.py`).
- **Tests cover the eight named scenarios.** expiry boundaries
  (`test_purge_aggregates_before_deleting_and_respects_boundary`,
  `test_an_expired_terminal_run_is_purged`/`..._survives`),
  restart (`test_canonical_invocation_provenance_survives_a_restart`),
  concurrent sweepers (`test_concurrent_admissions_produce_one_sweep`),
  cross-Workspace isolation (above), raw->aggregate (above), partial failure
  (`test_a_failed_purge_commits_nothing_and_leaves_the_store_usable`,
  `test_commit_success_then_failure_is_safe_to_retry`), legal hold (above),
  empty policy (`test_an_unbounded_policy_never_sweeps`,
  `test_a_sweeper_with_no_scope_deletes_nothing`).
- **DoD.** No accidental indefinite retention (123/123 declared); #1175
  closed; inventory machine-readable and CI-checked (`ci.yml:253`).

## Commands run this round (all green)

- `uv run python3 scripts/check-durable-table-inventory.py` -> ok, 123 tables
- `uv run pytest packages/maistro-core/tests/runs/test_retention_policy.py
  .../test_retention_conformance.py .../test_retention_reference_inventory.py
  .../test_retention_scope_conformance.py .../test_chat_retention_sweep.py -q`
  -> 112 passed, 30 skipped (PG-dependent)
- `uv run pytest packages/maistro-core/tests/quota/test_sqlite_usage_log.py
  .../persistence/test_session_ttl_purge.py .../persistence/test_sqlite_audit.py
  .../observability/test_retention_health.py .../events/test_durable_log.py
  .../tasks/test_idempotency_purge_driven.py .../security/test_pg_strikes.py
  .../persistence/test_pg_audit.py -q` -> 163 passed, 13 skipped
- `uv run pytest packages/maistro-core/tests/runs/test_archive_conformance.py
  .../test_archive_sweep.py .../test_archive_sweeper.py
  .../events/test_durable_store_conformance.py
  .../persistence/test_backend_conformance.py -q` -> 220 passed, 112 skipped
- `uv run ruff check .` -> All checks passed; `uv run ruff format --check .`
  -> 3530 files already formatted
- `uv run python scripts/check-suite-inventory.py` -> ok, 21 suites match
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> 1256/1256, ok

No test additions this round, so no suite-inventory delta note is required.
Residual: PG-only paths (SKIP LOCKED races, pg probe) skip locally without a
live Postgres; they are exercised by the hosted PG jobs, which were green at
the last merge-queue evaluation.
