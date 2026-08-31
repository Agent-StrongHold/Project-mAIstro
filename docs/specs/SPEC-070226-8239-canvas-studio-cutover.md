---
id: SPEC-070226-8239
title: "Canvas Studio ↔ maistro-server /v2/canvas API cutover"
repo: maistro-engine
kind: spec
status: Will Not Implement
created: 2026-07-02
rejected: 2026-08-31
substrate:
  - maistro-engine#ADR-045
  - maistro-engine#ADR-076
  - maistro-engine#SPEC-229
implements:
  - maistro-engine#ADR-045
related:
  - maistro-engine#ADR-042
  - maistro-engine#SPEC-183
  - maistro-engine#SPEC-184
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: UserClient
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-07-02
  - status: Will Not Implement
    date: 2026-08-31
---

# SPEC-070226-8239: Canvas Studio ↔ maistro-server /v2/canvas API cutover

## Current disposition

This specification is **Will Not Implement** in its proposed form. It treats
Canvas Studio as a separate user-facing product whose frontend is migrated as
an independent application. The current product contract in #286 and #95 makes
**Design Studio** the parent creative-production surface and **Canvas** a
capability/tool boundary inside that product.

The route and API observations below remain historical input. Any useful
Canvas API migration work must be revalidated against the live #95 Design
Studio cutover and canonical execution/tool boundaries rather than implementing
this separate-Studio contract.

## Context

Canvas Studio (the book-maker frontend, a separate app from maistro-engine) currently calls the
Canvas ability routes in `packages/maistro-canvas/src/maistro_canvas/canvas/routes.py` directly
(localhost HTTP, tight coupling). ADR-045 calls for a cutover to a clean API boundary:
`maistro-server` exposes `/v2/canvas` versioned routes (ADR-076 content negotiation) that proxy or
wrap the canvas ability, and Studio calls those instead. This decouples the frontend from the core
library and establishes a canonical HTTP API boundary.

The cutover is phased: Phase 1 (Studio → server) runs in parallel with the old direct routes
still working; Phase 2 deprecates the old routes; Phase 3 removes them.

## Goals

- Establish `/v2/canvas/*` as the canonical API boundary for Canvas operations (ADR-042/076).
- Studio calls only `maistro-server`, never `maistro-canvas` routes directly.
- No change to Canvas ability internals (SPEC-229 unchanged); server routes wrap or proxy only.
- Support content negotiation for response format (ADR-076).
- Maintain backward compatibility during Phase 1 (old routes still work).

## Non-goals

- Rewriting Canvas ability internals (out of scope; SPEC-229 is done).
- Multi-tenant Canvas API (Stronghold); engine stays single-instance.
- Real-time canvas updates via WebSocket Phase 1 (defer to Phase 2).

## Decision

### API surface (/v2/canvas/*)

```python
# GET /v2/canvas/designs — list all designs
# POST /v2/canvas/designs — create new design
# GET /v2/canvas/designs/{design_id} — fetch design metadata + content
# PUT /v2/canvas/designs/{design_id} — update design (title, description, content)
# DELETE /v2/canvas/designs/{design_id} — soft-delete design
# POST /v2/canvas/designs/{design_id}/publish — publish to print-on-demand
# GET /v2/canvas/designs/{design_id}/export/{format} — export (PDF, PNG, SVG)
# POST /v2/canvas/designs/{design_id}/thumbnail — generate/refresh thumbnail
# GET /v2/canvas/assets — list all canvas assets (images, shapes, templates)
# POST /v2/canvas/designs/{design_id}/generate-ai — request LLM-driven design generation
```

All routes:
- Accept `Authorization: Bearer <session>` (ADR-077 session auth).
- Return `application/json` by default; support `application/vnd.canvas+json` (v2) via Accept header
  (ADR-076; v1 response shape deferred).
- Emit canvas-specific events (design.created, design.updated, etc.) to the reactor bus (ADR-086).
- Record audit trail via ADR-037 observability.

### Phase 1 — Route proxy (Studio→server, old routes still work)

`packages/maistro-server/src/maistro_server/api/routes/canvas.py` (new):

```python
from maistro_canvas.canvas.store import CanvasStore
from maistro_canvas.canvas.executor import CanvasActionExecutor

@router.get("/v2/canvas/designs")
async def list_designs(req: Request) -> list[CanvasRecord]:
    """Proxy to CanvasStore.list_designs()."""
    store = req.app.state.canvas_store  # injected by container
    return await store.list_designs(req.user.id)

@router.post("/v2/canvas/designs")
async def create_design(req: Request, body: CreateDesignRequest) -> CanvasRecord:
    """Proxy to CanvasStore.create()."""
    ...
```

