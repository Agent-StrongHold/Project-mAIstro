---
inventory-delta:
  packages/hive-conductor/backend/tests: +64
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

## Repair round (coverage-gate + honest-answer fixes, +29 tests)

The merge-queue evaluation of this branch failed the diff-coverage gate: five
changed files sat below the 90% lines / 80% branch floors. Writing the tests
that close those gaps exposed two places where a projection could never answer
with its `ok` state in production, both now fixed in
`services/home_projections.py`:

- `_design()` read `configured`/`available` keys that
  `DesignServiceStatus.to_dict()` has never published (it publishes `ready`
  plus a recorded `cause`), so the design section answered "not configured"
  even over a ready service. It now consumes the real keys: a ready service is
  projectable, an unready one names its cause.
- `_backlog_candidate()` compared `item.priority == "critical"` against a
  model whose `priority` is an int (1 = highest, `models/backlog.py`), so the
  critical-priority adaptive candidate was unreachable. It now compares
  against the integer the model actually stores.

The repair also fixes a test that proved the wrong thing:
`test_composition_through_the_agent_tool_matches_the_route` asserted the
compose tool refuses a pinned payload, but its smuggle call ran after the
`_chat_workspace_id` context had been reset, so the refusal it observed was
the missing-Workspace one. The smuggle now runs inside the turn's Workspace
context and asserts the pinned-write refusal by name.

Tests added (+29):

- `tests/test_home_layout_service.py` (+8): region-id/resource-id shape
  refusals, the 48-region ceiling, the note-region and typed-region
  resource-pair contract (`LayoutError` both ways), read-back confirmation
  against a lying backend (`LayoutPersistenceError`), unreadable durable rows
  degrading to "not saved", stale-revision refusals on pin and compose, and
  late `register_json_store` wiring+initialization after
  `configure_persistence` (the `stores.py` path that wires a service-owned
  store mid-deployment).
- `tests/test_home_routes.py` (+21): 503 on a refused layout write, 422 on an
  invalid layout payload, unknown service failures propagating instead of
  being masked, 409 on a stale pin revision, 422 on pinning an unknown
  region, service-layer 404s behind the route's own check, the compose
  route's success envelope, runs/chat/design/attention section reads against
  shaped service answers (foreign runs skipped, untitled chat sessions falling
  back to their saved title, a ready design service projecting, attention
  entries mapping and unidentifiable ones skipping, `None` attention reading
  empty), non-member refusals at the service layer, blocked/critical/neutral
  adaptive backlog candidates, failed-run candidates scoped to the Workspace,
  and per-section degradation when the backlog or runs service fails. Plus the
  compose tool's malformed-payload, no-context, pinned/stale/invalid refusals
  and the dismiss tool's empty-identity refusal.

Validation executed at this repair head:

- `uv run pytest packages/hive-conductor/backend/tests` → 3720 passed,
  20 skipped (3740 collected; baseline 3711, delta +29 on top of this
  branch's earlier +35 — front-matter total +64).
- Hive suite under `coverage run --branch --source=packages/hive-conductor/backend`,
  then `scripts/check-diff-coverage.py coverage.xml --base <merge-base>` →
  ok: every measured file ≥ 90% lines / 80% branch arcs (was FAIL on five
  files before this round).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1322 reviewed identities = 1322 findings
  (the two production fixes eliminated no banked identity and added none).
- `scripts/check-ratchet-provenance.py`, `check-shipped-surface-truth.py`,
  `check-owned-store-access.py`, `check-public-routes.py`,
  `check-frontend-api-routes.py`, `check-frontend-typed-client.py`,
  `check-merge-markers.py`, `verify-monorepo-layout.sh` → all ok.
- OpenAPI types gate: `dump-hive-openapi.py` + `npm run gen:api` →
  `types.gen.ts` regenerated byte-identical (no diff).
- `uv run ruff check .` and `uv run ruff format --check .` → clean.

## Explicitly out of scope for this slice

The Home frontend shell, Dashboard retirement (cutover plan M3-E), workspace
scoping of chat sessions (#1822), the default-surface preference (#1050), and
LLM-driven (non-deterministic) adaptive selection. The backend contract this
slice lands is the part those consume: layout authority, projections, and the
Agent's two tools.
