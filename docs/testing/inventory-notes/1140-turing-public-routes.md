---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-turing/backend/tests: +5
  packages/maistro-core/tests: +4
  tests/: +21
---

# Turing public-route gate inventory

Issue #1140 adds shared Conductor/Turing route-policy fixtures covering protected and public declarations, missing declarations, expired exemptions, exact-route lookalikes, ambiguous runtime declarations, and trusted-base policy ratcheting (+21 collected cases and five Turing runtime authorization cases). The fixtures now audit both live FastAPI route trees, including lazy nested routers and WebSocket routes. The shared runtime matcher is used by both backends and the gate; Conductor's suffix carve-outs are removed so an undeclared or misleading route cannot become authenticated-only by name. Runtime fixtures also prove that an authenticated Conductor user without `config.write` cannot read settings, the existing authenticated-user chat surface retains its product authorization, and Turing service keys cannot inherit a sibling route's scope.

Repair follow-up (container-layout registry resolution and behavior parity):

- `packages/maistro-core/tests/security/test_route_registry_location.py` (+4) pins `locate_route_registry`: monorepo-checkout resolution, the packaged hive layout (`/app/backend/middleware` -> `/app/quality`), a shallow two-level layout that previously raised `IndexError` at import in the production container, and fail-closed behavior when no parent carries the registry.
- `tests/test_m1_542_policy_coverage.py::test_public_routes_main_covers_missing_success_and_new_surface_paths` now installs fixtures for both middleware files and both registries, and proves `main()` succeeds only when the Conductor and Turing public declarations are both present in the candidate registry (the previous fixture covered Conductor only, so the Turing audit failed the success path).
- `packages/hive-conductor/backend/tests/test_api.py::test_elevation_only_activates_granted_permissions` (rewritten assertion, net +1 line) pins that DELETE under `/v1/settings` requires the heavier `config.delete` permission even for an account elevated with `config.write` — the middleware refuses before routing, matching the pre-#1140 permission table restored in `quality/route-permissions.json`.
- `tests/test_check_enumerations.py::test_committed_baseline_is_well_formed` (rewritten in place) accepts the fully-repaid baseline state: when the routes gap was fixed the ratchet demanded the entry be pruned, and the doctrine "an empty baseline should be deleted" means the file's absence is the clean state (`load_baseline` reads an absent file as zero debt). The `tests/` delta also absorbs +3 pre-existing unrecorded node growth that already drifted at the merge base: the collected node-ID sets are byte-identical between the base revision and this head, so the correction records the merge's growth rather than any new test from this lane.
