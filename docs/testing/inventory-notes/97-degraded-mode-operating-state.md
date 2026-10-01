---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---

# #97 Degraded mode as a user-facing operating state (M3-B7)

Turns Conductor degradation from startup logging into a coherent product
mode. `/health` now answers *what* is degraded and *why* (`degraded_services`,
`optional_routers`), a degraded router mount is written to the `/v1/audit`
trail as a warning, the app shell renders a degraded-capabilities banner, and
`hctl status` prints the same list. Recovery stays on the same surfaces:
`/health` recomputes per request, capability providers re-enter via
`/v1/capabilities/discover`, and optional routers recover by the restart
re-running the mount.

Six tests added in `packages/hive-conductor/backend/tests/test_degraded_mode_surface.py`:

- `test_health_names_degraded_optional_router_with_cause` — a failed router
  mount appears in `degraded_services` with its cause and flips `degraded`;
- `test_health_lists_each_degraded_capability_with_reason` — llm_gateway /
  memory_decay / log_redaction entries carry human-readable reasons;
- `test_health_reports_no_degradation_when_everything_is_healthy` — the full
  healthy picture: empty `degraded_services`, `degraded: false`, healthy
  routers excluded;
- `test_degraded_router_entry_is_auditable` — `optional_router_degraded`
  warning in the audit trail with module target and error detail;
- `test_unmounted_capability_is_a_404_not_fake_success` — an unmounted route
  family answers 404, never a fabricated 200;
- `test_recovery_when_optional_service_returns` — per-request recompute
  (LLM gateway entry clears when the env appears) plus restart re-mount
  (a fresh `_include_optional_router` success serves the capability).

The product E2E half is `packages/hive-conductor/frontend/e2e/degraded-mode.spec.ts`
(banner + `hctl status` against intercepted `/health` payloads); its
execution in a deployed stack is tracked in KNOWN-GAPS under #302.
