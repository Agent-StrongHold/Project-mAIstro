---
inventory-delta:
  packages/maistro-core/tests: +4
---
# auto-325-cb9e: sweep-health metrics for retention (#325)

All four additions are in `packages/maistro-core/tests/runs/test_retention_policy.py`,
and they close the #325 health-metrics gap the owner decision of 2026-09-23
kept in scope ("Health metrics: backlog age, rows and bytes, last sweep,
failures") for the parts a sweeper can publish without a cross-store scanner:
last successful sweep, failures, and backlog age. Every case asserts deltas or
fake-clock-exact values, never wall-clock luck:

- `test_a_failed_sweep_is_counted_and_never_reported_successful`: a failed
  `maybe_sweep` increments `maistro_retention_sweep_failures_total` for its
  authorization mode and leaves `maistro_retention_sweep_last_success_timestamp`
  untouched — the runbook contract "a failed sweep is not reported as
  successful" becomes a checkable series rather than prose.
- `test_an_operator_sweep_failure_counts_and_still_raises`: `sweep_now` keeps
  propagating the store's exception in the operator's face, and the failure is
  still counted on the same series.
- `test_a_committed_sweep_publishes_its_success_time_by_mode`: a committed
  sweep publishes a real unix timestamp on its mode's series only; the other
  mode's last-success time does not move.
- `test_backlog_age_oldest_scope_and_drains_to_zero`: with `retention.time`
  replaced by a fake clock, `maistro_retention_backlog_age_seconds` follows
  the oldest standing backlogged scope of its mode exactly (0 → 7.0 s),
  a global-mode backlog neither resets nor extends the workspace-mode age,
  draining returns the age to zero, and a re-report of a still-backlogged
  global scope ages the original entry (3.0 s), not the last report.
