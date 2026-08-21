---
id: ADR-042
title: Canvas Asset HTTP Routes
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-09
substrate:
  - maistro-engine#ADR-039
  - maistro-engine#ADR-040
  - maistro-engine#ADR-041
  - maistro-engine#ADR-031
  - maistro-engine#ADR-032
implements: []
related:
  - maistro-engine#ADR-019
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-canvas/tests/test_asset_routes.py
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-09
---

# ADR-042: Canvas Asset HTTP Routes

## Context

ADR-040 ships persistence; ADR-041 ships compositing logic. Both are
in-process. Canvas Studio's frontend (and any future agent client)
needs an HTTP surface to read/write the new model.

The legacy `canvas/routes.py` exposes the old `LayerRecord` model. We
add a sibling router for the ADR-039 model so the two can co-exist
during the migration.

## Decision

Engine ships **`maistro_canvas.canvas.asset_routes`**, a FastAPI
`APIRouter` mounted under `/v2/canvas` to leave the legacy
`/v1/canvas` paths alone. Endpoints are thin wrappers around the
asset store + compositor; Pydantic models define the request/response
schemas for OpenAPI generation.

### Endpoints

```
# AssetDefinition
POST   /v2/canvas/asset-definitions                 — register
GET    /v2/canvas/asset-definitions/{asset_id}      — get
GET    /v2/canvas/asset-definitions?kind=structure  — list by kind
PUT    /v2/canvas/asset-definitions/{asset_id}      — update

# AssetSheet
PUT    /v2/canvas/asset-sheets/{asset_id}                 — upsert
GET    /v2/canvas/asset-sheets/{asset_id}                 — get
POST   /v2/canvas/asset-sheets/{asset_id}/regenerate      — bump revision

# AssetInstance
POST   /v2/canvas/asset-instances                       — upsert
GET    /v2/canvas/asset-instances/{instance_id}         — get
DELETE /v2/canvas/asset-instances/{instance_id}         — remove
GET    /v2/canvas/canvases/{canvas_id}/instances        — list

# ChildProfile
PUT    /v2/canvas/child-profiles/{profile_id}           — upsert
GET    /v2/canvas/child-profiles/{profile_id}           — get

# Book
POST   /v2/canvas/books                                 — create
GET    /v2/canvas/books/{book_id}                       — get
PUT    /v2/canvas/books/{book_id}                       — update

# Render plan (compositor wrapper, ADR-041)
POST   /v2/canvas/canvases/{canvas_id}/plan             — plan_render
```

### Pydantic boundary models

For each domain dataclass in `layers.py` and `asset_store.py` there
is a matching Pydantic model that mirrors its shape. The route
handler converts via the existing `_ser_*` / `_deser_*` helpers in
`asset_store.py` (single source of truth for shape) — Pydantic
validates the JSON envelope, and the dataclass remains the in-memory
representation.

Fields that aren't trivially typed (e.g. `pose_geometry` is a tagged
union of three shapes) are accepted as `dict[str, Any]` and validated
on the inner deserialiser. This keeps the wire schema honest with the
domain types without re-encoding their discriminators in two places.

### Status codes and error mapping

| Domain error                          | HTTP   |
|---------------------------------------|--------|
| `AssetDefinitionNotFoundError`        | 404    |
| `AssetSheetNotFoundError`             | 404    |
| `OcclusionCycleError`                 | 422    |
| `SkinBindingError`                    | 422    |
| `MissingSocketError`                  | 422    |
| `PoseGeometryMismatchError`           | 422    |
| `WorldStyleConflictError`             | 422    |
| `ValueError` (e.g. duplicate id)      | 400    |
| Pydantic `ValidationError`            | 422 (FastAPI default) |

All errors return `{"detail": "<message>", "code": "<DOMAIN_CODE>"}`.

### Dependency injection

The router takes a `get_store` callable as a FastAPI dependency:

```python
def make_router(get_store: Callable[[], AssetStore]) -> APIRouter: ...
```

Standalone Canvas Studio wires `InMemoryAssetStore` for tests and
`PostgresAssetStore` (with an async session factory) for production.
maistro-server will mount this router via the same factory after the
cutover.

## Boundary contracts

- All request bodies validate via Pydantic; invalid JSON returns 422.
- `register` (POST asset-definitions) is idempotent at the store level
  per ADR-040; HTTP returns 200 with the canonical row on a no-op,
  201 when a new row is created.
- `regenerate_sheet` (POST .../regenerate) returns the new sheet with
  `revision` strictly greater than the prior, or 404 if no prior and
  no `refs` provided.
- `plan` (POST .../plan) returns the `RenderPlan` shape from ADR-041,
  with `OcclusionCycleError` / `SkinBindingError` mapped to 422.

## Behavioural contracts

- All `GET`s are read-only and side-effect free.
- `DELETE /asset-instances/{id}` orphans children (cascades parent_id
  to NULL) per ADR-040; the returned status is 204 with empty body.
- `PUT` endpoints validate the path id matches the body id (`409` if
  not) to catch frontend bugs early.
- `POST /canvases/{canvas_id}/plan` is a pure function of its inputs.
  Repeated identical calls return identical `RenderPlan` JSON.

## Consequences

- ADR-043 (executor + tool) builds the agent integration on top of
  these routes — the davinci tool calls them via an HTTP client.
- The legacy `canvas/routes.py` is unchanged; both routers can mount
  alongside each other on the same FastAPI app.
- The Express → FastAPI cutover on canvas-studio-poc has a concrete
  surface to point at.

## Out of scope

- Authentication / authorisation hardening — the existing `auth.py`
  scheme applies at the FastAPI app level, not in the router itself.
- Streaming endpoints (e.g. SSE for generation progress) — separate
  ADR for the job-progress channel.
- Pagination — small canvases don't need it; revisit when v2.0
  multi-tenant arrives.

## Source references

- `packages/maistro-canvas/src/maistro_canvas/layers.py`
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_store.py`
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_compositor.py`
- `packages/maistro-canvas/src/maistro_canvas/canvas/routes.py` —
  legacy router, unchanged.

## Links

- PR: (this PR)
- Follow-up ADRs: ADR-043 (executor + tool integration)
