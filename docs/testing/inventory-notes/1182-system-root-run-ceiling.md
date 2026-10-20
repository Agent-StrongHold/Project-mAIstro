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
