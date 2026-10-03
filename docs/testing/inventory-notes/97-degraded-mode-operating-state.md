---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
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

Seven tests added in `packages/hive-conductor/backend/tests/test_degraded_mode_surface.py`:

- `test_health_names_degraded_optional_router_with_cause` — a failed router
  mount appears in `degraded_services` with its cause and flips `degraded`;
- `test_health_lists_each_degraded_capability_with_reason` — llm_gateway /
  memory_decay / log_redaction entries carry human-readable reasons;
- `test_health_reports_no_degradation_when_everything_is_healthy` — the full
  healthy picture: empty `degraded_services`, `degraded: false`, healthy
  routers excluded;
- `test_degraded_router_entry_is_auditable` — `optional_router_degraded`
  warning in the audit trail with module target and error detail;
- `test_audit_failure_never_breaks_startup` — with `log_audit` raising, the
  mount failure is still recorded on `app.state` and warned about; startup
  proceeds exactly as without the audit hook;
- `test_unmounted_capability_is_a_404_not_fake_success` — an unmounted route
  family answers 404, never a fabricated 200;
- `test_recovery_when_optional_service_returns` — per-request recompute
  (LLM gateway entry clears when the env appears) plus restart re-mount
  (a fresh `_include_optional_router` success serves the capability).

The product E2E half is `packages/hive-conductor/frontend/e2e/degraded-mode.spec.ts`
(banner + `hctl status` against intercepted `/health` payloads); its
execution in a deployed stack is tracked in KNOWN-GAPS under #302.

## CI-repair addendum: frontend-typed-client ratchet

The `frontend-typed-client` ratchet (#1048 P0.3) landed after this branch and
flags it at the merge queue: the new `DegradedBanner` raw `fetch("/health")`
and local `DegradedService` type are unbanked debt, and inserting the banner
import/render plus the CLI degraded-status block shifted four pre-existing
banked `raw_fetch` rows (`AppShell.tsx` logout, `CLI.tsx` agents/health/
sessions) onto new line-keyed identities, which the gate reads as fix+new.

Repair (all gate-sanctioned, no runtime behavior change to pre-existing code):

- `DegradedBanner` now fetches through the shared client (`apiGet`), keeping
  the deliberate silent-on-failure contract — new code adds no raw-fetch debt;
- the local `DegradedService` type carries a `frontend-typed-client: allow`
  waiver: `/health` returns a plain dict (no `response_model`), so no
  generated OpenAPI type exists to import instead;
- the four drifted pre-existing fetches carry waivers noting the drift cause
  (migrating them to the typed client is #1048 cutover work, not #97);
- `quality/frontend-typed-client-baseline.json` was rewritten with
  `--write-baseline` so the candidate ledger matches the tree exactly. The
  ratchet strictly shrinks against the base: raw fetch 64 → 60, hand-typed
  142 → 142. No grant was needed (none exists for this ratchet, and grants
  are read from the merge base anyway).

Verified locally: `check-frontend-typed-client.py` exits 0;
`check-frontend-api-routes.py` ok (230 routes); `tsc --noEmit` clean;
`eslint` clean within the warning budget; the 7 degraded-mode backend tests
still pass.

