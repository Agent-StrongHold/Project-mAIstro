---
inventory-delta:
  packages/hive-conductor/backend/tests: +35
---

# auto-1048 — Workspace Home layout, projections and adaptive composition (#1048 backend slice)

Implementation record for lane L1048 (issue #1048, branch `auto-1048`, starting
head `35f2e0158a9138e592b56ed84bd08aa2e04c92a4`, develop base identical). The
prior attempt (job `58cbd185`) died on a provider 429 during preflight and
produced no work; nothing was salvaged because nothing existed. This round adds
the backend half of the adaptive Workspace Home contract:

- `services/home_layouts.py` — the Workspace-scoped, durable, revision-checked
  Home layout, with the user/Agent authority split enforced in the service:
  `compose_adaptive` refuses any payload that pins, rewrites or (when the user
  left no unpinned space) grows Home, so pin 0%/some/100% all hold regardless
  of caller.
- `services/home_projections.py` — read-time compact projections over the
  canonical services (missions, backlog, run inspection, chat sessions, design
  status, attention), honest `ok/empty/unavailable` per section, deterministic
  explainable adaptive candidates, and backend-recorded dismissals.
- `routes/home.py` — `/v1/workspaces/{id}/home/{layout,projections,adaptive}`
  mounted under the existing `/v1/workspaces` prefix (no new route-permissions
  prefix, no new exemption).
- `services/chat_completion.py` + `services/chat_gate.py` — the Workspace
  Agent's `compose_home_adaptive` and `dismiss_home_adaptive` tools, calling
  the same service functions the routes serve (Agent/API parity), classified
  as TOOL_EFFECT_MUTATE.
- `middleware/auth.py` — a named carve-out in `_required_permission`: Home
  sub-routes are per-member presentation writes (same posture as
  `PUT /v1/dashboard/layout`), membership- and viewer-checked in-route;
  `check_enumerations.py` re-run clean.
- `frontend/src/api/types.gen.ts` — regenerated from the backend OpenAPI
  document (`scripts/dump-hive-openapi.py` + `npm run gen:api`), stable across
  a second regeneration.

## Tests added (35)

- `tests/test_home_layout_service.py` — 22 tests: workspace-scoped keying,
  default-is-unpinned-and-not-persisted-on-read, restart durability over a
  real `State`/`PersistedStore`/SQLite file (closed and reopened), write
  refused when the store refuses, revision conflicts, duplicate region ids,
  two regions referencing one resource, pinned-space refusal in every
  direction (pin-in-payload, id-overlap rewrite, full-pin no-space,
  explicitly-emptied Home), pin/unpin as presentation-only, dismissal counts
  and workspace scoping.
- `tests/test_home_routes.py` — 13 tests: anonymous 401, non-member/missing
  404, viewer 403 on every write, default offered without persisting,
  save/GET round trip with revision, 409 carrying the stored layout, pin
  never forks the resource, projections carry canonical ids only (cross-checked
  against `stores.backlog_items`), honest empty sections, membership scoping,
  adaptive explain + dismissal durability, and the two parity tests (dismiss
  and compose through chat tool and through HTTP route land in one store).
- `tests/test_scope_coverage.py` — no count change: the four Home mutating
  paths were added to the *existing* `test_product_surface_is_not_gated`
  loop, asserting the daily account reaches them (the other half of the
  middleware carve-out) rather than adding node IDs.

## Validation executed at this head

- `uv run ruff check packages/hive-conductor/backend` → clean (whole-tree run
  below).
- Targeted pytest (backend on PYTHONPATH, uv-managed env):
  `test_home_layout_service.py test_home_routes.py` → 35 passed;
  `test_scope_coverage.py test_widget_tools.py test_dashboard_layout.py
  test_chat_voice_gates.py test_default_workspace.py` → 107 passed;
  `test_dashboard_layout_durability.py test_backlog_routes.py
  test_attention_projection.py test_workspaces.py` → 148 passed;
  `test_chat_session_ownership.py test_chat_routes.py
  test_chat_gate_scans_model_context.py test_chat_created_agents.py` →
  62 passed.
- Gates re-run first-party: `check_enumerations.py` (no new gaps; the
  pre-existing baselined `/v1/voice/intent` gap unchanged), 
  `check-route-permissions.py` (ok, 17 declared / 23 tolerated undeclared,
  none new), `check-api-route-contracts.py` (OK, 0 canned),
  `check-frontend-api-routes.py` (ok, 178 call sites resolve).

## Explicitly out of scope for this slice

The Home frontend shell, Dashboard retirement (cutover plan M3-E), workspace
scoping of chat sessions (#1822), the default-surface preference (#1050), and
LLM-driven (non-deterministic) adaptive selection. The backend contract this
slice lands is the part those consume: layout authority, projections, and the
Agent's two tools.