Old routes in `maistro-canvas/canvas/routes.py` remain unchanged; Studio can call either. Hive
Conductor backend calls server routes (not canvas routes directly).

### Phase 2 — Deprecation + WebSocket upgrade (optional)

Emit `HTTP 200 with Deprecation: true` header on old canvas routes. Studio emits console warning.
Optional: add `/v2/canvas/designs/{id}/stream` (POST with messages → SSE or WS) for real-time
updates (depends on ADR-086 events finishing first).

### Phase 3 — Remove old routes (future)

Delete `maistro-canvas/canvas/routes.py` after cutover confirmed (at least 2 deployment cycles).
Users have only `/v2/canvas` to call.

### Content negotiation (ADR-076)

```
Request: GET /v2/canvas/designs/abc Accept: application/vnd.canvas+json;version=2
Response: 200 OK, Content-Type: application/vnd.canvas+json;version=2, {design fields per v2 schema}

Request: GET /v2/canvas/designs/abc Accept: application/json
Response: 200 OK, Content-Type: application/json, {design fields per default schema}
```

Version evolution handled per ADR-076 (header-based routing in `maistro-server/main.py`).

## Acceptance criteria

- [ ] `/v2/canvas/designs`, `/v2/canvas/designs/{id}`, `/v2/canvas/designs/{id}/export/{format}`
      routes exist and are reachable (no auth required for public designs, session-required for
      private; property: all route handlers use the same auth middleware as other v2 routes).
- [ ] GET `/v2/canvas/designs` returns a list of `CanvasRecord` (type matches SPEC-229).
- [ ] POST `/v2/canvas/designs` with a valid `CreateDesignRequest` creates a design and returns
      the full record (idempotent on request ID if present).
- [ ] PUT `/v2/canvas/designs/{id}` updates title/description/content; any field omitted in the
      body is unchanged (PATCH semantics for content, PUT semantics for metadata).
- [ ] DELETE `/v2/canvas/designs/{id}` soft-deletes (marks `deleted_at`, does not hard-delete);
      GET returns 404 after soft-delete (property: soft-delete is reversible via admin API for Phase 2).
- [ ] `/v2/canvas/designs/{id}/export/pdf` accepts `format: pdf|png|svg` and streams a binary
      response with correct `Content-Type` and `Content-Disposition: attachment`.
- [ ] Studio frontend (separate app) calls only `/v2/canvas` routes, zero calls to
      `localhost:8000/canvas` (old routes) in production code (CI: grep for direct canvas imports
      in frontend package).
- [ ] All routes emit events to the reactor bus per ADR-086 (design.created, etc.; property:
      every route that mutates emits exactly one event, no duplicates).
- [ ] Old canvas routes in `maistro-canvas/routes.py` still work (backward compatibility test:
      POST to old /canvas/designs works identically to /v2/canvas/designs).
- [ ] Content negotiation works (Accept header `application/vnd.canvas+json;version=2` returns v2
      schema; `application/json` returns default).

## Testing

- Unit: each route handler against a fake `CanvasStore` (mock in-memory store).
- Integration: Studio frontend (separate repo) points at server `/v2/canvas` routes and exercises
  the full flow (create, edit, export, publish).
- Backward compat: old `/canvas/designs` routes tested in parallel; both should return identical
  results for the same operation.
- Property (formal/): "exporting a design to PDF with width > 8000px and height > 8000px produces
  a valid PDF that reads correctly" (via PDF validation library).
- Load test: 100 concurrent design fetches against the store (verify no race conditions,
  especially on soft-delete).

## Open questions

- Should Phase 1 include real-time collaboration (multiple users editing one design) via WebSocket,
  or is that Phase 2? (Leaning: Phase 2, after ADR-086 events are finalized.)
- Studio's image-generation endpoint (`/generate-ai`) — does it stay in Studio backend or move
  into engine as `/v2/canvas/designs/{id}/generate-ai`? (Deferred: keep in Studio for now, call
  engine if needed.)
- Admin soft-delete-recovery endpoint — include in Phase 1 or defer to Phase 2? (Deferred to Phase 2.)

## References

- [ADR-045: Canvas Studio ↔ maistro-server /v2/canvas Cutover](../adr/ADR-045-canvas-studio-engine-cutover.md)
- [ADR-076: HTTP API Versioning via content negotiation](../adr/ADR-076-http-api-versioning.md)
- [ADR-042: Canvas Asset HTTP Routes](../adr/ADR-042-canvas-asset-routes.md)
- [SPEC-229: Canvas asset compositor](SPEC-229-canvas-asset-compositor.md)
- Canvas Studio frontend (separate repository).
